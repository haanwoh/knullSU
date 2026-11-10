from __future__ import annotations

from pathlib import Path

import pytest

from plx import mounts


def test_parse_bind_variants():
    assert mounts.parse_bind("/src") == mounts.Bind("/src", "/src")
    parsed = mounts.parse_bind("/src:/dst")
    assert (parsed.src, parsed.dst, parsed.ro) == ("/src", "/dst", False)
    read_only = mounts.parse_bind("/src:/dst:ro")
    assert read_only.ro is True and read_only.dst == "/dst"
    same_ro = mounts.parse_bind("/src:ro")
    assert same_ro.ro is True and same_ro.dst == "/src"


@pytest.mark.parametrize("spec", ["", "   ", "/a:/b:rw", "/a:/b:ro:extra"])
def test_parse_bind_rejects_bad_specs(spec):
    with pytest.raises(mounts.MountError):
        mounts.parse_bind(spec)


def test_default_binds_include_kernel_filesystems(cfg):
    names = {bind.dst for bind in mounts.default_binds(cfg)}
    assert {"/dev", "/proc", "/sys"} <= names


def test_storage_bind_uses_detected_path(cfg, monkeypatch, tmp_path: Path):
    shared = tmp_path / "shared"
    shared.mkdir()
    monkeypatch.setattr(mounts.device, "shared_storage", lambda: shared)
    binds = mounts.default_binds(cfg)
    assert any(bind.src == str(shared) and bind.dst == "/mnt/storage" for bind in binds)


def test_storage_bind_disabled(cfg, monkeypatch, tmp_path: Path):
    shared = tmp_path / "shared"
    shared.mkdir()
    monkeypatch.setattr(mounts.device, "shared_storage", lambda: shared)
    cfg.mounts.storage = False
    assert not any(bind.dst == "/mnt/storage" for bind in mounts.default_binds(cfg))


def test_extra_mounts_are_optional(cfg):
    cfg.mounts.extra = ["/definitely/missing:/mnt/x:ro"]
    binds = mounts.default_binds(cfg)
    extra = [bind for bind in binds if bind.dst == "/mnt/x"][0]
    assert extra.ro is True and extra.optional is True
    present, skipped = mounts.usable_binds(binds)
    assert extra in skipped


def test_proot_argv_shape(cfg):
    argv = mounts.proot_argv(cfg, command="uname -a")
    assert argv[0] == "proot"
    assert "-0" in argv and "--kill-on-exit" in argv
    assert str(cfg.rootfs) in argv
    assert argv[-3:] == [cfg.core.shell, "-lc", "uname -a"]
    assert any(part.startswith("HOME=") for part in argv)
    assert "-b" in argv


def test_proot_argv_login_shell(cfg):
    argv = mounts.proot_argv(cfg)
    assert argv[-1] == "-l"


def test_proot_argv_requires_rootfs(cfg, tmp_path: Path):
    cfg.core.rootfs = str(tmp_path / "does-not-exist")
    with pytest.raises(mounts.MountError, match="rootfs missing"):
        mounts.proot_argv(cfg)


def test_proot_argv_falls_back_to_sh(cfg):
    (cfg.rootfs / "bin/bash").unlink()
    argv = mounts.proot_argv(cfg, command="true")
    assert argv[-3] == "/bin/sh"


def test_chroot_script_is_namespaced(cfg):
    script = mounts.chroot_script(cfg, "id")
    assert "unshare -m" in script
    assert "mount -o bind" in script
    assert "chroot" in script
    assert str(cfg.rootfs) in script


def test_chroot_script_read_only_remount(cfg):
    cfg.mounts.extra = [f"{cfg.rootfs}:/mnt/ro:ro"]
    script = mounts.chroot_script(cfg, "true")
    assert "remount,bind,ro" in script


def test_chroot_argv_uses_su(cfg):
    argv = mounts.chroot_argv(cfg, "id")
    assert argv[0] == "su" and argv[1] == "-c"


def test_engine_argv_selects_engine(cfg):
    assert mounts.engine_argv(cfg, "true", engine="proot")[0] == "proot"
    assert mounts.engine_argv(cfg, "true", engine="chroot")[0] == "su"
    with pytest.raises(mounts.MountError):
        mounts.engine_argv(cfg, "true", engine="quantum")


def test_explain_payload(cfg):
    info = mounts.explain(cfg)
    assert info["engine"] == "proot"
    assert info["rootfs_exists"] is True
    assert isinstance(info["binds"], list)
    assert all({"src", "dst", "ro"} <= set(bind) for bind in info["binds"])


def test_engine_availability(monkeypatch):
    monkeypatch.setattr(mounts.device, "find_tool", lambda name: "/usr/bin/proot")
    assert mounts.proot_available() is True
    monkeypatch.setattr(mounts.device, "find_tool", lambda name: None)
    assert mounts.proot_available() is False
