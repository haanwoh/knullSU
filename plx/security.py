"""Honest security posture reporting for the device PocketLinux runs on.

This module is the counterweight to every "one-click root" promise on the
internet.  It tells you what is actually true about your phone — bootloader
state, SELinux, ADB-over-network, which ports are listening on every interface —
and it refuses to pretend that ``plx`` can do things it cannot.

Scope statement (also printed by ``plx security report``):
  * ``plx`` does **not** root devices, bypass lockscreens, or escalate privilege.
  * It gives you a full Linux userland, a service tree and documented hardware
    access *on hardware you own and control*.
  * Everything it changes lives under ``~/.plx`` plus bind-mounted guest paths.
"""

from __future__ import annotations

import os
from typing import Any

from . import net, paths, supervisor, util
from .config import Config

SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3}

VBOOT_MEANING = {
    "green": "bootloader locked, stock verified boot chain",
    "yellow": "bootloader locked with a custom key",
    "orange": "bootloader unlocked (dm-verity may be off)",
    "red": "verification failed or custom boot image",
}

SCOPE = [
    "plx does not root devices, unlock bootloaders, or bypass any lock screen.",
    "plx gives you a real Linux userland, a supervisor and Termux:API hardware access.",
    "plx writes only inside PLX_HOME and bind-mounted guest paths — it never touches /system.",
]


def _finding(id: str, severity: str, title: str, detail: str, fix: str = "") -> dict[str, str]:
    return {"id": id, "severity": severity, "title": title, "detail": detail, "fix": fix}


def _props() -> dict[str, str]:
    from . import device

    return device.props()


def boot_state() -> dict[str, Any]:
    props = _props()
    state = (
        props.get("ro.boot.verifiedbootstate")
        or props.get("ro.boot.veritymode")
        or props.get("ro.boot.vbmeta.device_state")
        or "unknown"
    ).lower()
    locked = props.get("ro.boot.flash.locked") == "1"
    return {
        "verified_boot_state": state,
        "meaning": VBOOT_MEANING.get(state, "unknown or not reported by this device"),
        "bootloader_locked": locked if "ro.boot.flash.locked" in props else None,
        "selinux": props.get("ro.boot.selinux") or _selinux(),
        "debuggable": props.get("ro.debuggable") == "1",
        "security_patch": props.get("ro.build.version.security_patch", "unknown"),
    }


def _selinux() -> str:
    from . import device

    return device.selinux_mode()


def collect_findings(config: Config) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    boot = boot_state()
    state = boot["verified_boot_state"]

    if state == "green":
        findings.append(
            _finding(
                "vboot", "info", "Verified boot is green", "Stock locked boot chain is intact."
            )
        )
    elif state in ("orange", "yellow", "red"):
        findings.append(
            _finding(
                "vboot",
                "medium" if state != "red" else "high",
                f"Verified boot is {state}",
                boot["meaning"],
                "Only use this state on hardware you own; some banking/DRM apps will refuse to run.",
            )
        )
    else:
        findings.append(
            _finding("vboot", "info", "Verified boot state unknown", "Device does not report it.")
        )

    if boot["bootloader_locked"] is False:
        findings.append(
            _finding(
                "bootloader",
                "medium",
                "Bootloader is unlocked",
                "Anyone with physical access and a USB cable can reflash this device.",
                "Re-lock the bootloader when you are done experimenting.",
            )
        )

    if boot["debuggable"]:
        findings.append(
            _finding(
                "debuggable",
                "high",
                "Build is debuggable",
                "ro.debuggable=1 allows attaching to app processes.",
                "Use a production build for daily use.",
            )
        )

    selinux = (boot["selinux"] or "").lower()
    if selinux and selinux not in ("enforcing", "unknown", ""):
        findings.append(
            _finding(
                "selinux",
                "medium",
                "SELinux is not enforcing",
                f"getenforce reports {selinux!r}.",
                "Set it back to enforcing unless you are actively debugging.",
            )
        )
    elif selinux == "enforcing":
        findings.append(
            _finding("selinux", "info", "SELinux enforcing", "Mandatory access control is on.")
        )

    adb_port = _props().get("service.adb.tcp.port", "")
    if adb_port:
        findings.append(
            _finding(
                "adb",
                "high",
                "ADB is listening over the network",
                f"service.adb.tcp.port={adb_port} — anyone on the same network can try to connect.",
                "adb usb   (turn wireless debugging off when not in use)",
            )
        )

    if util.which("su"):
        findings.append(
            _finding(
                "root",
                "low",
                "A su binary is present",
                "Root is already available on this device; plx itself does not install it.",
            )
        )

    if config.net.ssh_bind not in ("127.0.0.1", "localhost", "::1"):
        findings.append(
            _finding(
                "sshd_bind",
                "medium",
                "Guest sshd is bound to the network",
                f"net.ssh_bind={config.net.ssh_bind} — reachable from other machines.",
                "plx config set net.ssh_bind 127.0.0.1, and use `plx net tunnel` from a trusted host.",
            )
        )

    exposed = [entry for entry in net.listening_ports() if entry.get("exposed")]
    if exposed:
        ports = ", ".join(str(entry["port"]) for entry in exposed[:8])
        findings.append(
            _finding(
                "ports",
                "low" if len(exposed) < 5 else "medium",
                f"{len(exposed)} port(s) listening on all interfaces",
                f"tcp: {ports}{' …' if len(exposed) > 8 else ''}",
                "Stop services you do not need: plx service stop <name>",
            )
        )

    try:
        mode = os.stat(paths.home()).st_mode & 0o777
        if mode & 0o077:
            findings.append(
                _finding(
                    "home_perms",
                    "low",
                    f"{paths.home()} is group/world readable ({oct(mode)})",
                    "Keys, logs and service configs live there.",
                    f"chmod 700 {paths.home()}",
                )
            )
    except OSError:
        pass

    return sorted(findings, key=lambda item: SEVERITY_ORDER.get(item["severity"], 0), reverse=True)


