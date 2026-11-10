"""Hardware bridge — the phone's sensors and actuators, from the shell.

Implemented entirely on top of Termux:API, which means every call goes through
Android's own permission prompts.  Nothing here bypasses the OS: if you have
not granted a permission, the call fails and tells you so.  That is the point —
"ground-level access" should mean *first-class access to documented interfaces*,
not a pile of exploits.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from . import util

#: name -> (binary, what it does)
TOOLS: dict[str, tuple[str, str]] = {
    "battery": ("termux-battery-status", "level, temperature, charging state"),
    "wifi": ("termux-wifi-connectioninfo", "SSID, link speed, IP, RSSI"),
    "sensors": ("termux-sensor", "list/read accelerometer, gyro, light, …"),
    "location": ("termux-location", "GPS/network fix (needs location permission)"),
    "torch": ("termux-torch", "camera flash on/off"),
    "clipboard-get": ("termux-clipboard-get", "read the clipboard"),
    "clipboard-set": ("termux-clipboard-set", "write the clipboard"),
    "notification": ("termux-notification", "post a notification"),
    "toast": ("termux-toast", "transient toast message"),
    "vibrate": ("termux-vibrate", "vibrate the phone"),
    "camera": ("termux-camera-photo", "capture a JPEG from a camera id"),
    "tts": ("termux-tts-speak", "text to speech"),
    "volume": ("termux-volume", "read/set stream volumes"),
    "brightness": ("termux-brightness", "set screen brightness"),
    "wake-lock": ("termux-wake-lock", "hold a partial wake lock"),
    "wake-unlock": ("termux-wake-unlock", "release the wake lock"),
    "telephony": ("termux-telephony-deviceinfo", "radio/network/device identifiers"),
    "sms-list": ("termux-sms-list", "list SMS (needs SMS permission)"),
    "share": ("termux-share", "share a file with other apps"),
    "open": ("termux-open", "open a file/URL in another app"),
}

#: Tools that take no interesting arguments; used by ``plx hw status``.
QUICK = ("battery", "wifi", "telephony")


@dataclass(slots=True)
class ToolStatus:
    name: str
    binary: str
    present: bool
    path: str | None
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "binary": self.binary,
            "present": self.present,
            "path": self.path,
            "description": self.description,
        }


def tools() -> list[ToolStatus]:
    return [
        ToolStatus(name, binary, bool(util.which(binary)), util.which(binary), description)
        for name, (binary, description) in sorted(TOOLS.items())
    ]


def available() -> dict[str, str]:
    return {name: path for name, path in ((t.name, t.path) for t in tools()) if path}


def call(name: str, args: list[str] | None = None, *, timeout: float = 30.0) -> dict[str, Any]:
    """Invoke one Termux:API tool and return a structured result."""
    if name not in TOOLS:
        raise KeyError(f"unknown hardware tool {name!r} — try: plx hw ls")
    binary, description = TOOLS[name]
    path = util.which(binary)
    if not path:
        return {
            "tool": name,
            "ok": False,
            "code": 127,
            "stdout": "",
            "stderr": (
                f"{binary} not found. Install the CLI and the app:\n"
                "  pkg install termux-api\n"
                "  install 'Termux:API' from F-Droid, then grant the permission when asked"
            ),
            "description": description,
        }
    result = util.run([path, *(args or [])], timeout=timeout)
    payload = {
        "tool": name,
        "ok": result.ok,
        "code": result.code,
        "stdout": result.out.strip(),
        "stderr": result.err.strip(),
        "description": description,
    }
    parsed = _json(result.out)
    if parsed is not None:
        payload["json"] = parsed
    return payload


def _json(text: str) -> Any:
    text = (text or "").strip()
    if not text or text[0] not in "[{":
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def status() -> dict[str, Any]:
    """Snapshot of battery/wifi/telephony plus tool availability."""
    snapshot: dict[str, Any] = {
        "termux_api": bool(available()),
        "tools": [tool.to_dict() for tool in tools()],
        "data": {},
    }
    if not snapshot["termux_api"]:
        snapshot["hint"] = "pkg install termux-api  +  install the Termux:API app"
        return snapshot
    for name in QUICK:
        result = call(name, timeout=15)
        snapshot["data"][name] = result.get("json") or result.get("stdout") or result.get("stderr")
    return snapshot


def describe(name: str) -> str:
    return TOOLS.get(name, ("", "unknown tool"))[1]
