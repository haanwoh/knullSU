from __future__ import annotations

import platform

from plx import device


def test_props_empty_without_android(monkeypatch):
    monkeypatch.delenv(device.FAKE_PROPS_ENV, raising=False)
    monkeypatch.setattr(device.util, "have", lambda name: False)
    assert device.props() == {}


def test_fake_props_are_used(fake_android):
    props = device.props()
    assert props["ro.product.model"] == "Pixel 7"
    assert device.is_android() is True
    assert device.info()["model"] == "Pixel 7"
    assert device.info()["android"] == "15"


def test_summary_line_mentions_model(fake_android):
    line = device.summary_line()
    assert "Google Pixel 7" in line
    assert "Android 15" in line


def test_arch_mapping(monkeypatch):
    for machine, expected in (
        ("aarch64", "aarch64"),
        ("arm64", "aarch64"),
        ("armv7l", "armv7"),
        ("x86_64", "x86_64"),
        ("i686", "i686"),
        ("mips", "mips"),
    ):
        monkeypatch.setattr(platform, "machine", lambda m=machine: m)
        assert device.arch() == expected


def test_info_keys_present(fake_rootfs):
    data = device.info()
    for key in (
        "plx_version",
        "python",
        "kernel",
        "arch",
        "cpus",
        "is_android",
        "is_termux",
        "root_present",
        "selinux",
        "plx_home",
        "storage",
        "tools",
    ):
        assert key in data


def test_storage_dirs_returns_existing_paths():
    for path in device.storage_dirs():
        assert path.exists()


def test_can_write(tmp_path):
    assert device.can_write(tmp_path) is True
    assert not list(tmp_path.iterdir())
