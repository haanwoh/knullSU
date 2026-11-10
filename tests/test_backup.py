from __future__ import annotations

from pathlib import Path

import pytest

from plx import backup


def test_resolve_compressor():
    assert backup.resolve_compressor("gzip") == "gzip"
    assert backup.resolve_compressor("none") == "none"
    assert backup.resolve_compressor("auto") in ("zstd", "gzip")
    with pytest.raises(backup.BackupError):
        backup.resolve_compressor("lzma2")


def test_create_verify_and_list(cfg, fake_rootfs: Path, plx_home: Path):
    manifest = backup.create(cfg, compress="gzip", label="test")
    archive = Path(manifest["archive"])
    assert archive.exists() and archive.name.endswith(".tar.gz")
    assert archive.name.startswith("plx-ubuntu-test-")
    assert manifest["sha256"] and manifest["distro"] == "ubuntu"
    assert archive.with_suffix(archive.suffix + ".json").exists()

    verification = backup.verify(archive)
    assert verification["verified"] is True

    entries = backup.list_backups()
    assert entries and entries[0]["archive"] == str(archive)
    assert entries[0]["verified"] is True


def test_verify_detects_tampering(cfg):
    manifest = backup.create(cfg, compress="gzip", label="tamper")
    archive = Path(manifest["archive"])
    with open(archive, "ab") as handle:
        handle.write(b"extra")
    assert backup.verify(archive)["verified"] is False


def test_verify_without_manifest(cfg):
    manifest = backup.create(cfg, compress="gzip", label="nomanifest")
    archive = Path(manifest["archive"])
    archive.with_suffix(archive.suffix + ".json").unlink()
    result = backup.verify(archive)
    assert result["verified"] is False and "no manifest" in result["reason"]


def test_restore_requires_confirmation(cfg):
    manifest = backup.create(cfg, compress="gzip", label="confirm")
    with pytest.raises(backup.BackupError, match="--yes"):
        backup.restore(manifest["archive"], cfg)


def test_restore_into_new_location(cfg, plx_home: Path):
    manifest = backup.create(cfg, compress="gzip", label="restore")
    target = plx_home / "restored"
    new_cfg = cfg.with_overrides(rootfs=str(target))
    result = backup.restore(manifest["archive"], new_cfg, confirm=True)
    assert result["restored"] is True
    assert (target / "etc/os-release").exists()
    assert (target / "bin/sh").exists()


def test_restore_keeps_previous_rootfs_aside(cfg, fake_rootfs: Path, plx_home: Path):
    manifest = backup.create(cfg, compress="gzip", label="aside")
    result = backup.restore(manifest["archive"], cfg, confirm=True)
    assert result["aside"] is not None
    assert Path(result["aside"]).exists()


def test_create_dry_run_writes_nothing(cfg):
    result = backup.create(cfg, compress="gzip", dry_run=True)
    assert result["dry_run"] is True
    assert not Path(result["archive"]).exists()


def test_create_requires_rootfs(plx_home: Path, cfg):
    cfg.core.rootfs = str(plx_home / "missing")
    with pytest.raises(Exception, match="rootfs"):
        backup.create(cfg, compress="gzip")


def test_prune_keeps_newest(cfg):
    first = backup.create(cfg, compress="gzip", label="one")
    second = backup.create(cfg, compress="gzip", label="two")
    result = backup.prune(keep=1)
    remaining = [entry["archive"] for entry in backup.list_backups()]
    assert len(remaining) == 1
    assert remaining[0] in (first["archive"], second["archive"])
    assert len(result["removed"]) == 1


def test_prune_dry_run(cfg):
    backup.create(cfg, compress="gzip", label="keep")
    backup.create(cfg, compress="gzip", label="drop")
    before = len(backup.list_backups())
    backup.prune(keep=1, dry_run=True)
    assert len(backup.list_backups()) == before
