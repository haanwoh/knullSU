from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

from plx import console


def test_paint_respects_no_color():
    console.configure(color=False)
    assert console.paint("x", "bold") == "x"
    console.configure(color=True)
    assert "\033[1m" in console.paint("x", "bold")


def test_json_mode_disables_color():
    console.configure(json_mode=True, color=None)
    assert console.color_enabled() is False


def test_out_suppressed_when_quiet():
    console.configure(quiet=True)
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        console.out("hidden")
        console.ok("also hidden")
    assert buffer.getvalue() == ""


def test_table_collapses_newlines():
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        console.table(["service", "command"], [["web", "python3 -c 'a\nb'"]])
    rendered = buffer.getvalue()
    assert "service" in rendered and "web" in rendered
    assert "a b" in rendered
    assert rendered.count("\n") <= 4


def test_table_empty_rows():
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        console.table(["a"], [])
    assert "nothing to show" in buffer.getvalue()


def test_kv_block_aligns():
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        console.kv_block({"short": 1, "much-longer": 2})
    lines = buffer.getvalue().splitlines()
    assert len(lines) == 2
    assert "short" in lines[0] and "much-longer" in lines[1]


def test_json_out_roundtrip():
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        console.json_out({"b": 1, "a": [1, 2]})
    assert json.loads(buffer.getvalue()) == {"b": 1, "a": [1, 2]}


def test_box_and_bullets_smoke():
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        console.box("title", ["one", "two"])
        console.bullet_list(["item"])
    rendered = buffer.getvalue()
    assert "title" in rendered and "• item" in rendered


def test_width_is_bounded():
    assert 40 <= console.width() <= 110
