from __future__ import annotations

import os
from pathlib import Path

import pytest

from plx import config as config_mod
from plx import rootfs


def test_image_registry_is_arch_aware():
    assert "ubuntu" in rootfs.IMAGES and "alpine" in rootfs.IMAGES
    assert rootfs.image_url("ubuntu", "aarch64").endswith("arm64.tar.gz")
    assert "alpine" in rootfs.image_url("alpine", "x86_64")
    assert rootfs.image_url("debian", "aarch64") is None
    assert rootfs.image_url("nonsense", "aarch64") is None
    assert set(rootfs.supported_arches("alpine")) >= {"aarch64", "x86_64"}


def test_distros_union():
    listed = rootfs.distros()
    assert listed == sorted(listed)
    assert "ubuntu" in listed and "debian" in listed


def test_status_reports_missing_rootfs(tmp_path: Path):
    cfg = config_mod.Config().with_overrides(rootfs=str(tmp_path / "nothing"))
    state = rootfs.status(cfg)
    assert state["exists"] is False
    assert state["populated"] is False


def test_status_reads_release_file(fake_rootfs: Path, cfg):
    state = rootfs.status(cfg)
    assert state["exists"] is True and state["populated"] is True
    assert "Ubuntu" in state["distro_name"]
    assert state["shell_present"] is True


def test_post_configure_writes_expected_files(fake_rootfs: Path, cfg):
    written = rootfs.post_configure(cfg, "ubuntu", fake_rootfs)
    assert "etc/resolv.conf" in written
    assert "etc/apt/apt.conf.d/99-plx-sandbox" in written
    assert (fake_rootfs / "etc/plx-release").exists()
    assert (fake_rootfs / "mnt/storage").is_dir()
    mode = os.stat(fake_rootfs / "root/.ssh").st_mode & 0o777
    assert mode == 0o700
    assert "nameserver 1.1.1.1" in (fake_rootfs / "etc/resolv.conf").read_text()


def test_post_configure_skips_apt_for_alpine(fake_rootfs: Path, cfg):
    import shutil

    shutil.rmtree(fake_rootfs / "etc/apt")
    written = rootfs.post_configure(cfg, "alpine", fake_rootfs)
    assert not any("apt" in item for item in written)


def test_ensure_raises_with_hint(tmp_path: Path):
    cfg = config_mod.Config().with_overrides(rootfs=str(tmp_path / "empty"))
    with pytest.raises(rootfs.RootfsError, match="plx install"):
        rootfs.ensure(cfg)


def test_ensure_returns_existing(fake_rootfs: Path, cfg):
    assert rootfs.ensure(cfg) == fake_rootfs


def test_dry_run_install_creates_nothing(tmp_path: Path, plx_home: Path):
    cfg = config_mod.Config().with_overrides(
        distro="alpine", rootfs=str(plx_home / "rootfs" / "alpine")
    )
    summary = rootfs.install(cfg, arch="x86_64", dry_run=True)
    assert summary["dry_run"] is True
    assert not Path(summary["rootfs"]).exists()


def test_install_refuses_to_clobber(fake_rootfs: Path, cfg):
    with pytest.raises(rootfs.RootfsError, match="already exists"):
        rootfs.install(cfg, distro="ubuntu")


def test_install_unknown_distro(plx_home: Path, cfg):
    with pytest.raises(rootfs.RootfsError, match="unknown distribution|no built-in image"):
        rootfs.install(cfg, distro="beos", dest=plx_home / "x")


def test_remove_requires_confirmation(fake_rootfs: Path, cfg):
    with pytest.raises(rootfs.RootfsError, match="--yes"):
        rootfs.remove(cfg)


def test_remove_refuses_unsafe_paths(tmp_path: Path):
    cfg = config_mod.Config().with_overrides(rootfs=str(Path.home()))
    with pytest.raises(rootfs.RootfsError, match="unsafe"):
        rootfs.remove(cfg, confirm=True)


def test_remove_deletes_rootfs(fake_rootfs: Path, cfg):
    result = rootfs.remove(cfg, confirm=True)
    assert result["removed"] is True
    assert not fake_rootfs.exists()


def test_remove_dry_run_keeps_files(fake_rootfs: Path, cfg):
    result = rootfs.remove(cfg, confirm=True, dry_run=True)
    assert result["dry_run"] is True
    assert fake_rootfs.exists()


def test_extract_rejects_non_rootfs(tmp_path: Path, plx_home: Path):
    src = tmp_path / "junk"
    src.mkdir()
    (src / "hello.txt").write_text("hi")
    archive = tmp_path / "junk.tar"
    import subprocess

    subprocess.run(["tar", "-cf", str(archive), "-C", str(src), "."], check=True)
    with pytest.raises(rootfs.RootfsError, match="does not look like"):
        rootfs.extract(archive, plx_home / "dest")
