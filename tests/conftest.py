"""Shared fixtures.

Every test runs against a throw-away ``PLX_HOME`` so the suite can never touch
a real phone's rootfs, keys, logs or service definitions.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

if str(REPO_ROOT) not in sys.path:  # allows `pytest tests/` from anywhere
    sys.path.insert(0, str(REPO_ROOT))

from plx import config as config_mod  # noqa: E402
from plx import console  # noqa: E402


@pytest.fixture(autouse=True)
def reset_console():
    console.configure(json_mode=False, quiet=False, color=False)
    yield
    console.configure(json_mode=False, quiet=False, color=None)


@pytest.fixture
def plx_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "plxhome"
    home.mkdir()
    monkeypatch.setenv("PLX_HOME", str(home))
    return home


@pytest.fixture
def fake_android(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    props = {
        "ro.product.model": "Pixel 7",
        "ro.product.manufacturer": "Google",
        "ro.product.device": "panther",
        "ro.build.version.release": "15",
        "ro.build.version.sdk": "35",
        "ro.product.cpu.abi": "arm64-v8a",
        "ro.boot.verifiedbootstate": "orange",
        "ro.boot.flash.locked": "0",
        "ro.debuggable": "0",
        "ro.boot.selinux": "enforcing",
        "ro.build.version.security_patch": "2026-10-05",
        "service.adb.tcp.port": "",
    }
    monkeypatch.setenv("PLX_FAKE_PROPS", json.dumps(props))
    return props


@pytest.fixture
def fake_rootfs(plx_home: Path) -> Path:
    """A minimal directory tree that quacks like a Linux rootfs."""
    root = plx_home / "rootfs" / "ubuntu"
    for directory in ("etc/apt", "bin", "usr/bin", "usr/sbin", "root/.ssh", "var/log"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    for shell in ("bin/sh", "bin/bash"):
        target = root / shell
        target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        target.chmod(0o755)
    (root / "etc/os-release").write_text(
        'PRETTY_NAME="Ubuntu 24.04 LTS"\nNAME="Ubuntu"\nID=ubuntu\n', encoding="utf-8"
    )
    (root / "usr/bin/apt-get").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (root / "usr/sbin/sshd").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    return root


@pytest.fixture
def cfg(plx_home: Path, fake_rootfs: Path) -> config_mod.Config:
    base = config_mod.Config()
    config_mod.save(base.with_overrides(rootfs=str(fake_rootfs)))
    return config_mod.load()


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def daemon_env(plx_home: Path) -> dict[str, str]:
    return {
        **os.environ,
        "PLX_HOME": str(plx_home),
        "PYTHONPATH": f"{REPO_ROOT}{os.pathsep}{os.environ.get('PYTHONPATH', '')}".rstrip(
            os.pathsep
        ),
    }
