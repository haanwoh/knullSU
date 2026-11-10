"""Filesystem layout for PocketLinux.

Everything the tool writes lives under one home directory (``~/.plx`` by
default).  That keeps a phone install trivially auditable: one directory to
back up, one directory to delete.  ``PLX_HOME`` overrides the location and is
the seam the test suite uses so tests never touch a real home directory.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_HOME = "~/.plx"


def _env_home() -> str | None:
    value = os.environ.get("PLX_HOME", "").strip()
    return value or None


def home() -> Path:
    """Root of all PocketLinux state."""
    candidate = _env_home() or DEFAULT_HOME
    return Path(candidate).expanduser()


def config_file() -> Path:
    return home() / "config.toml"


def services_file() -> Path:
    return home() / "services.toml"


def state_dir() -> Path:
    return home() / "state"


def log_dir() -> Path:
    return home() / "logs"


def cache_dir() -> Path:
    return home() / "cache"


def rootfs_dir() -> Path:
    return home() / "rootfs"


def recipes_dir() -> Path:
    return home() / "recipes"


def backups_dir() -> Path:
    return home() / "backups"


def socket_path() -> Path:
    return state_dir() / "plxd.sock"


def pid_file() -> Path:
    return state_dir() / "plxd.pid"


def state_file() -> Path:
    return state_dir() / "plxd.json"


def daemon_log() -> Path:
    return log_dir() / "plxd.log"


def service_log(name: str) -> Path:
    return log_dir() / f"{name}.log"


def rootfs_path(distro: str) -> Path:
    return rootfs_dir() / distro


def ensure_layout() -> None:
    for directory in (
        home(),
        state_dir(),
        log_dir(),
        cache_dir(),
        rootfs_dir(),
        recipes_dir(),
        backups_dir(),
    ):
        directory.mkdir(parents=True, exist_ok=True)
    # Keys, logs and service definitions live under PLX_HOME: keep it private.
    try:
        os.chmod(home(), 0o700)
    except OSError:
        pass


def relative_to_home(path: Path) -> str:
    """Render ``~`` for paths inside the user's real home, for pretty output."""
    try:
        return "~/" + str(path.expanduser().relative_to(Path.home()))
    except (ValueError, OSError):
        return str(path)
