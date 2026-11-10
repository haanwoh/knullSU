"""Entering the guest: the ``plx shell`` engine layer.

``plx shell`` is the product's centre of gravity — everything else exists to
make this command feel like ``ssh localhost`` on a real machine.  It never
guesses: if the engine, the rootfs or ``proot`` is missing you get a precise
error and the exact command that fixes it, and ``--dry-run`` prints the whole
argv instead of running it.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from typing import Any

from . import console, device, mounts, rootfs, util
from .config import Config


class ShellError(RuntimeError):
    """Raised when a shell session cannot be constructed."""


def available_engines() -> dict[str, dict[str, Any]]:
    return {
        "proot": {
            "available": mounts.proot_available(),
            "binary": device.which("proot") if hasattr(device, "which") else util.which("proot"),
            "needs_root": False,
            "install": "pkg install proot",
        },
        "chroot": {
            "available": mounts.chroot_available(),
            "binary": util.which("su"),
            "needs_root": True,
            "install": "root the device (e.g. Magisk) or `pkg install tsu`",
        },
    }


def resolve_engine(config: Config, engine: str | None = None, *, root: bool = False) -> str:
    if engine:
        return engine.lower()
    if root:
        return "chroot"
    return config.core.engine


def build_argv(
    config: Config,
    command: str | None = None,
    *,
    engine: str | None = None,
    login: bool = True,
    root: bool = False,
) -> list[str]:
    selected = resolve_engine(config, engine, root=root)
    try:
        return mounts.engine_argv(config, command, engine=selected, login=login)
    except mounts.MountError as exc:
        raise ShellError(str(exc)) from exc


def _preflight(config: Config, selected: str) -> None:
    try:
        rootfs.ensure(config)
    except rootfs.RootfsError as exc:
        raise ShellError(str(exc)) from exc

    if selected == "proot" and not mounts.proot_available():
        raise ShellError(
            "proot is not installed — run: pkg install proot\n"
            "  (or use the chroot engine on a rooted device: plx shell --engine chroot)"
        )
    if selected == "chroot":
        if not mounts.chroot_available():
            raise ShellError(
                "the chroot engine needs root: no `su` binary found.\n"
                "  Use the default proot engine, or install root (Magisk) / Termux tsu."
            )
    if not (config.rootfs / config.core.shell.lstrip("/")).exists():
        console.warn(f"{config.core.shell} missing inside the rootfs — falling back to /bin/sh")


def enter(
    config: Config,
    command: str | None = None,
    *,
    engine: str | None = None,
    login: bool = True,
    root: bool = False,
    dry_run: bool = False,
    env: dict[str, str] | None = None,
) -> int:
    """Run a guest shell (or one command) and return its exit status."""
    selected = resolve_engine(config, engine, root=root)
    _preflight(config, selected)
    try:
        argv = build_argv(config, command, engine=selected, login=login, root=root)
    except ShellError as exc:
        console.err(str(exc))
        return 2

    if dry_run:
        console.muted("[dry-run] " + shlex.join(argv))
        return 0

    console.muted(f"→ {config.core.distro} · engine {selected} · {config.rootfs}")
    full_env = {**os.environ, **(env or {})}
    try:
        proc = subprocess.run(argv, env=full_env)
    except FileNotFoundError:
        console.err(f"{argv[0]} not found — is it installed?")
        return 127
    except KeyboardInterrupt:  # pragma: no cover - interactive
        return 130
    return proc.returncode


def capture(
    config: Config,
    command: str,
    *,
    engine: str | None = None,
    root: bool = False,
    timeout: float = 900.0,
    env: dict[str, str] | None = None,
) -> util.Result:
    """Run a command inside the guest and capture its output (no TTY)."""
    selected = resolve_engine(config, engine, root=root)
    try:
        argv = mounts.engine_argv(config, command, engine=selected, login=False)
    except mounts.MountError as exc:
        raise ShellError(str(exc)) from exc
    return util.run(argv, timeout=timeout, env=env, merge_stderr=False)


def interactive_hint(config: Config, engine: str | None = None) -> str:
    selected = resolve_engine(config, engine)
    return f"plx shell --engine {selected}"


def info(config: Config) -> dict[str, Any]:
    """Everything ``plx shell --json`` needs to describe the session."""
    selected = config.core.engine
    return {
        "engine": selected,
        "engines": available_engines(),
        "rootfs": str(config.rootfs),
        "rootfs_ready": config.rootfs.exists() and any(config.rootfs.iterdir()),
        "workdir": config.core.workdir,
        "shell": config.core.shell,
        "mounts": mounts.explain(config, engine=selected),
    }
