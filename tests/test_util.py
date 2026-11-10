from __future__ import annotations

from pathlib import Path

import pytest

from plx import util


def test_run_captures_output():
    result = util.run(["printf", "hello"])
    assert result.ok and result.out == "hello" and result.code == 0


def test_run_string_command_is_split():
    assert util.run("echo  two").out.strip() == "two"


def test_run_missing_binary():
    result = util.run(["definitely-not-a-real-binary-xyz"])
    assert result.code == 127 and "not found" in result.err


def test_run_check_raises():
    with pytest.raises(util.CommandError) as excinfo:
        util.run(["false"], check=True)
    assert excinfo.value.result.code == 1


def test_run_timeout():
    result = util.run(["sleep", "5"], timeout=0.2)
    assert result.code == 124


def test_run_shell_pipes():
    result = util.run_shell("printf 'a\\nb\\n' | wc -l")
    assert result.ok and result.out.strip() == "2"


def test_human_bytes():
    assert util.human_bytes(0) == "0 B"
    assert util.human_bytes(1024) == "1.0 KiB"
    assert util.human_bytes(1536) == "1.5 KiB"
    assert util.human_bytes(3 * 1024**3) == "3.0 GiB"
    assert util.human_bytes(None) == "?"


def test_human_duration():
    assert util.human_duration(5) == "5s"
    assert util.human_duration(65) == "1m 5s"
    assert util.human_duration(3725) == "1h 2m"
    assert util.human_duration(90000) == "1d 1h"


def test_atomic_write_and_read(tmp_path: Path):
    target = tmp_path / "nested" / "file.txt"
    util.atomic_write(target, "content", mode=0o600)
    assert target.read_text() == "content"
    assert (target.stat().st_mode & 0o777) == 0o600
    assert not list(target.parent.glob(".file.txt.tmp*"))


def test_read_text_default(tmp_path: Path):
    assert util.read_text(tmp_path / "missing") == ""
    assert util.read_text(tmp_path / "missing", "fallback") == "fallback"


def test_parse_getprop():
    text = "[ro.product.model]: [Pixel 7]\n[ro.build.version.sdk]: [35]\n\n[broken line\n"
    props = util.parse_getprop(text)
    assert props["ro.product.model"] == "Pixel 7"
    assert props["ro.build.version.sdk"] == "35"
    assert "broken line" not in props


def test_parse_kv():
    data = util.parse_kv("# comment\na: 1\nb = two\n\nnoise\n")
    assert data == {"a": "1", "b": "two"}


def test_tail_lines(tmp_path: Path):
    log = tmp_path / "big.log"
    log.write_text("\n".join(f"line-{index}" for index in range(5000)) + "\n")
    lines = util.tail_lines(log, 3)
    assert lines == ["line-4997", "line-4998", "line-4999"]
    assert util.tail_lines(tmp_path / "nope", 3) == []


def test_sha256_file(tmp_path: Path):
    target = tmp_path / "data"
    target.write_bytes(b"abc")
    assert util.sha256_file(target) == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_unique_preserves_order():
    assert util.unique([3, 1, 3, 2, 1]) == [3, 1, 2]


def test_meminfo_has_memtotal():
    info = util.meminfo()
    assert isinstance(info, dict)
    if info:
        assert info["MemTotal"] > 0
