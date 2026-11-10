"""Device introspection.

PocketLinux only ever touches the device it is running on, and only through
documented interfaces: ``getprop``, ``/proc``, Termux:API and normal Linux
syscalls.  There is no exploit code anywhere in this project — ``plx`` gives
you *depth* (a real root filesystem, a service tree, bind-mounted hardware
nodes), not privilege escalation.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

from . import __version__, paths, util

FAKE_PROPS_ENV = "PLX_FAKE_PROPS"

PROP_MAP = {
    "model": "ro.product.model",
    "manufacturer": "ro.product.manufacturer",
    "brand": "ro.product.brand",
    "device": "ro.product.device",
    "android": "ro.build.version.release",
    "sdk": "ro.build.version.sdk",
    "build_id": "ro.build.id",
    "fingerprint": "ro.build.fingerprint",
    "abi": "ro.product.cpu.abi",
    "selinux": "ro.build.selinux",
    "verified_boot": "ro.boot.verifiedbootstate",
    "bootloader": "ro.bootloader",
    "security_patch": "ro.build.version.security_patch",
}


def props() -> dict[str, str]:
    """Return Android system properties.

    ``PLX_FAKE_PROPS`` (JSON) is honoured so the test suite can simulate a
    Pixel, an emulator, or a non-Android host without touching a phone.
    """
    fake = os.environ.get(FAKE_PROPS_ENV)
    if fake:
        try:
            data = json.loads(fake)
        except json.JSONDecodeError:
            return {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    if not util.have("getprop"):
        return {}
    result = util.run(["getprop"], timeout=10)
    return util.parse_getprop(result.out) if result.ok else {}


def is_termux() -> bool:
    prefix = os.environ.get("PREFIX", "")
    return (
        "com.termux" in prefix
        or bool(os.environ.get("TERMUX_VERSION"))
        or Path("/data/data/com.termux/files/usr").exists()
    )


def is_android() -> bool:
    if props():
        return True
    if is_termux():
        return True
    return "android" in platform.release().lower()


def arch() -> str:
    machine = (platform.machine() or "").lower()
    mapping = {
        "aarch64": "aarch64",
        "arm64": "aarch64",
        "armv8l": "aarch64",
        "armv7l": "armv7",
        "armv6l": "armv7",
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "i686": "i686",
        "i386": "i686",
    }
    return mapping.get(machine, machine or "unknown")


def cpu_count() -> int:
    return os.cpu_count() or 1


def memory_total() -> int | None:
    info = util.meminfo()
    return info.get("MemTotal") or None


def uptime() -> float | None:
    text = util.read_text("/proc/uptime").strip()
    if not text:
        return None
    try:
        return float(text.split()[0])
    except (ValueError, IndexError):
        return None


def storage_dirs() -> list[Path]:
    """Candidate shared-storage locations that actually exist."""
    candidates = [
        Path("/sdcard"),
        Path("/storage/emulated/0"),
        Path("/storage/self/primary"),
        Path.home() / "storage" / "shared",
        Path.home() / "storage" / "downloads",
        Path.home() / "storage" / "documents",
    ]
    seen: list[Path] = []
    for candidate in candidates:
        try:
            if candidate.exists() and candidate not in seen:
                seen.append(candidate)
        except OSError:  # pragma: no cover - defensive
            continue
    return seen


def shared_storage() -> Path | None:
    """The single path that best represents shared storage, if any."""
    preferred = [
        Path.home() / "storage" / "shared",
        Path("/storage/emulated/0"),
        Path("/sdcard"),
        Path("/storage/self/primary"),
    ]
    existing = storage_dirs()
    for candidate in preferred:
        if candidate in existing:
            return candidate
    return existing[0] if existing else None


def root_present() -> bool:
    """True when a ``su`` binary is available (Termux:root-repo or Magisk)."""
    return util.have("su")


def selinux_mode() -> str:
    if util.have("getenforce"):
        result = util.run(["getenforce"], timeout=5)
        if result.ok and result.out.strip():
            return result.out.strip()
    return "unknown"


def termux_version() -> str | None:
    return os.environ.get("TERMUX_VERSION") or None


def info() -> dict[str, Any]:
    """Everything ``plx info`` shows, as a JSON-serialisable dict."""
    prop_values = props()
    data: dict[str, Any] = {
        "plx_version": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "kernel": platform.release(),
        "machine": platform.machine(),
        "arch": arch(),
        "cpus": cpu_count(),
        "memory_total": memory_total(),
        "uptime_seconds": uptime(),
        "is_android": is_android(),
        "is_termux": is_termux(),
        "termux_version": termux_version(),
        "root_present": root_present(),
        "selinux": selinux_mode(),
        "prefix": os.environ.get("PREFIX") or sys.prefix,
        "home": str(Path.home()),
        "plx_home": str(paths.home()),
        "storage": [str(path) for path in storage_dirs()],
        "shell": os.environ.get("SHELL") or "",
        "tools": {
            name: util.which(name)
            for name in ("proot", "tar", "curl", "rsync", "ssh", "sshd", "zstd", "su", "pkg")
        },
    }
    for key, prop in PROP_MAP.items():
        value = prop_values.get(prop)
        if value:
            data[key] = value
    data["android_props"] = prop_values
    return data


def summary_line() -> str:
    """One-line human description, e.g. ``Pixel 7 · Android 15 · aarch64``."""
    data = info()
    parts: list[str] = []
    model = " ".join(filter(None, [data.get("manufacturer"), data.get("model")]))
    if model:
        parts.append(model)
    elif data.get("platform"):
        parts.append(str(data["platform"]))
    if data.get("android"):
        parts.append(f"Android {data['android']}")
    parts.append(str(data.get("arch")))
    if data.get("is_termux"):
        parts.append("Termux")
    return " · ".join(parts)


def disk_free_for(path: Path | str) -> int | None:
    target = Path(path)
    while not target.exists() and target != target.parent:
        target = target.parent
    return util.disk_free(target)


def can_write(target: Path | str) -> bool:
    try:
        probe = Path(target) / f".plx-write-test-{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def find_tool(*names: str) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None
