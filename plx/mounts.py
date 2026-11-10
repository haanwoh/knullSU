"""Bind-mount planning and shell-engine command construction.

Two engines are supported:

``proot``
    No root required.  ``proot`` intercepts syscalls and fakes ``uid 0``, which
    is what makes a Debian/Ubuntu userland usable on a stock phone.  Bind
    mounts are emulated by proot itself.

``chroot``
    Needs ``su``/root.  Bind mounts are real kernel mounts performed in a
    throw-away mount namespace (``unshare -m``), so the host sees nothing
    afterwards and a crash can never leave a half-mounted rootfs behind.

Every command this module builds can be inspected first with
``plx shell --dry-run`` or ``plx mount show`` — nothing is executed silently.
"""

from __future__ import annotations

import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from . import device
from .config import Config


class MountError(RuntimeError):
    """Raised when a bind spec or the selected engine is unusable."""


@dataclass(slots=True, frozen=True)
class Bind:
    src: str
    dst: str
    ro: bool = False
    optional: bool = False

    def exists(self) -> bool:
        return Path(self.src).exists()

    def proot_arg(self) -> str:
        return f"{self.src}:{self.dst}" if self.src != self.dst else self.src

    def __str__(self) -> str:
        flags = " (ro)" if self.ro else ""
        return f"{self.src} -> {self.dst}{flags}"


def parse_bind(spec: str) -> Bind:
    """Parse ``src:dst[:ro]`` (``dst`` optional, ``ro`` suffix optional)."""
    if not spec or not spec.strip():
        raise MountError("empty bind spec")
    parts = spec.strip().split(":")
    if len(parts) == 1:
        return Bind(parts[0], parts[0])
    if len(parts) == 2:
        if parts[1] == "ro":
            return Bind(parts[0], parts[0], ro=True)
        return Bind(parts[0], parts[1])
    if len(parts) == 3 and parts[2] == "ro":
        return Bind(parts[0], parts[1], ro=True)
    raise MountError(f"unsupported bind spec {spec!r} — use src:dst or src:dst:ro")


def default_binds(config: Config) -> list[Bind]:
    """The bind set every shell session starts from."""
    binds: list[Bind] = [
        Bind("/dev", "/dev"),
        Bind("/proc", "/proc"),
        Bind("/sys", "/sys"),
    ]
    if config.mounts.storage:
        shared = device.shared_storage()
        if shared is not None:
            binds.append(Bind(str(shared), "/mnt/storage", optional=True))
    for spec in config.mounts.extra:
        bind = parse_bind(spec)
        binds.append(Bind(bind.src, bind.dst, ro=bind.ro, optional=True))
    return binds


def usable_binds(binds: Sequence[Bind]) -> tuple[list[Bind], list[Bind]]:
    """Split binds into ``(present, skipped)`` based on the source existing."""
    present = [bind for bind in binds if bind.exists()]
    skipped = [bind for bind in binds if not bind.exists()]
    return present, skipped


def proot_available() -> bool:
    return device.find_tool("proot") is not None


def chroot_available() -> bool:
    return device.root_present()


def engine_available(engine: str) -> bool:
    return proot_available() if engine == "proot" else chroot_available()


def proot_argv(
    config: Config,
    command: str | None = None,
    *,
    bind_list: Sequence[Bind] | None = None,
    login: bool = True,
    extra_env: dict[str, str] | None = None,
) -> list[str]:
    """Build the full ``proot`` argv for a rootfs shell or one-off command."""
    rootfs = config.rootfs
    if not rootfs.exists():
        raise MountError(f"rootfs missing at {rootfs} — run: plx install {config.core.distro}")
    binds = list(bind_list if bind_list is not None else default_binds(config))
    present, _ = usable_binds(binds)

    argv: list[str] = [
        "proot",
        "-0",
        "--link2symlink",
        "--kill-on-exit",
        "-r",
        str(rootfs),
        "-w",
        config.core.workdir,
    ]
    for bind in present:
        argv += ["-b", bind.proot_arg()]

    env = {
        "HOME": config.core.workdir,
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "TERM": "xterm-256color",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "HOSTNAME": config.core.hostname,
        "PLX_HOST": "1",
    }
    env.update(extra_env or {})

    argv += ["/usr/bin/env", "-i"]
    argv += [f"{key}={value}" for key, value in env.items()]
    shell = (
        config.core.shell if Path(rootfs / config.core.shell.lstrip("/")).exists() else "/bin/sh"
    )
    if command:
        argv += [shell, "-lc", command]
    elif login:
        argv += [shell, "-l"]
    else:
        argv += [shell, "-i"]
    return argv


