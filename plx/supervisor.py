"""Service definitions and the client half of the ``plxd`` supervisor.

``plxd`` is a ~300-line process supervisor purpose-built for PocketLinux.  It
exists because systemd does not exist inside a proot container and Termux has
no service manager: you still want ``sshd``, a dev server and a notebook to
come back automatically, log to disk, and be start/stop-able from one command.

Services live in ``~/.plx/services.toml``::

    [service.sshd]
    command = "/usr/sbin/sshd -D -e"
    restart = "always"
    restart_delay = 2.0

    [service.web]
    command = ["python3", "-m", "http.server", "8080"]
    dir = "/root/projects/site"
    restart = "on-failure"
    env = { PYTHONUNBUFFERED = "1" }
"""

from __future__ import annotations

import json
import shlex
import socket
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths, util

RESTART_POLICIES = ("always", "on-failure", "never")
STOP_SIGNALS = ("TERM", "INT", "HUP", "QUIT", "KILL")

DEFAULT_SERVICES_TEXT = """\
# PocketLinux service definitions — see docs/05-services.md
# [service.example]
# command = "/usr/bin/python3 -m http.server 8080"
# dir = "/root"
# restart = "on-failure"
"""


class ServiceError(ValueError):
    """Raised when a service definition is invalid."""


@dataclass(slots=True)
class ServiceSpec:
    name: str
    command: str | list[str]
    dir: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    restart: str = "on-failure"
    restart_delay: float = 2.0
    max_restarts: int = 5
    restart_window: float = 60.0
    stop_timeout: float = 10.0
    stop_signal: str = "TERM"
    enabled: bool = True
    description: str = ""

    def argv(self) -> list[str]:
        if isinstance(self.command, str):
            return shlex.split(self.command)
        return [str(part) for part in self.command]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "command": self.command,
            "dir": self.dir,
            "env": dict(self.env),
            "restart": self.restart,
            "restart_delay": self.restart_delay,
            "max_restarts": self.max_restarts,
            "restart_window": self.restart_window,
            "stop_timeout": self.stop_timeout,
            "stop_signal": self.stop_signal,
            "enabled": self.enabled,
            "description": self.description,
        }


def _coerce_spec(name: str, raw: dict[str, Any]) -> ServiceSpec:
    if not isinstance(raw, dict):
        raise ServiceError(f"service {name!r}: expected a table")
    command = raw.get("command")
    if not command:
        raise ServiceError(f"service {name!r}: missing required 'command'")
    if not isinstance(command, (str, list)):
        raise ServiceError(f"service {name!r}: 'command' must be a string or list")

    restart = str(raw.get("restart", "on-failure")).lower()
    if restart not in RESTART_POLICIES:
        raise ServiceError(
            f"service {name!r}: restart={restart!r} invalid — use {', '.join(RESTART_POLICIES)}"
        )
    stop_signal = str(raw.get("stop_signal", "TERM")).upper().removeprefix("SIG")
    if stop_signal not in STOP_SIGNALS:
        raise ServiceError(f"service {name!r}: stop_signal={stop_signal!r} invalid")

    env_raw = raw.get("env", {})
    if not isinstance(env_raw, dict):
        raise ServiceError(f"service {name!r}: 'env' must be a table of strings")

    try:
        spec = ServiceSpec(
            name=name,
            command=command,
            dir=str(raw["dir"]) if raw.get("dir") else None,
            env={str(key): str(value) for key, value in env_raw.items()},
            restart=restart,
            restart_delay=float(raw.get("restart_delay", 2.0)),
            max_restarts=int(raw.get("max_restarts", 5)),
            restart_window=float(raw.get("restart_window", 60.0)),
            stop_timeout=float(raw.get("stop_timeout", 10.0)),
            stop_signal=stop_signal,
            enabled=bool(raw.get("enabled", True)),
            description=str(raw.get("description", "")),
        )
    except (TypeError, ValueError) as exc:
        raise ServiceError(f"service {name!r}: {exc}") from exc
    if spec.restart_delay < 0:
        raise ServiceError(f"service {name!r}: restart_delay must be >= 0")
    return spec


def parse_services(data: dict[str, Any]) -> dict[str, ServiceSpec]:
    """Parse a services document. Accepts ``[service.x]`` or ``[services.x]``."""
    if not isinstance(data, dict):
        raise ServiceError("services file must be a TOML document")
    table = data.get("service", data.get("services", {}))
    if not isinstance(table, dict):
        raise ServiceError("[service] must be a table")
    specs: dict[str, ServiceSpec] = {}
    for name, raw in table.items():
        if not isinstance(name, str) or not name.strip():
            raise ServiceError("service names must be non-empty strings")
        specs[name] = _coerce_spec(name, raw)
    return specs


