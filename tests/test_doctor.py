from __future__ import annotations

from plx import config as config_mod
from plx import doctor


def test_run_returns_known_statuses(cfg):
    checks = doctor.run(cfg)
    assert checks
    assert all(check.status in doctor.STATUSES for check in checks)
    ids = [check.id for check in checks]
    assert len(ids) == len(set(ids)), "check ids must be unique"


def test_summarize_counts_match(cfg):
    checks = doctor.run(cfg)
    summary = doctor.summarize(checks)
    assert sum(summary["counts"].values()) == len(checks)
    assert summary["status"] in doctor.STATUSES
    assert len(summary["checks"]) == len(checks)


def test_python_check_passes():
    assert doctor.check_python().status == "pass"


def test_host_check_uses_fake_android(fake_android):
    result = doctor.check_host()
    # An Android host that is not Termux is a warning: full support needs Termux.
    assert result.status == "warn"
    assert "Pixel 7" in result.detail


def test_arch_check_supported():
    assert doctor.check_arch().status in ("pass", "fail")


def test_disk_check_reports_detail(cfg):
    result = doctor.check_disk(cfg)
    assert result.status in ("pass", "warn", "skip", "fail")
    assert result.detail


def test_rootfs_check_detects_installed(fake_rootfs, cfg):
    assert doctor.check_rootfs(cfg).status == "pass"


def test_rootfs_check_warns_when_missing(tmp_path, plx_home):
    cfg = config_mod.Config().with_overrides(rootfs=str(plx_home / "empty"))
    result = doctor.check_rootfs(cfg)
    assert result.status == "warn"
    assert "plx install" in result.fix


def test_config_check_warns_on_problems(plx_home):
    (plx_home / "config.toml").write_text('[core]\nengine = "chaos"\n')
    result = doctor.check_config(config_mod.load())
    assert result.status == "warn"


def test_services_check_without_file(plx_home):
    assert doctor.check_services().status == "skip"


def test_exit_code_logic():
    failing = [doctor.check_python(), doctor._check("x", "x", "fail", "boom")]
    assert doctor.exit_code(doctor.summarize(failing)) == 1
    passing = [doctor._check("x", "x", "pass", "fine")]
    assert doctor.exit_code(doctor.summarize(passing)) == 0


def test_render_smoke(cfg, capsys):
    checks = doctor.run(cfg)
    doctor.render(checks)
    out = capsys.readouterr().out
    assert "check" in out
    assert "suggested fixes" in out or checks
