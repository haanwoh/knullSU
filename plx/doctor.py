"""``plx doctor`` — a pre-flight check that explains *why* something is broken.

Every check is cheap (<50 ms except the network probe), side-effect free, and
carries a concrete fix command.  The same data drives the human table and the
``--json`` output used by scripts and CI.
"""

from __future__ import annotations

import socket
import sys
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from . import __version__, console, device, mounts, paths, rootfs, supervisor, util
from .config import Config
from .config import load as load_config

STATUSES = ("pass", "warn", "fail", "skip")
RANK = {"pass": 0, "skip": 1, "warn": 2, "fail": 3}
SYMBOL = {"pass": "✓", "warn": "!", "fail": "✗", "skip": "-"}
STYLE = {"pass": "green", "warn": "yellow", "fail": "red", "skip": "grey"}
SUPPORTED_ARCHES = ("aarch64", "armv7", "x86_64", "i686")
MIN_DISK = 1500 * 1024 * 1024


@dataclass(slots=True)
class Check:
    id: str
    title: str
    status: str
    detail: str = ""
    fix: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _check(id: str, title: str, status: str, detail: str = "", fix: str = "") -> Check:
    if status not in STATUSES:
        raise ValueError(f"bad status {status!r}")
    return Check(id=id, title=title, status=status, detail=detail, fix=fix)


def check_python() -> Check:
    version = sys.version_info
    detail = f"{version.major}.{version.minor}.{version.micro} ({sys.executable})"
    if version < (3, 11):
        return _check(
            "python",
            "Python runtime",
            "fail",
            detail,
            "PocketLinux needs Python 3.11+ (tomllib) — pkg install python",
        )
    return _check("python", "Python runtime", "pass", detail)


def check_host() -> Check:
    data = device.info()
    detail = device.summary_line()
    if data.get("is_termux"):
        return _check("host", "Host device", "pass", detail)
    if data.get("is_android"):
        return _check("host", "Host device", "warn", detail, "Run from Termux for full support")
    return _check(
        "host",
        "Host device",
        "warn",
        f"{detail} (not Android/Termux)",
        "PocketLinux targets Android; on Linux you can still test the CLI",
    )


def check_arch() -> Check:
    arch = device.arch()
    if arch in SUPPORTED_ARCHES:
        return _check("arch", "CPU architecture", "pass", arch)
    return _check(
        "arch",
        "CPU architecture",
        "fail",
        arch,
        f"no prebuilt image for {arch}; build a rootfs tarball and use plx install --url",
    )


def check_proot(config: Config) -> Check:
    path = util.which("proot")
    if path:
        result = util.run([path, "--version"], timeout=10)
        version = result.out.strip().splitlines()[0] if result.ok and result.out else "?"
        return _check("proot", "proot engine", "pass", f"{path} · {version}")
    if config.core.engine == "chroot":
        return _check("proot", "proot engine", "skip", "using chroot engine")
    return _check(
        "proot",
        "proot engine",
        "fail",
        "proot not found",
        "pkg install proot",
    )


def check_root() -> Check:
    path = util.which("su")
    if path:
        return _check("root", "Root / chroot engine", "pass", f"su at {path}")
    return _check(
        "root",
        "Root / chroot engine",
        "skip",
        "no su — proot engine works without root",
    )


def check_termux_api() -> Check:
    path = util.which("termux-battery-status")
    if path:
        return _check("termux-api", "Termux:API bridge", "pass", f"{path} present")
    return _check(
        "termux-api",
        "Termux:API bridge",
        "warn",
        "termux-api CLI or the Termux:API app is missing",
        "pkg install termux-api  +  install the Termux:API app",
    )


def check_storage() -> Check:
    shared = device.shared_storage()
    if shared:
        writable = device.can_write(shared)
        status = "pass" if writable else "warn"
        fix = "" if writable else "termux-setup-storage (grant storage permission)"
        return _check("storage", "Shared storage", status, str(shared), fix)
    return _check(
        "storage",
        "Shared storage",
        "warn",
        "no shared storage path visible",
        "termux-setup-storage",
    )


def check_disk(config: Config) -> Check:
    probe = config.rootfs.parent if config.rootfs.parent.exists() else paths.home()
    free = device.disk_free_for(probe)
    if free is None:
        return _check("disk", "Free space", "skip", "could not stat the filesystem")
    detail = f"{util.human_bytes(free)} free on {probe}"
    if free >= MIN_DISK:
        return _check("disk", "Free space", "pass", detail)
    if free >= MIN_DISK // 3:
        return _check(
            "disk",
            "Free space",
            "warn",
            detail,
            "Ubuntu needs ~1.5 GiB; Alpine needs ~150 MiB (plx install alpine)",
        )
    return _check("disk", "Free space", "fail", detail, "Free space before installing a rootfs")


def check_memory() -> Check:
    total = device.memory_total()
    if not total:
        return _check("memory", "Memory", "skip", "unknown")
    detail = util.human_bytes(total)
    if total >= 2 * 1024**3:
        return _check("memory", "Memory", "pass", detail)
    return _check("memory", "Memory", "warn", detail, "Heavy builds may swap; avoid -j$(nproc)")


