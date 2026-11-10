"""Small, dependency-free helpers shared by every subsystem.

Nothing here touches PocketLinux state directly — these are the primitives
(process execution, parsing, formatting, safe file writes) that the rest of
the package is built from, which also makes them easy to unit-test.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CHUNK = 1024 * 1024


class CommandError(RuntimeError):
    """Raised by :func:`run` when ``check=True`` and the command fails."""

    def __init__(self, result: Result) -> None:
        self.result = result
        super().__init__(result.summary())


@dataclass(slots=True)
class Result:
    """Outcome of a subprocess call."""

    cmd: Sequence[str]
    code: int
    out: str = ""
    err: str = ""
    duration: float = 0.0

    @property
    def ok(self) -> bool:
        return self.code == 0

    def summary(self) -> str:
        rendered = " ".join(shlex.quote(part) for part in self.cmd)
        head = self.out.strip().splitlines()[:3]
        detail = " | ".join(head) if head else self.err.strip().splitlines()[:3]
        tail = f" — {detail}" if detail else ""
        return f"command failed (exit {self.code}): {rendered}{tail}"


def which(name: str) -> str | None:
    return shutil.which(name)


def have(name: str) -> bool:
    return which(name) is not None


def run(
    cmd: str | Sequence[str],
    *,
    check: bool = False,
    timeout: float | None = None,
    env: Mapping[str, str] | None = None,
    cwd: str | Path | None = None,
    input_text: str | None = None,
    merge_stderr: bool = False,
) -> Result:
    """Run a command without a shell and capture its output.

    A string command is split with :func:`shlex.split`; use :func:`run_shell`
    when shell features (pipes, redirects, ``&&``) are required.
    """
    argv = shlex.split(cmd) if isinstance(cmd, str) else [str(part) for part in cmd]
    if not argv:
        return Result(argv, 0, "", "")

    full_env = {**os.environ, **(env or {})}
    stderr = subprocess.STDOUT if merge_stderr else subprocess.PIPE
    started = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            input=input_text,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            errors="replace",
            timeout=timeout,
            env=full_env,
            cwd=str(cwd) if cwd else None,
        )
        result = Result(argv, proc.returncode, proc.stdout or "", proc.stderr or "")
    except FileNotFoundError:
        result = Result(argv, 127, "", f"{argv[0]}: command not found")
    except PermissionError:
        result = Result(argv, 126, "", f"{argv[0]}: permission denied")
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout if isinstance(exc.stdout, str) else ""
        result = Result(argv, 124, out or "", f"timed out after {timeout}s")
    result.duration = time.monotonic() - started
    if check and not result.ok:
        raise CommandError(result)
    return result


def run_shell(
    script: str,
    *,
    check: bool = False,
    timeout: float | None = None,
    env: Mapping[str, str] | None = None,
    cwd: str | Path | None = None,
) -> Result:
    """Run a shell snippet with ``bash`` when available, else ``sh``."""
    shell = which("bash") or "/bin/sh"
    argv = [shell, "-c", script]
    started = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            env={**os.environ, **(env or {})},
            cwd=str(cwd) if cwd else None,
        )
        result = Result(argv, proc.returncode, proc.stdout or "", proc.stderr or "")
    except subprocess.TimeoutExpired:
        result = Result(argv, 124, "", f"timed out after {timeout}s")
    result.duration = time.monotonic() - started
    if check and not result.ok:
        raise CommandError(result)
    return result


def human_bytes(count: float | int | None) -> str:
    if count is None:
        return "?"
    value = float(count)
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    for unit in units:
        if abs(value) < 1024 or unit == units[-1]:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PiB"


def human_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "?"
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m {total % 60}s"
    if total < 86400:
        return f"{total // 3600}h {(total % 3600) // 60}m"
    return f"{total // 86400}d {(total % 86400) // 3600}h"


def atomic_write(path: Path | str, text: str, *, mode: int | None = None) -> Path:
    """Write ``text`` to ``path`` atomically (temp file + rename)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    if mode is not None:
        os.chmod(tmp, mode)
    os.replace(tmp, target)
    return target


def read_text(path: Path | str, default: str = "") -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return default


def ensure_dir(path: Path | str) -> Path:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(CHUNK)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def parse_getprop(text: str) -> dict[str, str]:
    """Parse ``getprop`` output (``[key]: [value]``)."""
    props: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("[") or "]" not in line:
            continue
        try:
            key, _, rest = line[1:].partition("]: [")
            value = rest[:-1] if rest.endswith("]") else rest
        except ValueError:  # pragma: no cover - defensive
            continue
        if key:
            props[key.strip()] = value.strip()
    return props


def parse_kv(text: str) -> dict[str, str]:
    """Parse ``key: value`` or ``key=value`` lines into a dict."""
    data: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for sep in (":", "="):
            if sep in line:
                key, _, value = line.partition(sep)
                data[key.strip()] = value.strip()
                break
    return data


def tail_lines(path: Path | str, count: int = 100) -> list[str]:
    """Return the last ``count`` lines of a file, cheaply for large logs."""
    target = Path(path)
    try:
        with open(target, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            block = min(size, max(8192, count * 256))
            handle.seek(size - block)
            data = handle.read().decode("utf-8", errors="replace")
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return []
    lines = data.splitlines()
    return lines[-count:]


def disk_free(path: Path | str) -> int | None:
    try:
        return shutil.disk_usage(str(path)).free
    except OSError:
        return None


def disk_total(path: Path | str) -> int | None:
    try:
        return shutil.disk_usage(str(path)).total
    except OSError:
        return None


def meminfo() -> dict[str, int]:
    """Parse ``/proc/meminfo`` (kB values converted to bytes)."""
    data: dict[str, int] = {}
    for line in read_text("/proc/meminfo").splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            data[key.strip()] = int(parts[0]) * 1024
    return data


def json_dumps(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True, default=str)


def flatten(items: Iterable[Iterable[Any]]) -> list[Any]:
    return [item for group in items for item in group]


def unique(items: Iterable[Any]) -> list[Any]:
    seen: set[Any] = set()
    out: list[Any] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
