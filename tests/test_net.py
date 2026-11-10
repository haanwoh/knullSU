from __future__ import annotations

import socket

import pytest

from plx import net, util


def test_local_ips_contains_strings():
    ips = net.local_ips()
    assert isinstance(ips, list)
    assert all(isinstance(ip, str) and ip for ip in ips)


def test_port_free_detects_bound_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        assert net.port_free(port) is False
    assert net.port_free(port) is True


def test_listening_ports_shape():
    entries = net.listening_ports()
    assert isinstance(entries, list)
    for entry in entries:
        assert {"proto", "addr", "port", "exposed"} <= set(entry)


def test_sshd_config_text(cfg):
    text = net.sshd_config_text(cfg)
    assert f"Port {cfg.net.ssh_port}" in text
    assert f"ListenAddress {cfg.net.ssh_bind}" in text
    assert "PasswordAuthentication no" in text
    assert "PermitRootLogin prohibit-password" in text


def test_sshd_config_password_auth_opt_in(cfg):
    assert "PasswordAuthentication yes" in net.sshd_config_text(cfg, password_auth=True)


def test_write_sshd_config_idempotent(cfg, fake_rootfs):
    first = net.write_sshd_config(cfg)
    assert first["changed"] is True
    second = net.write_sshd_config(cfg)
    assert second["changed"] is False
    forced = net.write_sshd_config(cfg, force=True)
    assert forced["changed"] is True


def test_session_info_loopback_default(cfg):
    info = net.session_info(cfg)
    assert info["exposed_to_lan"] is False
    assert info["command"].startswith("ssh -p")
    assert info["sshd_present"] is True


def test_session_info_lan_exposure(cfg):
    cfg.net.ssh_bind = "0.0.0.0"
    info = net.session_info(cfg)
    assert info["exposed_to_lan"] is True


@pytest.mark.skipif(util.which("ssh-keygen") is None, reason="ssh-keygen unavailable")
def test_ensure_ssh_key(cfg, fake_rootfs):
    result = net.ensure_ssh_key(cfg)
    assert result["created"] is True
    assert result["public"].startswith("ssh-ed25519")
    again = net.ensure_ssh_key(cfg)
    assert again["created"] is False


def test_diagnose_payload(cfg):
    payload = net.diagnose(cfg)
    assert {"hostname", "ips", "ssh_port", "listening", "sshd_present"} <= set(payload)