def check_rootfs(config: Config) -> Check:
    state = rootfs.status(config)
    if not state["populated"]:
        return _check(
            "rootfs",
            "Root filesystem",
            "warn",
            f"nothing installed at {state['rootfs']}",
            f"plx install {config.core.distro}",
        )
    name = state.get("distro_name") or config.core.distro
    size = util.human_bytes(state["size"]) if state.get("size") else "?"
    detail = f"{name} · {state['rootfs']} · {size}"
    if not state["shell_present"]:
        return _check(
            "rootfs",
            "Root filesystem",
            "warn",
            detail + f" · {config.core.shell} missing",
            'plx install --force, or set core.shell = "/bin/sh"',
        )
    return _check("rootfs", "Root filesystem", "pass", detail)


def check_engine_combo(config: Config) -> Check:
    selected = config.core.engine
    if selected == "proot" and not mounts.proot_available():
        return _check(
            "engine",
            "Selected engine",
            "fail",
            "config says proot but proot is missing",
            "pkg install proot",
        )
    if selected == "chroot" and not mounts.chroot_available():
        return _check(
            "engine",
            "Selected engine",
            "fail",
            "config says chroot but no su is available",
            "plx config set core.engine proot",
        )
    return _check("engine", "Selected engine", "pass", selected)


def check_services() -> Check:
    try:
        specs = supervisor.load_services()
    except supervisor.ServiceError as exc:
        return _check("services", "Service definitions", "fail", str(exc), "plx service edit")
    enabled = [spec for spec in specs.values() if spec.enabled]
    if not specs:
        return _check(
            "services", "Service definitions", "skip", "none defined", "plx service example"
        )
    return _check("services", "Service definitions", "pass", f"{len(enabled)}/{len(specs)} enabled")


def check_daemon() -> Check:
    if supervisor.ping():
        pid = supervisor.alive_pid()
        return _check("daemon", "plxd supervisor", "pass", f"running (pid {pid})")
    return _check("daemon", "plxd supervisor", "warn", "not running", "plx service up")


def check_network() -> Check:
    started = time.monotonic()
    try:
        with socket.create_connection(("1.1.1.1", 53), timeout=2.0):
            elapsed = (time.monotonic() - started) * 1000
            return _check("network", "Network", "pass", f"TCP ok in {elapsed:.0f} ms")
    except OSError as exc:
        return _check(
            "network",
            "Network",
            "warn",
            f"no outbound TCP ({exc.__class__.__name__})",
            "check Wi-Fi/mobile data — apt/pip need it",
        )


def check_tools() -> Check:
    required = {"tar": "extract rootfs images"}
    optional = {
        "curl": "faster downloads",
        "rsync": "recipe file sync",
        "zstd": "smaller backups",
        "ssh": "remote access",
        "git": "cloning projects",
    }
    missing_required = [name for name in required if not util.which(name)]
    if missing_required:
        return _check(
            "tools",
            "Required tools",
            "fail",
            f"missing: {', '.join(missing_required)}",
            f"pkg install {' '.join(missing_required)}",
        )
    missing_optional = [name for name in optional if not util.which(name)]
    if missing_optional:
        return _check(
            "tools",
            "Optional tools",
            "warn",
            f"missing: {', '.join(missing_optional)}",
            f"pkg install {' '.join(missing_optional)}",
        )
    return _check("tools", "Optional tools", "pass", "all present")


def check_clock() -> Check:
    year = time.localtime().tm_year
    if year < 2024:
        return _check(
            "clock",
            "System clock",
            "warn",
            f"device clock says {year}",
            "wrong clocks break TLS and apt — enable automatic date & time",
        )
    return _check("clock", "System clock", "pass", time.strftime("%Y-%m-%d %H:%M %Z"))


def check_config(config: Config) -> Check:
    if config.warnings:
        return _check(
            "config",
            "Configuration",
            "warn",
            "; ".join(config.warnings[:3]),
            f"fix {paths.config_file()} or run plx config init --force",
        )
    location = config.source or paths.config_file()
    return _check("config", "Configuration", "pass", str(location))


def run(config: Config | None = None) -> list[Check]:
    """Run every check in a stable order."""
    cfg = config or load_config()
    checks = [
        check_python(),
        check_host(),
        check_arch(),
        check_engine_combo(cfg),
        check_proot(cfg),
        check_root(),
        check_termux_api(),
        check_storage(),
        check_disk(cfg),
        check_memory(),
        check_rootfs(cfg),
        check_services(),
        check_daemon(),
        check_network(),
        check_tools(),
        check_clock(),
        check_config(cfg),
    ]
    return checks


def summarize(checks: Iterable[Check]) -> dict[str, Any]:
    materialised = list(checks)
    counts = {status: 0 for status in STATUSES}
    for item in materialised:
        counts[item.status] += 1
    worst = "pass"
    for item in materialised:
        if RANK[item.status] > RANK[worst]:
            worst = item.status
    return {
        "plx_version": __version__,
        "status": worst,
        "counts": counts,
        "checks": [item.to_dict() for item in materialised],
    }


def render(checks: list[Check]) -> None:
    headers = ["", "check", "result"]
    rows = [
        [
            console.paint(SYMBOL[item.status], STYLE[item.status]),
            item.title,
            item.detail or item.status,
        ]
        for item in checks
    ]
    console.table(headers, rows)
    fixes = [item for item in checks if item.fix and item.status in ("warn", "fail")]
    if fixes:
        console.out()
        console.out(console.paint("suggested fixes", "bold"))
        for item in fixes:
            console.out(f"  {console.paint(item.title, 'cyan')}: {item.fix}")


def exit_code(summary: dict[str, Any]) -> int:
    return 1 if summary["status"] == "fail" else 0
