"""Networking helpers: addresses, listening ports, SSH keys and sshd config.

The security default is deliberate: sshd is configured to bind **loopback only**
and to refuse password logins.  Exposing a phone's sshd to the LAN is one
``plx config set net.ssh_bind 0.0.0.0`` away, but it is never the default and
``plx security report`` will flag it if you do it.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Any

from . import console, util
from .config import Config

SSHD_CONFIG = """\
# written by plx — regenerate with: plx net sshd-config --force
Port {port}
ListenAddress {bind}
Protocol 2
HostKey /etc/ssh/ssh_host_ed25519_key
HostKey /etc/ssh/ssh_host_rsa_key
PermitRootLogin prohibit-password
PasswordAuthentication {password_auth}
KbdInteractiveAuthentication no
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
X11Forwarding no
AllowAgentForwarding yes
AllowTcpForwarding yes
PermitTunnel no
ClientAliveInterval 60
ClientAliveCountMax 3
MaxAuthTries 4
Subsystem sftp internal-sftp
UsePAM no
PrintMotd no
AcceptEnv LANG LC_*
"""


def local_ips() -> list[str]:
    ips: list[str] = []
    if util.have("ip"):
        result = util.run(["ip", "-o", "-4", "addr", "show"], timeout=5)
        for line in result.out.splitlines():
            parts = line.split()
            for index, token in enumerate(parts):
                if token == "inet" and index + 1 < len(parts):
                    address = parts[index + 1].split("/")[0]
                    if address not in ips:
                        ips.append(address)
    if not ips:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("1.1.1.1", 80))
                ips.append(sock.getsockname()[0])
        except OSError:
            pass
    return ips


def hostname() -> str:
    return socket.gethostname()


def port_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def listening_ports() -> list[dict[str, Any]]:
    """Listening TCP sockets, from ``ss`` when available, else /proc."""
    if util.have("ss"):
        result = util.run(["ss", "-ltnH"], timeout=5)
        if result.ok:
            entries: list[dict[str, Any]] = []
            for line in result.out.splitlines():
                parts = line.split()
                if len(parts) < 4:
                    continue
                local = parts[3]
                if ":" not in local:
                    continue
                addr, _, port = local.rpartition(":")
                try:
                    port_number = int(port)
                except ValueError:
                    continue
                entries.append(
                    {
                        "proto": "tcp",
                        "addr": addr or "*",
                        "port": port_number,
                        "exposed": addr in ("0.0.0.0", "*", "[::]", "::"),
                    }
                )
            return sorted(entries, key=lambda item: item["port"])
    return _proc_net_tcp()


def _proc_net_tcp() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for name, proto in (("/proc/net/tcp", "tcp"), ("/proc/net/tcp6", "tcp6")):
        text = util.read_text(name)
        for line in text.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 4 or parts[3] != "0A":  # 0A = LISTEN
                continue
            local = parts[1]
            if ":" not in local:
                continue
            _, _, port_hex = local.rpartition(":")
            try:
                port = int(port_hex, 16)
            except ValueError:
                continue
            entries.append({"proto": proto, "addr": "0.0.0.0", "port": port, "exposed": True})
    return sorted(entries, key=lambda item: item["port"])


def key_path(config: Config) -> Path:
    return config.rootfs / "root" / ".ssh" / "id_ed25519"


def ensure_ssh_key(
    config: Config, *, force: bool = False, comment: str | None = None
) -> dict[str, Any]:
    """Create an ed25519 keypair for the guest root user (host-side, no chroot)."""
    target = key_path(config)
    if target.exists() and not force:
        return {"created": False, "path": str(target), "public": _read_pub(target)}
    if not util.have("ssh-keygen"):
        raise FileNotFoundError("ssh-keygen not found — pkg install openssh")
    target.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(target.parent, 0o700)
    target.unlink(missing_ok=True)
    target.with_suffix(".pub").unlink(missing_ok=True)
    result = util.run(
        [
            "ssh-keygen",
            "-t",
            "ed25519",
            "-N",
            "",
            "-C",
            comment or f"plx@{hostname()}",
            "-f",
            str(target),
        ],
        timeout=30,
    )
    if not result.ok:
        raise RuntimeError(f"ssh-keygen failed: {result.err.strip() or result.code}")
    os.chmod(target, 0o600)
    return {"created": True, "path": str(target), "public": _read_pub(target)}


def _read_pub(key: Path) -> str:
    return util.read_text(key.with_suffix(".pub")).strip()


def sshd_config_text(config: Config, *, password_auth: bool = False) -> str:
    return SSHD_CONFIG.format(
        port=config.net.ssh_port,
        bind=config.net.ssh_bind,
        password_auth="yes" if password_auth else "no",
    )


def write_sshd_config(
    config: Config, *, password_auth: bool = False, force: bool = False
) -> dict[str, Any]:
    target = config.rootfs / "etc" / "ssh" / "sshd_config"
    text = sshd_config_text(config, password_auth=password_auth)
    if target.exists() and not force:
        existing = util.read_text(target)
        if existing.strip() == text.strip():
            return {"path": str(target), "changed": False}
    target.parent.mkdir(parents=True, exist_ok=True)
    util.atomic_write(target, text)
    return {"path": str(target), "changed": True}


def sshd_present(config: Config) -> bool:
    return (config.rootfs / "usr/sbin/sshd").exists() or (config.rootfs / "usr/bin/ssh").exists()


def session_info(config: Config) -> dict[str, Any]:
    ips = local_ips()
    host = ips[0] if ips else "127.0.0.1"
    exposed = config.net.ssh_bind not in ("127.0.0.1", "localhost", "::1")
    target_host = host if exposed else "127.0.0.1"
    return {
        "user": "root",
        "port": config.net.ssh_port,
        "bind": config.net.ssh_bind,
        "exposed_to_lan": exposed,
        "key": str(key_path(config)),
        "command": f"ssh -p {config.net.ssh_port} root@{target_host}",
        "from_host": f"ssh -p {config.net.ssh_port} root@{host}",
        "sshd_present": sshd_present(config),
        "addresses": ips,
        "hint": (
            "inside the guest: apt install openssh-server && /usr/sbin/sshd -D -e"
            if not sshd_present(config)
            else "start it: plx service start sshd"
        ),
    }


def diagnose(config: Config) -> dict[str, Any]:
    return {
        "hostname": hostname(),
        "ips": local_ips(),
        "ssh_port": config.net.ssh_port,
        "ssh_port_free": port_free(config.net.ssh_port),
        "listening": listening_ports(),
        "sshd_present": sshd_present(config),
    }


def banner(config: Config) -> None:
    info = session_info(config)
    console.kv_block(
        {
            "user": info["user"],
            "port": info["port"],
            "bind": f"{info['bind']} ({'LAN' if info['exposed_to_lan'] else 'loopback only'})",
            "from host": info["from_host"],
            "key": info["key"],
        }
    )
