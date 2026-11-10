from __future__ import annotations

from pathlib import Path

import pytest

from plx import config as config_mod


def test_defaults_when_file_missing(tmp_path: Path):
    cfg = config_mod.load(tmp_path / "absent.toml")
    assert cfg.core.engine == "proot"
    assert cfg.core.distro == "ubuntu"
    assert cfg.mounts.storage is True
    assert cfg.net.ssh_port == 8022
    assert cfg.net.ssh_bind == "127.0.0.1"
    assert cfg.warnings == []


def test_roundtrip(tmp_path: Path):
    cfg = config_mod.Config()
    cfg.mounts.extra = ["/sdcard/Download:/root/dl", "/tmp:/tmp:ro"]
    cfg.core.distro = "alpine"
    cfg.net.ssh_port = 2222
    target = tmp_path / "config.toml"
    config_mod.save(cfg, target)
    loaded = config_mod.load(target)
    assert loaded.core.distro == "alpine"
    assert loaded.net.ssh_port == 2222
    assert loaded.mounts.extra == cfg.mounts.extra


def test_invalid_engine_falls_back_with_warning(tmp_path: Path):
    target = tmp_path / "config.toml"
    target.write_text('[core]\nengine = "magic"\n')
    cfg = config_mod.load(target)
    assert cfg.core.engine == "proot"
    assert any("engine" in warning for warning in cfg.warnings)


def test_unknown_section_warns(tmp_path: Path):
    target = tmp_path / "config.toml"
    target.write_text('[core]\ndistro = "alpine"\n[bogus]\nx = 1\n')
    cfg = config_mod.load(target)
    assert any("bogus" in warning for warning in cfg.warnings)


def test_bad_ssh_port_uses_default(tmp_path: Path):
    target = tmp_path / "config.toml"
    target.write_text("[net]\nssh_port = 99999\n")
    cfg = config_mod.load(target)
    assert cfg.net.ssh_port == 8022
    assert any("ssh_port" in warning for warning in cfg.warnings)


def test_invalid_toml_raises(tmp_path: Path):
    target = tmp_path / "config.toml"
    target.write_text("[core\nengine = ")
    with pytest.raises(config_mod.ConfigError):
        config_mod.load(target)


def test_storage_false(tmp_path: Path):
    target = tmp_path / "config.toml"
    target.write_text("[mounts]\nstorage = false\n")
    assert config_mod.load(target).mounts.storage is False


def test_init_respects_existing_file(tmp_path: Path):
    target = tmp_path / "config.toml"
    path, written = config_mod.init(target)
    assert written and path.exists()
    path.write_text('[core]\ndistro = "alpine"\n')
    _, written_again = config_mod.init(target)
    assert written_again is False
    assert config_mod.load(target).core.distro == "alpine"
    _, written_force = config_mod.init(target, force=True)
    assert written_force is True
    assert config_mod.load(target).core.distro == "ubuntu"


def test_set_value_string_int_bool_and_list():
    cfg = config_mod.Config()
    assert config_mod.set_value(cfg, "core.distro", "debian").core.distro == "debian"
    assert config_mod.set_value(cfg, "net.ssh_port", "2022").net.ssh_port == 2022
    assert config_mod.set_value(cfg, "mounts.storage", "no").mounts.storage is False
    updated = config_mod.set_value(cfg, "mounts.extra", "/a:/b, /c:/d")
    assert updated.mounts.extra == ["/a:/b", "/c:/d"]


def test_set_value_rejects_unknown_keys():
    cfg = config_mod.Config()
    with pytest.raises(config_mod.ConfigError):
        config_mod.set_value(cfg, "core.nope", "x")
    with pytest.raises(config_mod.ConfigError):
        config_mod.set_value(cfg, "nonsense", "x")
    with pytest.raises(config_mod.ConfigError):
        config_mod.set_value(cfg, "net.ssh_port", "not-a-number")


def test_resolved_rootfs_uses_distro(plx_home: Path):
    cfg = config_mod.Config()
    assert cfg.rootfs.name == "ubuntu"
    assert cfg.with_overrides(distro="alpine").rootfs.name == "alpine"
    custom = cfg.with_overrides(rootfs="/tmp/custom-rf")
    assert str(custom.rootfs) == "/tmp/custom-rf"
