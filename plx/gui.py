"""Optional desktop: Termux:X11 + a real XFCE session inside the guest.

PocketLinux is a shell-first project, but a phone with a keyboard and a 6-inch
display is a legitimate terminal *and* a legitimate desktop.  This module only
orchestrates: it starts the Termux:X11 server on the host, records the PID in
``~/.plx/state/gui.json``, and hands you the exact in-guest command to launch
the desktop session.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from . import console, paths, util
from .config import Config

SERVER_BINARIES = ("termux-x11", "termux-x11-nightly")
DESKTOP_COMMANDS = {
    "xfce": "dbus-run-session -- startxfce4",
    "lxqt": "dbus-run-session -- startlxqt",
    "mate": "dbus-run-session -- mate-session",
    "fluxbox": "dbus-run-session -- fluxbox",
    "openbox": "dbus-run-session -- openbox-session",
    "xterm": "xterm",
}


def state_file() -> Path:
    return paths.state_dir() / "gui.json"


def find_server() -> str | None:
    for name in SERVER_BINARIES:
        found = util.which(name)
        if found:
            return found
    return None


def display_number(display: str) -> str:
    return display.lstrip(":").split(".")[0] or "0"


def load_state() -> dict[str, Any]:
    try:
        return json.loads(state_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(data: dict[str, Any]) -> None:
    paths.ensure_layout()
    util.atomic_write(state_file(), json.dumps(data, indent=2))


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError):
        return False
    return True


def session_command(config: Config, desktop: str | None = None) -> str:
    name = (desktop or config.gui.desktop).lower()
    command = DESKTOP_COMMANDS.get(name, DESKTOP_COMMANDS["xfce"])
    return f"DISPLAY={config.gui.display} {command}"


def status(config: Config) -> dict[str, Any]:
    state = load_state()
    server = find_server()
    pid = state.get("pid")
    return {
        "server_binary": server,
        "server_available": bool(server),
        "display": config.gui.display,
        "running": bool(state.get("running")) and _alive(pid),
        "pid": pid if _alive(pid) else None,
        "desktop": config.gui.desktop,
        "session_command": session_command(config),
        "state_file": str(state_file()),
        "install_hint": (
            None
            if server
            else "install the Termux:X11 app + `pkg install x11-repo termux-x11-nightly`"
        ),
    }


def start(config: Config, *, display: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    server = find_server()
    chosen_display = display or config.gui.display
    if not server:
        raise RuntimeError(
            "Termux:X11 server not found.\n"
            "  pkg install x11-repo\n"
            "  pkg install termux-x11-nightly\n"
            "  install the 'Termux:X11' app, then run: plx gui start"
        )
    if status(config)["running"]:
        return {**status(config), "started": False, "reason": "already running"}
    argv = [server, chosen_display]
    if dry_run:
        console.muted("[dry-run] " + " ".join(argv))
        return {"started": False, "dry_run": True, "command": argv}

    handle = subprocess.Popen(  # noqa: S603 - fixed argv
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    time.sleep(0.4)
    if handle.poll() is not None:
        raise RuntimeError(
            f"Termux:X11 exited immediately (code {handle.returncode}) — "
            "open the Termux:X11 app once, then retry"
        )
    _save_state(
        {
            "pid": handle.pid,
            "display": chosen_display,
            "running": True,
            "started": util.now_iso(),
            "binary": server,
        }
    )
    return {
        "started": True,
        "pid": handle.pid,
        "display": chosen_display,
        "session_command": session_command(config),
        "next": "plx gui session   (or: plx shell -c '" + session_command(config) + "')",
    }


def stop(config: Config, *, dry_run: bool = False) -> dict[str, Any]:
    state = load_state()
    pid = state.get("pid")
    if not _alive(pid):
        _save_state({**state, "running": False})
        return {"stopped": False, "reason": "not running"}
    if dry_run:
        console.muted(f"[dry-run] kill {pid}")
        return {"stopped": False, "dry_run": True, "pid": pid}
    try:
        os.killpg(os.getpgid(int(pid)), signal.SIGTERM)
    except (OSError, ValueError):
        try:
            os.kill(int(pid), signal.SIGTERM)
        except OSError:
            pass
    _save_state({**state, "running": False})
    return {"stopped": True, "pid": pid}


def session(config: Config, desktop: str | None = None, *, engine: str | None = None) -> int:
    """Run the desktop session in the foreground inside the guest."""
    from . import shell

    return shell.enter(config, session_command(config, desktop), engine=engine)
