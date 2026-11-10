"""End-to-end CLI tests: the same entry point a user types on their phone."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from plx.cli import main


def run(argv: list[str], capsys) -> tuple[int, str, str]:
    code = main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def run_json(argv: list[str], capsys) -> tuple[int, dict]:
    code, out, err = run(argv, capsys)
    if not out.strip():
        raise AssertionError(f"no JSON output (stderr: {err!r})")
    return code, json.loads(out)


def test_version_json(capsys):
    code, payload = run_json(["--json", "version"], capsys)
    assert code == 0
    assert payload["name"] == "pocketlinux"
    assert payload["version"]


def test_no_command_prints_help(capsys):
    code, out, _ = run([], capsys)
    assert code == 0
    assert "usage: plx" in out


def test_info_json(plx_home: Path, fake_android, cfg, capsys):
    code, payload = run_json(["info", "--json"], capsys)
    assert code == 0
    assert payload["device"]["model"] == "Pixel 7"
    assert payload["rootfs"]["populated"] is True
    assert "engines" in payload


def test_doctor_json(plx_home: Path, cfg, capsys):
    code, payload = run_json(["doctor", "--json"], capsys)
    assert code in (0, 1)
    assert payload["counts"]
    assert len(payload["checks"]) > 5


def test_doctor_human_output(plx_home: Path, cfg, capsys):
    code, out, _ = run(["doctor"], capsys)
    assert code in (0, 1)
    assert "check" in out


def test_install_list_json(plx_home: Path, capsys):
    code, payload = run_json(["install", "--list", "--json"], capsys)
    assert code == 0
    names = {entry["name"] for entry in payload["distros"]}
    assert {"ubuntu", "alpine", "debian"} <= names
    assert payload["current_arch"]


def test_install_dry_run_json(plx_home: Path, cfg, capsys):
    code, payload = run_json(["install", "alpine", "--dry-run", "--json"], capsys)
    assert code == 0
    assert payload["dry_run"] is True
    assert payload["distro"] == "alpine"


def test_config_init_set_show(plx_home: Path, capsys):
    code, out, _ = run(["config", "init"], capsys)
    assert code == 0 and "wrote" in out
    code, out, _ = run(["config", "set", "core.distro", "alpine"], capsys)
    assert code == 0
    code, payload = run_json(["config", "show", "--json"], capsys)
    assert payload["config"]["core"]["distro"] == "alpine"


def test_config_path(capsys, plx_home: Path):
    code, out, _ = run(["config", "path"], capsys)
    assert code == 0
    assert str(plx_home / "config.toml") in out


def test_rootfs_status_json(cfg, capsys):
    code, payload = run_json(["rootfs", "status", "--json"], capsys)
    assert code == 0
    assert payload["populated"] is True
    assert "Ubuntu" in payload["distro_name"]


def test_shell_show_json(cfg, capsys):
    code, payload = run_json(["shell", "--show", "--json"], capsys)
    assert code == 0
    assert payload["rootfs_ready"] is True
    assert set(payload["engines"]) == {"proot", "chroot"}


def test_shell_chroot_dry_run(cfg, capsys):
    code, out, _ = run(["shell", "--engine", "chroot", "--dry-run"], capsys)
    assert code == 0
    assert "unshare" in out and "chroot" in out


def test_shell_without_rootfs_errors(plx_home: Path, capsys):
    code, _, err = run(["shell", "--dry-run"], capsys)
    assert code == 2
    assert "rootfs" in err.lower()


def test_shell_error_as_json(plx_home: Path, capsys):
    code, out, _ = run(["shell", "--dry-run", "--json"], capsys)
    assert code == 2
    assert json.loads(out)["ok"] is False


def test_mount_show_json(cfg, capsys):
    code, payload = run_json(["mount", "show", "--json"], capsys)
    assert code == 0
    assert payload["engine"] == "proot"
    assert payload["binds"]


def test_service_ls_json(cfg, plx_home: Path, capsys):
    code, payload = run_json(["service", "ls", "--json"], capsys)
    assert code == 0
    assert payload["daemon_running"] is False


def test_service_status_when_down(plx_home: Path, capsys):
    code, payload = run_json(["service", "status", "--json"], capsys)
    assert code == 0
    assert payload["daemon"]["running"] is False


def test_service_start_without_daemon(plx_home: Path, capsys):
    code, _, err = run(["service", "start", "web"], capsys)
    assert code == 1
    assert "plxd" in err


def test_service_example_and_ls(plx_home: Path, capsys):
    code, out, _ = run(["service", "example"], capsys)
    assert code == 0
    assert (plx_home / "services.toml").exists()
    code, out, _ = run(["service", "ls"], capsys)
    assert code == 0
    assert "no services defined" in out


def test_recipe_ls_json(cfg, capsys):
    code, payload = run_json(["recipe", "ls", "--json"], capsys)
    assert code == 0
    names = {entry["name"] for entry in payload["recipes"]}
    assert {"devbox", "minimal"} <= names


def test_recipe_show_json(cfg, capsys):
    code, payload = run_json(["recipe", "show", "devbox", "--json"], capsys)
    assert code == 0
    assert payload["base"] == "ubuntu"
    assert payload["services"]


def test_recipe_apply_dry_run(cfg, capsys):
    code, payload = run_json(["recipe", "apply", "devbox", "--dry-run", "--json"], capsys)
    assert code == 0
    assert payload["ok"] is True
    assert payload["package_manager"] == "apt"


def test_hw_ls_json(capsys):
    code, payload = run_json(["hw", "ls", "--json"], capsys)
    assert code == 0
    assert any(tool["name"] == "battery" for tool in payload["tools"])


def test_hw_unknown_tool(plx_home: Path, capsys):
    code, _, err = run(["hw", "call", "warp-drive"], capsys)
    assert code == 2
    assert "unknown hardware tool" in err


def test_hw_missing_termux_api(plx_home: Path, capsys):
    code, payload = run_json(["hw", "battery", "--json"], capsys)
    assert code == 1
    assert payload["ok"] is False
    assert "termux-api" in payload["stderr"]


def test_backup_create_list_verify(cfg, capsys):
    code, payload = run_json(["backup", "create", "--compress", "gzip", "--json"], capsys)
    assert code == 0
    archive = Path(payload["archive"])
    assert archive.exists()
    code, listing = run_json(["backup", "ls", "--json"], capsys)
    assert listing["backups"][0]["archive"] == str(archive)
    code, verified = run_json(["backup", "verify", str(archive), "--json"], capsys)
    assert code == 0 and verified["verified"] is True


def test_backup_restore_needs_yes(cfg, capsys):
    code, payload = run_json(["backup", "create", "--compress", "gzip", "--json"], capsys)
    code, _, err = run(["backup", "restore", payload["archive"]], capsys)
    assert code == 2
    assert "--yes" in err


def test_net_ip_and_ports(cfg, capsys):
    code, payload = run_json(["net", "ip", "--json"], capsys)
    assert code == 0 and payload["hostname"]
    code, payload = run_json(["net", "ports", "--json"], capsys)
    assert code == 0 and isinstance(payload["ports"], list)


def test_net_sshd_config(cfg, capsys):
    code, payload = run_json(["net", "sshd-config", "--json"], capsys)
    assert code == 0
    assert payload["changed"] is True


def test_gui_status_json(cfg, capsys):
    code, payload = run_json(["gui", "status", "--json"], capsys)
    assert code == 0
    assert payload["display"] == ":0"


def test_security_report_json(cfg, fake_android, capsys):
    code, payload = run_json(["security", "report", "--json"], capsys)
    assert code == 0
    assert payload["scope"]
    assert payload["findings"]


def test_security_harden_dry_run(cfg, fake_android, capsys):
    code, payload = run_json(["security", "harden", "--dry-run", "--json"], capsys)
    assert code == 0
    assert payload["applied"] is False
    assert payload["actions"]


def test_invalid_command_exits(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["not-a-command"])
    assert excinfo.value.code == 2


def test_home_flag_overrides_env(tmp_path: Path, capsys):
    custom = tmp_path / "custom-home"
    code, out, _ = run(["--home", str(custom), "config", "init"], capsys)
    assert code == 0
    assert (custom / "config.toml").exists()