def chroot_script(
    config: Config,
    command: str | None = None,
    *,
    bind_list: Sequence[Bind] | None = None,
) -> str:
    """Build a POSIX shell script that bind-mounts, chroots and cleans up.

    The script is meant to be run through ``su -c``.  It mounts inside a
    private mount namespace, so ``exit`` (or even a lost shell) cannot leave
    the host with stray mounts.
    """
    rootfs = config.rootfs
    if not rootfs.exists():
        raise MountError(f"rootfs missing at {rootfs} — run: plx install {config.core.distro}")
    binds = list(bind_list if bind_list is not None else default_binds(config))
    present, _ = usable_binds(binds)

    lines = [
        "set -eu",
        f"R={shlex.quote(str(rootfs))}",
        "export PATH=/system/bin:/system/xbin:/usr/bin:/bin:$PATH",
        "unshare -m --propagation private /bin/sh -s <<'PLX_EOF'",
        f"R={shlex.quote(str(rootfs))}",
        "set -eu",
    ]
    for bind in present:
        target = f"$R{bind.dst}"
        lines.append(f"mkdir -p {shlex.quote(target)}")
        if bind.ro:
            lines.append(f"mount -o bind {shlex.quote(bind.src)} {shlex.quote(target)}")
            lines.append(f"mount -o remount,bind,ro {shlex.quote(target)}")
        else:
            lines.append(f"mount -o bind {shlex.quote(bind.src)} {shlex.quote(target)}")
    if command:
        lines.append(
            f"chroot {shlex.quote(str(rootfs))} {config.core.shell} -lc {shlex.quote(command)}"
        )
    else:
        lines.append(f"exec chroot {shlex.quote(str(rootfs))} {config.core.shell} -l")
    lines += ["PLX_EOF", ""]
    return "\n".join(lines)


def chroot_argv(
    config: Config,
    command: str | None = None,
    *,
    bind_list: Sequence[Bind] | None = None,
) -> list[str]:
    script = chroot_script(config, command, bind_list=bind_list)
    return ["su", "-c", script]


def engine_argv(
    config: Config,
    command: str | None = None,
    *,
    engine: str | None = None,
    login: bool = True,
    bind_list: Sequence[Bind] | None = None,
) -> list[str]:
    """Pick the engine from config/argument and return the argv to run."""
    selected = (engine or config.core.engine).lower()
    if selected == "proot":
        return proot_argv(config, command, bind_list=bind_list, login=login)
    if selected == "chroot":
        return chroot_argv(config, command, bind_list=bind_list)
    raise MountError(f"unknown engine {selected!r} — expected proot or chroot")


def explain(config: Config, *, engine: str | None = None) -> dict[str, object]:
    """Machine-readable description of the planned session (for --json)."""
    selected = (engine or config.core.engine).lower()
    binds = default_binds(config)
    present, skipped = usable_binds(binds)
    return {
        "engine": selected,
        "engine_available": engine_available(selected),
        "rootfs": str(config.rootfs),
        "rootfs_exists": config.rootfs.exists(),
        "workdir": config.core.workdir,
        "shell": config.core.shell,
        "binds": [{"src": bind.src, "dst": bind.dst, "ro": bind.ro} for bind in present],
        "skipped_binds": [str(bind) for bind in skipped],
    }