def load_services(path: Path | str | None = None) -> dict[str, ServiceSpec]:
    import tomllib

    target = Path(path).expanduser() if path else paths.services_file()
    if not target.exists():
        return {}
    try:
        with open(target, "rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ServiceError(f"{target}: invalid TOML — {exc}") from exc
    return parse_services(data)


def save_services(specs: dict[str, ServiceSpec], path: Path | str | None = None) -> Path:
    """Write service definitions back to TOML (used by ``plx recipe apply``)."""
    target = Path(path).expanduser() if path else paths.services_file()
    lines = ["# PocketLinux service definitions — see docs/05-services.md", ""]
    for name in sorted(specs):
        spec = specs[name]
        if spec.description:
            lines.append(f"# {spec.description}")
        lines.append(f"[service.{name}]")
        if isinstance(spec.command, list):
            rendered = ", ".join(json.dumps(str(part)) for part in spec.command)
            lines.append(f"command = [{rendered}]")
        else:
            lines.append(f"command = {json.dumps(spec.command)}")
        if spec.dir:
            lines.append(f"dir = {json.dumps(spec.dir)}")
        lines.append(f"restart = {json.dumps(spec.restart)}")
        lines.append(f"restart_delay = {spec.restart_delay}")
        lines.append(f"max_restarts = {spec.max_restarts}")
        lines.append(f"stop_timeout = {spec.stop_timeout}")
        lines.append(f"stop_signal = {json.dumps(spec.stop_signal)}")
        if not spec.enabled:
            lines.append("enabled = false")
        if spec.env:
            rendered = ", ".join(f"{k} = {json.dumps(v)}" for k, v in sorted(spec.env.items()))
            lines.append(f"env = {{ {rendered} }}")
        lines.append("")
    paths.ensure_layout()
    util.atomic_write(target, "\n".join(lines))
    return target


class SupervisorError(RuntimeError):
    """Raised when the daemon is unreachable or returns an error."""


class SupervisorClient:
    """Line-delimited JSON client for ``plxd``."""

    def __init__(self, socket_path: Path | str | None = None, timeout: float = 5.0) -> None:
        self.socket_path = Path(socket_path) if socket_path else paths.socket_path()
        self.timeout = timeout

    # -- transport -------------------------------------------------------
    def request(self, command: str, **payload: Any) -> Any:
        message = json.dumps({"cmd": command, **payload}).encode() + b"\n"
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                sock.connect(str(self.socket_path))
                sock.sendall(message)
                buffer = b""
                while not buffer.endswith(b"\n"):
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    buffer += chunk
        except FileNotFoundError as exc:
            raise SupervisorError(
                "plxd is not running (no socket). Start it with: plx service up"
            ) from exc
        except (TimeoutError, ConnectionRefusedError, OSError) as exc:
            raise SupervisorError(f"cannot talk to plxd: {exc}") from exc

        if not buffer.strip():
            raise SupervisorError("plxd closed the connection without a reply")
        try:
            reply = json.loads(buffer.decode())
        except json.JSONDecodeError as exc:
            raise SupervisorError(f"plxd sent invalid JSON: {exc}") from exc
        if not reply.get("ok"):
            raise SupervisorError(reply.get("error", "unknown supervisor error"))
        return reply.get("data")

    # -- commands --------------------------------------------------------
    def status(self) -> dict[str, Any]:
        return self.request("status")

    def start(self, name: str) -> dict[str, Any]:
        return self.request("start", name=name)

    def stop(self, name: str) -> dict[str, Any]:
        return self.request("stop", name=name)

    def restart(self, name: str) -> dict[str, Any]:
        return self.request("restart", name=name)

    def reload(self) -> dict[str, Any]:
        return self.request("reload")

    def shutdown(self) -> dict[str, Any]:
        return self.request("shutdown")

    def logs(self, name: str, lines: int = 100) -> list[str]:
        return util.tail_lines(paths.service_log(name), lines)


def ping(socket_path: Path | str | None = None, timeout: float = 1.5) -> bool:
    """True when a supervisor answers on the socket."""
    try:
        SupervisorClient(socket_path, timeout=timeout).status()
        return True
    except SupervisorError:
        return False


def alive_pid(socket_path: Path | str | None = None) -> int | None:
    pid_path = paths.pid_file()
    if socket_path:
        pid_path = Path(socket_path).parent / "plxd.pid"
    try:
        pid = int(pid_path.read_text().strip())
    except (OSError, ValueError):
        return None
    try:
        import os

        os.kill(pid, 0)
    except OSError:
        return None
    return pid


def wait_for_socket(socket_path: Path | str | None = None, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ping(socket_path, timeout=0.5):
            return True
        time.sleep(0.1)
    return False


def format_status_table(data: dict[str, Any]) -> tuple[list[str], list[list[str]]]:
    headers = ["service", "state", "pid", "restarts", "uptime", "command"]
    rows: list[list[str]] = []
    for name, info in sorted((data.get("services") or {}).items()):
        rows.append(
            [
                name,
                str(info.get("state", "?")),
                str(info.get("pid") or "-"),
                str(info.get("restarts", 0)),
                util.human_duration(info.get("uptime")) if info.get("uptime") else "-",
                str(info.get("command", ""))[:40],
            ]
        )
    return headers, rows


def describe_specs(specs: Sequence[ServiceSpec]) -> list[list[str]]:
    rows = []
    for spec in specs:
        rows.append(
            [
                spec.name,
                "yes" if spec.enabled else "no",
                spec.restart,
                " ".join(spec.argv())[:44],
            ]
        )
    return rows
