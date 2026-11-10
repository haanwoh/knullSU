from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from plx import paths, supervisor

SERVICES = """
[service.sleeper]
command = ["{python}", "-c", "import time; time.sleep(60)"]
restart = "never"

[service.crasher]
command = ["{python}", "-c", "import sys; sys.exit(4)"]
restart = "always"
restart_delay = 0.05
max_restarts = 2
restart_window = 30
stop_timeout = 3
"""


def test_parse_valid_definition():
    specs = supervisor.parse_services(
        {"service": {"web": {"command": "python3 -m http.server 8080", "restart": "always"}}}
    )
    assert specs["web"].argv() == ["python3", "-m", "http.server", "8080"]
    assert specs["web"].restart == "always"


def test_parse_requires_command():
    with pytest.raises(supervisor.ServiceError, match="command"):
        supervisor.parse_services({"service": {"bad": {}}})


@pytest.mark.parametrize(
    "definition",
    [
        {"command": "true", "restart": "sometimes"},
        {"command": "true", "stop_signal": "SIGBANANA"},
        {"command": "true", "env": "not-a-table"},
        {"command": "true", "restart_delay": -5},
        {"command": 12},
    ],
)
def test_parse_rejects_bad_definitions(definition):
    with pytest.raises(supervisor.ServiceError):
        supervisor.parse_services({"service": {"x": definition}})


def test_parse_accepts_services_alias():
    specs = supervisor.parse_services({"services": {"a": {"command": "true"}}})
    assert "a" in specs


def test_save_and_load_roundtrip(plx_home: Path):
    specs = supervisor.parse_services(
        {
            "service": {
                "web": {
                    "command": ["python3", "-m", "http.server", "8080"],
                    "restart": "always",
                    "restart_delay": 1.5,
                    "env": {"A": "1"},
                    "description": "test service",
                }
            }
        }
    )
    target = supervisor.save_services(specs)
    loaded = supervisor.load_services(target)
    assert loaded["web"].argv() == ["python3", "-m", "http.server", "8080"]
    assert loaded["web"].restart_delay == 1.5
    assert loaded["web"].env == {"A": "1"}
    assert "test service" in target.read_text()


def test_load_missing_file_returns_empty(plx_home: Path):
    assert supervisor.load_services() == {}


def test_load_rejects_broken_toml(plx_home: Path):
    (plx_home / "services.toml").write_text("[service.x\ncommand = ")
    with pytest.raises(supervisor.ServiceError):
        supervisor.load_services()


def test_client_without_daemon(plx_home: Path):
    client = supervisor.SupervisorClient()
    with pytest.raises(supervisor.SupervisorError, match="not running"):
        client.status()
    assert supervisor.ping() is False


def test_daemon_lifecycle(plx_home: Path, daemon_env: dict[str, str], tmp_path: Path):
    services = plx_home / "services.toml"
    services.write_text(SERVICES.format(python=sys.executable))
    proc = subprocess.Popen(
        [sys.executable, "-m", "plx.plxd", "run"],
        env=daemon_env,
        cwd=str(Path(__file__).resolve().parent.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        assert supervisor.wait_for_socket(timeout=20), "plxd did not create its socket"
        client = supervisor.SupervisorClient()
        status = client.status()
        assert status["services"]["sleeper"]["state"] == "running"
        assert status["daemon"]["pid"] == proc.pid

        stopped = client.stop("sleeper")
        assert stopped["state"] == "stopped" and stopped["pid"] is None
        assert client.start("sleeper")["state"] == "running"

        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            crasher = client.status()["services"]["crasher"]
            if crasher["state"] == "failed":
                break
            time.sleep(0.1)
        assert crasher["state"] == "failed"
        assert crasher["restarts"] == 2
        assert "gave up" in (crasher["last_error"] or "")

        assert client.logs("sleeper", 5) == []
        assert paths.service_log("sleeper").exists()

        unknown = client.request
        with pytest.raises(supervisor.SupervisorError, match="unknown service"):
            client.start("ghost")
        assert unknown  # silence unused warnings

        client.shutdown()
        proc.wait(timeout=20)
        assert proc.returncode == 0
        assert supervisor.ping() is False
        assert not paths.socket_path().exists()
        assert not paths.pid_file().exists()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


def test_status_table_format():
    headers, rows = supervisor.format_status_table(
        {
            "services": {
                "web": {
                    "state": "running",
                    "pid": 42,
                    "restarts": 1,
                    "uptime": 30,
                    "command": "python3 -m http.server",
                }
            }
        }
    )
    assert headers[0] == "service"
    assert rows[0][0] == "web" and rows[0][2] == "42"
