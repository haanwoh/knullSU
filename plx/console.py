"""Terminal presentation layer.

Every command funnels its output through this module so that ``--json``,
``--quiet`` and ``--no-color`` behave identically everywhere, and so the
output stays readable on a 60-column phone terminal.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from collections.abc import Iterable, Sequence
from typing import Any

RESET = "\033[0m"
STYLES = {
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "grey": "\033[90m",
}

_STATE: dict[str, Any] = {"json": False, "quiet": False, "color": None}


def configure(
    *,
    json_mode: bool = False,
    quiet: bool = False,
    color: bool | None = None,
) -> None:
    _STATE["json"] = json_mode
    _STATE["quiet"] = quiet
    _STATE["color"] = color


def json_mode() -> bool:
    return bool(_STATE["json"])


def quiet() -> bool:
    return bool(_STATE["quiet"])


def color_enabled() -> bool:
    override = _STATE["color"]
    if override is not None:
        return bool(override) and not json_mode()
    if json_mode() or os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    return sys.stdout.isatty()


def paint(text: str, *styles: str) -> str:
    if not color_enabled():
        return text
    prefix = "".join(STYLES.get(style, "") for style in styles)
    return f"{prefix}{text}{RESET}" if prefix else text


def width() -> int:
    try:
        return max(40, min(shutil.get_terminal_size((80, 24)).columns, 110))
    except OSError:  # pragma: no cover - defensive
        return 80


def out(message: str = "") -> None:
    if quiet() or json_mode():
        return
    print(message)


def info(message: str) -> None:
    out(message)


def muted(message: str) -> None:
    out(paint(message, "grey"))


def ok(message: str) -> None:
    out(f"{paint('✓', 'green')} {message}")


def warn(message: str) -> None:
    out(f"{paint('!', 'yellow')} {message}")


def err(message: str) -> None:
    stream = sys.stderr
    if json_mode():
        return
    print(f"{paint('✗', 'red')} {message}", file=stream)


def step(message: str) -> None:
    out(f"{paint('▸', 'cyan')} {message}")


def header(message: str) -> None:
    out()
    out(paint(message, "bold"))


def json_out(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True, default=str))


def hr(char: str = "─") -> None:
    out(paint(char * width(), "grey"))


def _strip_ansi(text: str) -> str:
    out_chars = []
    index = 0
    while index < len(text):
        if text[index] == "\033":
            end = text.find("m", index)
            if end == -1:
                break
            index = end + 1
            continue
        out_chars.append(text[index])
        index += 1
    return "".join(out_chars)


def table(
    headers: Sequence[str],
    rows: Iterable[Sequence[Any]],
    *,
    aligns: Sequence[str] | None = None,
) -> None:
    """Render an aligned text table that survives narrow terminals."""
    materialised = [[" ".join(str(cell).split()) for cell in row] for row in rows]
    if not materialised:
        muted("(nothing to show)")
        return
    columns = len(headers)
    widths = [len(_strip_ansi(str(head))) for head in headers]
    for row in materialised:
        for index in range(min(columns, len(row))):
            widths[index] = max(widths[index], len(_strip_ansi(row[index])))

    limit = width()
    while sum(widths) + 2 * (columns - 1) > limit and max(widths) > 8:
        widest = widths.index(max(widths))
        widths[widest] -= 1

    def cell(text: str, index: int) -> str:
        plain = _strip_ansi(text)
        if len(plain) > widths[index]:
            return plain[: max(1, widths[index] - 1)] + "…"
        align = (aligns or ["left"] * columns)[index]
        return text.rjust(widths[index]) if align == "right" else text.ljust(widths[index])

    out(paint("  ".join(cell(str(h), i) for i, h in enumerate(headers)), "bold"))
    out(paint("  ".join("─" * w for w in widths), "grey"))
    for row in materialised:
        padded = list(row) + [""] * (columns - len(row))
        out("  ".join(cell(padded[i], i) for i in range(columns)))


def kv_block(data: dict[str, Any], *, indent: str = "  ") -> None:
    if not data:
        muted("(empty)")
        return
    widest = max(len(str(key)) for key in data)
    for key, value in data.items():
        out(f"{indent}{paint(str(key).ljust(widest), 'cyan')}  {value}")


def box(title: str, lines: Sequence[str]) -> None:
    """Draw a simple bordered box (no box-drawing font requirements)."""
    content = [*lines]
    inner = min(
        width() - 4, max([len(title), *(len(_strip_ansi(line)) for line in content)] or [0])
    )
    out()
    out(paint(f"┌─ {title} " + "─" * max(0, inner - len(title) - 1), "grey"))
    for line in content:
        out(f"│ {line}")
    out(paint("└" + "─" * (inner + 2), "grey"))


def bullet_list(items: Iterable[str], marker: str = "•") -> None:
    for item in items:
        out(f"  {paint(marker, 'grey')} {item}")
