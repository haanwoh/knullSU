"""``plxd`` — the PocketLinux supervisor daemon.

Design goals, in order: (1) never leave orphan processes behind, (2) survive a
crashing child with bounded backoff, (3) be debuggable with ``cat`` and
``tail`` only.  Every child runs in its own session, output goes straight to
``~/.plx/logs/<name>.log``, and state is mirrored to a JSON file so
``plx service status`` still works when the socket has gone away.

Run it in the foreground with ``plx service daemon``; start it detached with
``plx service up``.
"""

from __future__ import annotations

import argparse
import json
import os
import select
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import __version__, console, paths, supervisor, util

MAX_LOG_BYTES = 5 * 1024 * 1024
MAX_REQUEST_BYTES = 1024 * 1024
SIGNALS = {
    "TERM": signal.SIGTERM,
    "INT": signal.SIGINT,
    "HUP": signal.SIGHUP,
    "QUIT": signal.SIGQUIT,
    "KILL": signal.SIGKILL,
}


@dataclass
class Runtime:
    """Live state of one supervised service."""

    spec: supervisor.ServiceSpec
    state: str = "stopped"  # stopped|running|restarting|failed|disabled
    proc: subprocess.Popen[bytes] | None = None
    log_handle: Any = None
    started_at: float | None = None
    restarts: int = 0
    restart_times: list[float] = field(default_factory=list)
    last_exit: int | None = None
    last_error: str | None = None
    next_start: float | None = None
    stopped_by_user: bool = False

    # -- derived ---------------------------------------------------------
    @property
    def pid(self) -> int | None:
        return self.proc.pid if self.proc is not None else None

    def uptime(self) -> float | None:
        if self.proc is None or self.started_at is None:
            return None
        return max(0.0, time.monotonic() - self.started_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.spec.name,
            "state": self.state,
            "pid": self.pid,
            "restarts": self.restarts,
            "uptime": round(self.uptime(), 1) if self.uptime() is not None else None,
            "last_exit": self.last_exit,
            "last_error": self.last_error,
            "restart_policy": self.spec.restart,
            "command": " ".join(self.spec.argv()),
            "description": self.spec.description,
            "next_start_in": (
                round(max(0.0, (self.next_start or 0) - time.monotonic()), 1)
                if self.next_start
                else None
            ),
        }


