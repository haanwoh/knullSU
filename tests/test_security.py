from __future__ import annotations

from pathlib import Path

from plx import security


def test_report_has_scope_and_findings(cfg):
    report = security.report(cfg)
    assert report["scope"]
    assert isinstance(report["findings"], list)
    assert report["worst"] in security.SEVERITY_ORDER
    assert "verified_boot_state" in report["device"]


def test_unlocked_bootloader_is_flagged(fake_android, cfg):
    report = security.report(cfg)
    ids = {finding["id"] for finding in report["findings"]}
    assert "vboot" in ids
    assert "bootloader" in ids
    boot = next(finding for finding in report["findings"] if finding["id"] == "bootloader")
    assert boot["severity"] == "medium"


def test_adb_over_network_is_high(fake_android, cfg, monkeypatch):
    import json

    props = {**fake_android, "service.adb.tcp.port": "5555"}
    monkeypatch.setenv("PLX_FAKE_PROPS", json.dumps(props))
    report = security.report(cfg)
    adb = next((f for f in report["findings"] if f["id"] == "adb"), None)
    assert adb is not None and adb["severity"] == "high"


def test_ssh_bind_exposure_flagged(fake_android, cfg):
    cfg.net.ssh_bind = "0.0.0.0"
    report = security.report(cfg)
    assert any(finding["id"] == "sshd_bind" for finding in report["findings"])


def test_harden_plan_only_by_default(fake_android, cfg, fake_rootfs: Path):
    result = security.harden(cfg)
    assert result["applied"] is False
    assert not (fake_rootfs / "etc/ssh/sshd_config").exists()


def test_harden_apply_writes_sshd_config(fake_android, cfg, fake_rootfs: Path):
    result = security.harden(cfg, apply=True)
    assert result["applied"] is True
    text = (fake_rootfs / "etc/ssh/sshd_config").read_text()
    assert "PasswordAuthentication no" in text
    assert f"Port {cfg.net.ssh_port}" in text
    assert all(action["applied"] for action in result["actions"])


def test_harden_dry_run_does_not_write(fake_android, cfg, fake_rootfs: Path):
    result = security.harden(cfg, apply=True, dry_run=True)
    assert result["applied"] is False
    assert not (fake_rootfs / "etc/ssh/sshd_config").exists()
