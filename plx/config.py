"""Configuration loading, validation and TOML emission.

One file, ``~/.plx/config.toml``, drives every subsystem.  Unknown keys are
preserved-but-ignored with a warning instead of crashing, because a config
file written by a newer ``plx`` must never brick an older one.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from . import paths

DEFAULT_CONFIG_TEXT = """\
# PocketLinux configuration — regenerate with: plx config init --force
[core]
engine = "proot"          # proot (no root needed) | chroot (needs su/root)
distro = "ubuntu"
rootfs = ""               # empty = ~/.plx/rootfs/<distro>
workdir = "/root"
shell = "/bin/bash"
hostname = "pocketlinux"

[mounts]
storage = true            # bind ~/storage/shared -> /mnt/storage
extra = []                # ["/sdcard/Download:/root/downloads", "...:/x:ro"]

[net]
ssh_port = 8022
ssh_bind = "127.0.0.1"

[ui]
color = "auto"            # auto | always | never

[gui]
display = ":0"
desktop = "xfce"
"""

VALID_ENGINES = ("proot", "chroot")
VALID_COLORS = ("auto", "always", "never")


class ConfigError(ValueError):
    """Raised when the configuration file is structurally invalid."""


@dataclass(slots=True)
class Core:
    engine: str = "proot"
    distro: str = "ubuntu"
    rootfs: str = ""
    workdir: str = "/root"
    shell: str = "/bin/bash"
    hostname: str = "pocketlinux"

    def resolved_rootfs(self) -> Path:
        if self.rootfs:
            return Path(self.rootfs).expanduser()
        return paths.rootfs_path(self.distro)


@dataclass(slots=True)
class Mounts:
    storage: bool = True
    extra: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Net:
    ssh_port: int = 8022
    ssh_bind: str = "127.0.0.1"


@dataclass(slots=True)
class Ui:
    color: str = "auto"


@dataclass(slots=True)
class Gui:
    display: str = ":0"
    desktop: str = "xfce"


@dataclass(slots=True)
class Config:
    core: Core = field(default_factory=Core)
    mounts: Mounts = field(default_factory=Mounts)
    net: Net = field(default_factory=Net)
    ui: Ui = field(default_factory=Ui)
    gui: Gui = field(default_factory=Gui)
    warnings: list[str] = field(default_factory=list)
    source: Path | None = None

    # -- convenience -----------------------------------------------------
    @property
    def rootfs(self) -> Path:
        return self.core.resolved_rootfs()

    def exists(self) -> bool:
        return self.rootfs.exists()

    def with_overrides(self, **overrides: Any) -> Config:
        """Return a copy with ``core`` field overrides applied."""
        return replace(self, core=replace(self.core, **overrides))

    # -- serialisation ---------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "core": {
                "engine": self.core.engine,
                "distro": self.core.distro,
                "rootfs": self.core.rootfs,
                "workdir": self.core.workdir,
                "shell": self.core.shell,
                "hostname": self.core.hostname,
            },
            "mounts": {"storage": self.mounts.storage, "extra": list(self.mounts.extra)},
            "net": {"ssh_port": self.net.ssh_port, "ssh_bind": self.net.ssh_bind},
            "ui": {"color": self.ui.color},
            "gui": {"display": self.gui.display, "desktop": self.gui.desktop},
        }


def _as_bool(value: Any, key: str, warnings: list[str], default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"true", "false", "1", "0", "yes", "no"}:
        return value.lower() in {"true", "1", "yes"}
    warnings.append(f"{key}: expected a boolean, got {value!r} — using {default}")
    return default


def _as_int(value: Any, key: str, warnings: list[str], default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        warnings.append(f"{key}: expected an integer, got {value!r} — using {default}")
        return default
    if not low <= number <= high:
        warnings.append(f"{key}: {number} out of range {low}..{high} — using {default}")
        return default
    return number


def _as_str(value: Any, key: str, warnings: list[str], default: str) -> str:
    if value is None:
        return default
    if isinstance(value, (str, int, float)):
        return str(value)
    warnings.append(f"{key}: expected a string, got {type(value).__name__} — using {default!r}")
    return default


def _section(data: dict[str, Any], name: str, warnings: list[str]) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        warnings.append(f"[{name}]: expected a table — section ignored")
        return {}
    return value


def from_dict(data: dict[str, Any], *, source: Path | None = None) -> Config:
    warnings: list[str] = []
    if not isinstance(data, dict):
        raise ConfigError("config root must be a TOML table")

    core_raw = _section(data, "core", warnings)
    mounts_raw = _section(data, "mounts", warnings)
    net_raw = _section(data, "net", warnings)
    ui_raw = _section(data, "ui", warnings)
    gui_raw = _section(data, "gui", warnings)

    known = {"core", "mounts", "net", "ui", "gui"}
    for extra in sorted(set(data) - known):
        warnings.append(f"unknown section [{extra}] ignored")

    engine = _as_str(core_raw.get("engine", "proot"), "core.engine", warnings, "proot").lower()
    if engine not in VALID_ENGINES:
        warnings.append(f"core.engine={engine!r} unknown — using 'proot'")
        engine = "proot"

    color = _as_str(ui_raw.get("color", "auto"), "ui.color", warnings, "auto").lower()
    if color not in VALID_COLORS:
        warnings.append(f"ui.color={color!r} unknown — using 'auto'")
        color = "auto"

    extra_mounts: list[str] = []
    raw_mounts = mounts_raw.get("extra", [])
    if isinstance(raw_mounts, str):
        extra_mounts = [raw_mounts]
    elif isinstance(raw_mounts, list):
        extra_mounts = [str(item) for item in raw_mounts]
    else:
        warnings.append("mounts.extra: expected a list of strings — ignored")

    config = Config(
        core=Core(
            engine=engine,
            distro=_as_str(core_raw.get("distro", "ubuntu"), "core.distro", warnings, "ubuntu"),
            rootfs=_as_str(core_raw.get("rootfs", ""), "core.rootfs", warnings, ""),
            workdir=_as_str(core_raw.get("workdir", "/root"), "core.workdir", warnings, "/root"),
            shell=_as_str(core_raw.get("shell", "/bin/bash"), "core.shell", warnings, "/bin/bash"),
            hostname=_as_str(
                core_raw.get("hostname", "pocketlinux"),
                "core.hostname",
                warnings,
                "pocketlinux",
            ),
        ),
        mounts=Mounts(
            storage=_as_bool(mounts_raw.get("storage", True), "mounts.storage", warnings, True),
            extra=extra_mounts,
        ),
        net=Net(
            ssh_port=_as_int(
                net_raw.get("ssh_port", 8022), "net.ssh_port", warnings, 8022, 1, 65535
            ),
            ssh_bind=_as_str(
                net_raw.get("ssh_bind", "127.0.0.1"), "net.ssh_bind", warnings, "127.0.0.1"
            ),
        ),
        ui=Ui(color=color),
        gui=Gui(
            display=_as_str(gui_raw.get("display", ":0"), "gui.display", warnings, ":0"),
            desktop=_as_str(gui_raw.get("desktop", "xfce"), "gui.desktop", warnings, "xfce"),
        ),
        warnings=warnings,
        source=source,
    )
    return config


def load(path: Path | str | None = None) -> Config:
    """Load config from ``path`` (default ``~/.plx/config.toml``).

    A missing file is not an error — defaults are returned.  A malformed file
    raises :class:`ConfigError` with the offending line, because silently
    ignoring broken TOML is how people lose an hour of debugging.
    """
    target = Path(path).expanduser() if path else paths.config_file()
    if not target.exists():
        return Config(source=target)
    try:
        with open(target, "rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{target}: invalid TOML — {exc}") from exc
    return from_dict(data, source=target)


def save(config: Config, path: Path | str | None = None) -> Path:
    """Write ``config`` back to disk as TOML."""
    target = Path(path).expanduser() if path else paths.config_file()
    text = render_toml(config)
    paths.ensure_layout()
    tmp = target.with_name(f".{target.name}.tmp{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)
    return target


def render_toml(config: Config) -> str:
    data = config.to_dict()
    lines: list[str] = [
        "# PocketLinux configuration — regenerate with: plx config init --force",
        "",
        "[core]",
        f"engine = {_toml_value(data['core']['engine'])}",
        f"distro = {_toml_value(data['core']['distro'])}",
        f"rootfs = {_toml_value(data['core']['rootfs'])}",
        f"workdir = {_toml_value(data['core']['workdir'])}",
        f"shell = {_toml_value(data['core']['shell'])}",
        f"hostname = {_toml_value(data['core']['hostname'])}",
        "",
        "[mounts]",
        f"storage = {'true' if data['mounts']['storage'] else 'false'}",
        f"extra = [{', '.join(_toml_value(item) for item in data['mounts']['extra'])}]",
        "",
        "[net]",
        f"ssh_port = {data['net']['ssh_port']}",
        f"ssh_bind = {_toml_value(data['net']['ssh_bind'])}",
        "",
        "[ui]",
        f"color = {_toml_value(data['ui']['color'])}",
        "",
        "[gui]",
        f"display = {_toml_value(data['gui']['display'])}",
        f"desktop = {_toml_value(data['gui']['desktop'])}",
        "",
    ]
    return "\n".join(lines)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def init(path: Path | str | None = None, *, force: bool = False) -> tuple[Path, bool]:
    """Create the config file if absent. Returns ``(path, written)``."""
    target = Path(path).expanduser() if path else paths.config_file()
    if target.exists() and not force:
        return target, False
    paths.ensure_layout()
    atomic = target.with_name(f".{target.name}.tmp{os.getpid()}")
    atomic.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
    os.replace(atomic, target)
    return target, True


def set_value(config: Config, dotted: str, raw: str) -> Config:
    """Return a copy of ``config`` with ``dotted`` key set from a string."""
    section, _, key = dotted.partition(".")
    if not key:
        raise ConfigError(f"expected section.key, got {dotted!r}")

    data = config.to_dict()
    if section not in data:
        raise ConfigError(f"unknown section {section!r} (known: {', '.join(sorted(data))})")
    if key not in data[section]:
        known = ", ".join(sorted(data[section]))
        raise ConfigError(f"unknown key {section}.{key!r} (known: {known})")

    current = data[section][key]
    if isinstance(current, bool):
        value: Any = _as_bool(raw, dotted, [], current)
    elif isinstance(current, int):
        try:
            value = int(raw)
        except ValueError as exc:
            raise ConfigError(f"{dotted}: expected an integer") from exc
    elif isinstance(current, list):
        value = [item.strip() for item in raw.split(",") if item.strip()]
    else:
        value = raw

    data[section][key] = value
    updated = from_dict(data, source=config.source)
    return updated