def report(config: Config) -> dict[str, Any]:
    findings = collect_findings(config)
    counts = {severity: 0 for severity in SEVERITY_ORDER}
    for finding in findings:
        counts[finding["severity"]] = counts.get(finding["severity"], 0) + 1
    worst = max(
        (finding["severity"] for finding in findings),
        key=lambda severity: SEVERITY_ORDER.get(severity, 0),
        default="info",
    )
    return {
        "device": boot_state(),
        "findings": findings,
        "counts": counts,
        "worst": worst,
        "scope": SCOPE,
        "ssh": net.session_info(config),
        "exposed_ports": [entry for entry in net.listening_ports() if entry.get("exposed")],
        "plx_home": {"path": str(paths.home()), "exists": paths.home().exists()},
        "services": sorted(supervisor.load_services().keys())
        if paths.services_file().exists()
        else [],
    }


def harden(config: Config, *, apply: bool = False, dry_run: bool = False) -> dict[str, Any]:
    """Apply the safe-by-default settings; report exactly what changed."""
    actions: list[dict[str, Any]] = []

    def plan(action: str, target: str, detail: str) -> None:
        actions.append({"action": action, "target": target, "detail": detail, "applied": False})

    sshd_target = config.rootfs / "etc/ssh/sshd_config"
    plan(
        "write-sshd-config",
        str(sshd_target),
        f"no password auth, bind {config.net.ssh_bind}:{config.net.ssh_port}",
    )
    if (config.rootfs / "root/.ssh").exists():
        plan("chmod", str(config.rootfs / "root/.ssh"), "700")
        plan("chmod", str(config.rootfs / "root/.ssh/id_ed25519"), "600 (if present)")
    plan("chmod", str(paths.home()), "700")

    if dry_run or not apply:
        return {"applied": False, "actions": actions}

    net.write_sshd_config(config, password_auth=False, force=True)
    for key_mode in (
        (config.rootfs / "root/.ssh", 0o700),
        (config.rootfs / "root/.ssh/id_ed25519", 0o600),
        (paths.home(), 0o700),
    ):
        path, mode = key_mode
        if path.exists():
            try:
                os.chmod(path, mode)
            except OSError:
                continue
    for action in actions:
        action["applied"] = True
    return {"applied": True, "actions": actions}


def render(report_data: dict[str, Any]) -> None:
    from . import console

    device_info = report_data["device"]
    console.kv_block(
        {
            "verified boot": f"{device_info['verified_boot_state']} — {device_info['meaning']}",
            "selinux": device_info["selinux"],
            "security patch": device_info["security_patch"],
            "worst finding": report_data["worst"],
        }
    )
    console.header("findings")
    rows = [
        [finding["severity"], finding["title"], finding["detail"][:70]]
        for finding in report_data["findings"]
    ]
    console.table(["severity", "finding", "detail"], rows)
    suggestions = [finding for finding in report_data["findings"] if finding.get("fix")]
    if suggestions:
        console.header("hardening suggestions")
        console.bullet_list(f"{item['title']}: {item['fix']}" for item in suggestions)
    console.header("scope")
    console.bullet_list(report_data["scope"])
