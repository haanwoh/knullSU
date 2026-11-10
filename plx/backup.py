"""Whole-rootfs snapshots.

A phone is a hostile environment for long-lived state: one ``pkg upgrade``, one
bad ``apt full-upgrade`` in the guest, or a full disk and your rootfs is toast.
``plx backup`` is the undo button — a tar of the guest (minus ``/proc``,
``/sys``, ``/dev``, ``/tmp``, ``/run``) plus a JSON manifest with a SHA-256, so
a restore can never silently install a truncated archive.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from . import __version__, console, device, paths, rootfs, util
from .config import Config

EXCLUDES = ("./proc", "./sys", "./dev", "./tmp", "./run", "./var/log")
COMPRESSORS = {
    "zstd": ["--use-compress-program=zstd", "-cf"],
    "gzip": ["-czf"],
    "none": ["-cf"],
}
SUFFIX = {"zstd": ".tar.zst", "gzip": ".tar.gz", "none": ".tar"}


class BackupError(RuntimeError):
    """Raised when a snapshot cannot be created, verified or restored."""


def resolve_compressor(preference: str = "auto") -> str:
    if preference in COMPRESSORS:
        return preference
    if preference != "auto":
        raise BackupError(f"unknown compressor {preference!r} (auto|zstd|gzip|none)")
    return "zstd" if util.have("zstd") else "gzip"


def timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def archive_path(
    config: Config,
    dest: str | Path | None = None,
    label: str | None = None,
    compressor: str = "auto",
) -> Path:
    directory = Path(dest).expanduser() if dest else paths.backups_dir()
    clean_label = f"-{label}" if label else ""
    name = f"plx-{config.core.distro}{clean_label}-{timestamp()}{SUFFIX[resolve_compressor(compressor)]}"
    return directory / name


def _tar_argv(root: Path, archive: Path, compressor: str) -> list[str]:
    flags = COMPRESSORS[compressor]
    argv = ["tar", *flags, str(archive), "-C", str(root)]
    argv += [f"--exclude={item}" for item in EXCLUDES]
    argv.append(".")
    return argv


def create(
    config: Config,
    *,
    dest: str | Path | None = None,
    label: str | None = None,
    compress: str = "auto",
    dry_run: bool = False,
    skip_verify: bool = False,
) -> dict[str, Any]:
    """Snapshot the configured rootfs and write a manifest beside it."""
    root = rootfs.ensure(config)
    compressor = resolve_compressor(compress)
    archive = archive_path(config, dest, label, compressor)
    archive.parent.mkdir(parents=True, exist_ok=True)
    argv = _tar_argv(root, archive, compressor)

    if dry_run:
        console.muted("[dry-run] " + " ".join(argv))
        return {"archive": str(archive), "dry_run": True, "command": argv}

    started = time.monotonic()
    console.step(f"snapshotting {root.name} → {archive.name}")
    result = util.run(argv, timeout=7200)
    if not result.ok:
        archive.unlink(missing_ok=True)
        raise BackupError(f"tar failed: {result.err.strip() or result.code}")
    size = archive.stat().st_size
    manifest: dict[str, Any] = {
        "archive": archive.name,
        "created": util.now_iso(),
        "plx_version": __version__,
        "distro": config.core.distro,
        "engine": config.core.engine,
        "host_model": device.info().get("model", "unknown"),
        "compressor": compressor,
        "size": size,
        "bytes": size,
        "excludes": list(EXCLUDES),
        "command": argv,
        "sha256": None if skip_verify else util.sha256_file(archive),
        "duration": round(time.monotonic() - started, 1),
    }
    util.atomic_write(archive.with_suffix(archive.suffix + ".json"), util.json_dumps(manifest))
    console.ok(f"wrote {archive} ({util.human_bytes(size)})")
    manifest["archive"] = str(archive)
    return manifest


def list_backups(directory: str | Path | None = None) -> list[dict[str, Any]]:
    folder = Path(directory).expanduser() if directory else paths.backups_dir()
    if not folder.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    for path in sorted(folder.iterdir()):
        if not path.is_file():
            continue
        if not any(path.name.endswith(suffix) for suffix in SUFFIX.values()):
            continue
        manifest_path = path.with_suffix(path.suffix + ".json")
        data: dict[str, Any] = {}
        if manifest_path.exists():
            try:
                import json

                data = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
        entries.append(
            {
                "archive": str(path),
                "name": path.name,
                "size": path.stat().st_size,
                "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime)),
                "distro": data.get("distro", "?"),
                "verified": bool(data.get("sha256")),
                "manifest": bool(data),
            }
        )
    entries.sort(key=lambda item: item["modified"], reverse=True)
    return entries


def verify(archive: Path | str) -> dict[str, Any]:
    """Check an archive against its manifest hash."""
    path = Path(archive).expanduser()
    if not path.exists():
        raise BackupError(f"{path} does not exist")
    manifest_path = path.with_suffix(path.suffix + ".json")
    if not manifest_path.exists():
        return {"archive": str(path), "verified": False, "reason": "no manifest"}
    import json

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackupError(f"manifest unreadable: {exc}") from exc
    expected = manifest.get("sha256")
    if not expected:
        return {"archive": str(path), "verified": False, "reason": "manifest has no sha256"}
    actual = util.sha256_file(path)
    return {
        "archive": str(path),
        "verified": actual == expected,
        "expected": expected,
        "actual": actual,
    }


def restore(
    archive: Path | str,
    config: Config,
    *,
    confirm: bool = False,
    dry_run: bool = False,
    skip_verify: bool = False,
) -> dict[str, Any]:
    """Replace the configured rootfs with ``archive`` (keeps an aside copy)."""
    path = Path(archive).expanduser()
    if not path.exists():
        raise BackupError(f"{path} does not exist")
    if not confirm:
        raise BackupError(
            f"restoring replaces {config.rootfs} — re-run with --yes once you are sure"
        )

    verification = {"verified": False, "reason": "skipped"}
    if not skip_verify:
        verification = verify(path)

    if dry_run:
        console.muted(f"[dry-run] extract {path} into {config.rootfs}")
        return {"restored": False, "archive": str(path), "dry_run": True, **verification}

    target = config.rootfs
    staging = target.with_name(target.name + ".restore-tmp")
    if staging.exists():
        import shutil

        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    result = util.run(
        ["tar", "-xf", str(path), "-C", str(staging), "--no-same-owner"], timeout=7200
    )
    if not result.ok:
        raise BackupError(f"extraction failed: {result.err.strip() or result.code}")

    aside = None
    if target.exists():
        aside = target.with_name(f"{target.name}.pre-restore-{timestamp()}")
        target.rename(aside)
    staging.rename(target)
    return {
        "restored": True,
        "archive": str(path),
        "rootfs": str(target),
        "aside": str(aside) if aside else None,
        **verification,
    }


def prune(
    keep: int = 5, directory: str | Path | None = None, *, dry_run: bool = False
) -> dict[str, Any]:
    """Delete all but the ``keep`` newest snapshots."""
    entries = list_backups(directory)
    victims = entries[keep:]
    removed: list[str] = []
    for entry in victims:
        path = Path(entry["archive"])
        if dry_run:
            console.muted(f"[dry-run] rm {path}")
            continue
        path.unlink(missing_ok=True)
        path.with_suffix(path.suffix + ".json").unlink(missing_ok=True)
        removed.append(str(path))
    return {"kept": [entry["archive"] for entry in entries[:keep]], "removed": removed}