class Supervisor:
    """Owns child processes and the control socket."""

    def __init__(
        self,
        specs: dict[str, supervisor.ServiceSpec],
        *,
        services_path: Path | None = None,
        socket_path: Path | None = None,
        state_file: Path | None = None,
        log_dir: Path | None = None,
        poll: float = 0.15,
    ) -> None:
        self.services_path = Path(services_path) if services_path else paths.services_file()
        self.socket_path = Path(socket_path) if socket_path else paths.socket_path()
        self.state_path = Path(state_file) if state_file else paths.state_file()
        self.log_dir = Path(log_dir) if log_dir else paths.log_dir()
        self.poll = poll
        self.runtimes: dict[str, Runtime] = {
            name: Runtime(spec=spec, state="stopped" if spec.enabled else "disabled")
            for name, spec in specs.items()
        }
        self.started_at = time.time()
        self._stop = False
        self._dirty = True

    # -- logging ---------------------------------------------------------
    def _rotate_log(self, name: str) -> Path:
        log_path = self.log_dir / f"{name}.log"
        try:
            if log_path.exists() and log_path.stat().st_size > MAX_LOG_BYTES:
                rotated = log_path.with_suffix(".log.1")
                rotated.unlink(missing_ok=True)
                log_path.rename(rotated)
        except OSError:
            pass
        return log_path

    def _note(self, level: str, message: str) -> None:
        line = f"{util.now_iso()} [{level}] {message}\n"
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            with open(self.log_dir / "plxd.log", "a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError:
            pass
        if sys.stdout.isatty() and not console.json_mode():
            print(line.rstrip(), file=sys.stderr, flush=True)

    # -- child lifecycle -------------------------------------------------
    def _spawn(self, rt: Runtime) -> None:
        spec = rt.spec
        argv = spec.argv()
        rt.next_start = None
        if not argv:
            rt.state = "failed"
            rt.last_error = "empty command"
            self._dirty = True
            return

        cwd = spec.dir
        if cwd and not Path(cwd).is_dir():
            self._note("warn", f"{spec.name}: dir {cwd} missing — using default")
            cwd = None

        log_path = self._rotate_log(spec.name)
        try:
            handle = open(log_path, "ab", buffering=0)
        except OSError as exc:
            rt.state = "failed"
            rt.last_error = f"cannot open log: {exc}"
            self._dirty = True
            return

        env = {**os.environ, **spec.env, "PLX_SERVICE": spec.name}
        try:
            proc = subprocess.Popen(  # noqa: S603 - argv comes from the user's own config
                argv,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except (OSError, ValueError) as exc:
            handle.close()
            rt.state = "failed"
            rt.last_error = f"spawn failed: {exc}"
            self._note("error", f"{spec.name}: {exc}")
            self._dirty = True
            return

        rt.proc = proc
        rt.log_handle = handle
        rt.state = "running"
        rt.started_at = time.monotonic()
        rt.stopped_by_user = False
        rt.last_error = None
        self._dirty = True
        self._note("info", f"{spec.name}: started pid {proc.pid}")

    def _signal(self, rt: Runtime, name: str) -> None:
        if rt.proc is None:
            return
        signum = SIGNALS.get(name.upper(), signal.SIGTERM)
        try:
            os.killpg(os.getpgid(rt.proc.pid), signum)
        except (ProcessLookupError, PermissionError):
            try:
                rt.proc.send_signal(signum)
            except (ProcessLookupError, OSError):
                pass

    def _close_log(self, rt: Runtime) -> None:
        if rt.log_handle is not None:
            try:
                rt.log_handle.close()
            except OSError:
                pass
            rt.log_handle = None

    def _reap(self) -> None:
        for rt in self.runtimes.values():
            if rt.proc is None:
                continue
            code = rt.proc.poll()
            if code is None:
                continue
            rt.last_exit = code
            rt.proc = None
            rt.started_at = None
            self._close_log(rt)
            if rt.stopped_by_user or rt.state == "stopping":
                rt.state = "stopped"
                self._dirty = True
                self._note("info", f"{rt.spec.name}: stopped (exit {code})")
                continue
            self._schedule_restart(rt, code)

    def _schedule_restart(self, rt: Runtime, code: int) -> None:
        spec = rt.spec
        ok_exit = code == 0
        if spec.restart == "never" or (spec.restart == "on-failure" and ok_exit):
            rt.state = "stopped" if ok_exit else "failed"
            self._dirty = True
            self._note("info", f"{spec.name}: exit {code} — not restarting ({spec.restart})")
            return

        now = time.monotonic()
        rt.restart_times = [t for t in rt.restart_times if now - t < spec.restart_window]
        if len(rt.restart_times) >= spec.max_restarts:
            rt.state = "failed"
            rt.last_error = (
                f"gave up after {spec.max_restarts} restarts in {spec.restart_window:.0f}s"
            )
            self._dirty = True
            self._note("error", f"{spec.name}: {rt.last_error}")
            return

        rt.restart_times.append(now)
        rt.restarts += 1
        rt.state = "restarting"
        rt.next_start = now + spec.restart_delay
        self._dirty = True
        self._note(
            "warn",
            f"{spec.name}: exit {code} — restart #{rt.restarts} in {spec.restart_delay:.1f}s",
        )

    def _tick(self) -> None:
        now = time.monotonic()
        for rt in self.runtimes.values():
            if rt.state == "restarting" and rt.next_start is not None and now >= rt.next_start:
                self._spawn(rt)

    # -- public operations ------------------------------------------------
    def start_service(self, name: str) -> dict[str, Any]:
        rt = self._lookup(name)
        if not rt.spec.enabled:
            raise supervisor.ServiceError(f"{name} is disabled in services.toml")
        if rt.proc is not None:
            return rt.to_dict()
        rt.restart_times.clear()
        rt.restarts = 0
        rt.stopped_by_user = False
        self._spawn(rt)
        if rt.state != "running":
            raise supervisor.ServiceError(f"{name}: {rt.last_error or 'failed to start'}")
        return rt.to_dict()

    def stop_service(self, name: str) -> dict[str, Any]:
        rt = self._lookup(name)
        if rt.proc is None:
            rt.state = "disabled" if not rt.spec.enabled else "stopped"
            rt.next_start = None
            self._dirty = True
            return rt.to_dict()

        rt.stopped_by_user = True
        rt.state = "stopping"
        self._signal(rt, rt.spec.stop_signal)
        deadline = time.monotonic() + max(0.5, rt.spec.stop_timeout)
        while time.monotonic() < deadline and rt.proc.poll() is None:
            time.sleep(0.05)
        if rt.proc.poll() is None:
            self._signal(rt, "KILL")
            try:
                rt.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:  # pragma: no cover - very defensive
                pass
        code = rt.proc.poll()
        rt.last_exit = code
        rt.proc = None
        rt.started_at = None
        self._close_log(rt)
        rt.state = "stopped"
        rt.next_start = None
        self._dirty = True
        self._note("info", f"{name}: stopped by request (exit {code})")
        return rt.to_dict()

    def restart_service(self, name: str) -> dict[str, Any]:
        self.stop_service(name)
        time.sleep(0.05)
        return self.start_service(name)

    def _lookup(self, name: str) -> Runtime:
        try:
            return self.runtimes[name]
        except KeyError as exc:
            known = ", ".join(sorted(self.runtimes)) or "none defined"
            raise supervisor.ServiceError(f"unknown service {name!r} (known: {known})") from exc

    def status(self) -> dict[str, Any]:
        return {
            "daemon": {
                "pid": os.getpid(),
                "version": __version__,
                "uptime": round(time.time() - self.started_at, 1),
                "socket": str(self.socket_path),
                "services_file": str(self.services_path),
            },
            "services": {name: rt.to_dict() for name, rt in sorted(self.runtimes.items())},
        }

    def write_state(self) -> None:
        if not self._dirty:
            return
        payload = self.status()
        payload["written_at"] = util.now_iso()
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            util.atomic_write(self.state_path, json.dumps(payload, indent=2))
        except OSError:
            pass
        self._dirty = False

    def reload(self) -> dict[str, Any]:
        specs = supervisor.load_services(self.services_path)
        added: list[str] = []
        removed: list[str] = []
        for name in list(self.runtimes):
            if name not in specs:
                self.stop_service(name)
                del self.runtimes[name]
                removed.append(name)
        for name, spec in specs.items():
            if name in self.runtimes:
                runtime = self.runtimes[name]
                runtime.spec = spec
                if not spec.enabled:
                    self.stop_service(name)
                    runtime.state = "disabled"
            else:
                self.runtimes[name] = Runtime(
                    spec=spec, state="stopped" if spec.enabled else "disabled"
                )
                added.append(name)
        self._dirty = True
        self._note("info", f"reload: +{len(added)} -{len(removed)}")
        return {"added": added, "removed": removed, "services": sorted(self.runtimes)}

    def start_all(self) -> None:
        for name, rt in self.runtimes.items():
            if rt.spec.enabled:
                try:
                    self.start_service(name)
                except supervisor.ServiceError as exc:
                    self._note("error", f"{name}: {exc}")

    def stop_all(self) -> None:
        for name in self.runtimes:
            try:
                self.stop_service(name)
            except supervisor.ServiceError:
                continue

    # -- control socket ---------------------------------------------------
    def _dispatch(self, request: dict[str, Any]) -> Any:
        command = request.get("cmd")
        if command == "status":
            return self.status()
        if command == "ping":
            return {"pong": True, "pid": os.getpid()}
        if command in {"start", "stop", "restart"}:
            name = str(request.get("name", ""))
            if not name:
                raise supervisor.ServiceError("missing service name")
            return getattr(self, f"{command}_service")(name)
        if command == "reload":
            return self.reload()
        if command == "logs":
            name = str(request.get("name", ""))
            self._lookup(name)
            lines = int(request.get("lines", 100))
            return {"name": name, "lines": util.tail_lines(self.log_dir / f"{name}.log", lines)}
        if command == "shutdown":
            self._stop = True
            return {"stopping": True}
        raise supervisor.ServiceError(f"unknown command {command!r}")

    def _serve_connection(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(5.0)
            buffer = b""
            while b"\n" not in buffer and len(buffer) < MAX_REQUEST_BYTES:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buffer += chunk
            if not buffer.strip():
                return
            try:
                request = json.loads(buffer.decode().splitlines()[0])
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                reply = {"ok": False, "error": f"bad request: {exc}"}
            else:
                try:
                    reply = {"ok": True, "data": self._dispatch(request)}
                except supervisor.ServiceError as exc:
                    reply = {"ok": False, "error": str(exc)}
                except Exception as exc:  # pragma: no cover - last-resort guard
                    reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            conn.sendall(json.dumps(reply).encode() + b"\n")
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _bind_socket(self) -> socket.socket:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            try:
                probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                probe.settimeout(0.3)
                probe.connect(str(self.socket_path))
                probe.close()
                raise supervisor.ServiceError(
                    f"another plxd is already listening on {self.socket_path}"
                )
            except (TimeoutError, ConnectionRefusedError, FileNotFoundError, OSError):
                self.socket_path.unlink(missing_ok=True)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.socket_path))
        os.chmod(self.socket_path, 0o600)
        server.listen(16)
        server.setblocking(False)
        return server

    def serve_forever(self) -> int:
        paths.ensure_layout()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        try:
            server = self._bind_socket()
        except supervisor.ServiceError as exc:
            console.err(str(exc))
            return 1

        paths.pid_file().write_text(str(os.getpid()), encoding="utf-8")
        self._note("info", f"plxd {__version__} starting (pid {os.getpid()})")
        self.start_all()

        previous = {}
        for signame in ("SIGTERM", "SIGINT", "SIGHUP"):
            try:
                previous[signame] = signal.signal(
                    getattr(signal, signame), lambda *_: setattr(self, "_stop", True)
                )
            except (ValueError, AttributeError):  # pragma: no cover - non-main thread
                pass

        last_state_write = 0.0
        try:
            while not self._stop:
                try:
                    readable, _, _ = select.select([server], [], [], self.poll)
                except InterruptedError:  # pragma: no cover - signal race
                    readable = []
                if readable:
                    try:
                        conn, _ = server.accept()
                    except (BlockingIOError, InterruptedError):
                        conn = None
                    if conn is not None:
                        self._serve_connection(conn)
                self._reap()
                self._tick()
                if time.monotonic() - last_state_write > 1.0:
                    self.write_state()
                    last_state_write = time.monotonic()
        finally:
            self._note("info", "plxd stopping — shutting down services")
            self.stop_all()
            self._dirty = True
            self.write_state()
            server.close()
            self.socket_path.unlink(missing_ok=True)
            paths.pid_file().unlink(missing_ok=True)
            for signame, handler in previous.items():
                try:
                    signal.signal(getattr(signal, signame), handler)
                except (ValueError, AttributeError):
                    pass
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plxd", description="PocketLinux service supervisor daemon"
    )
    parser.add_argument("--services", default=None, help="services.toml path")
    parser.add_argument("--socket", default=None, help="control socket path")
    parser.add_argument("--state-file", default=None, help="state JSON path")
    parser.add_argument("--log-dir", default=None, help="log directory")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="run the daemon (foreground)")
    status = sub.add_parser("status", help="print daemon status as JSON")
    status.add_argument("--socket", default=None, help="control socket path")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command in (None, "run"):
        try:
            specs = supervisor.load_services(args.services)
        except supervisor.ServiceError as exc:
            console.err(str(exc))
            return 2
        if not specs:
            console.warn(f"no services defined in {args.services or paths.services_file()}")
        daemon = Supervisor(
            specs,
            services_path=Path(args.services) if args.services else None,
            socket_path=Path(args.socket) if args.socket else None,
            state_file=Path(args.state_file) if args.state_file else None,
            log_dir=Path(args.log_dir) if args.log_dir else None,
        )
        return daemon.serve_forever()
    if args.command == "status":
        client = supervisor.SupervisorClient(args.socket)
        try:
            console.json_out(client.status())
        except supervisor.SupervisorError as exc:
            console.err(str(exc))
            return 1
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":  # pragma: no cover - entry point
    sys.exit(main())
