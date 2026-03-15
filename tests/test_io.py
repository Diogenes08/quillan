"""Tests for quillan.io — atomic writes, cap, prune."""

from __future__ import annotations

import time

import pytest

from quillan.io import atomic_write, atomic_write_from, cap_file_chars, prune_old_tmp, mktemp


def test_atomic_write_creates_file(tmp_path):
    p = tmp_path / "out.txt"
    atomic_write(p, "hello")
    assert p.read_text() == "hello"


def test_atomic_write_bytes(tmp_path):
    p = tmp_path / "out.bin"
    atomic_write(p, b"\x00\x01\x02")
    assert p.read_bytes() == b"\x00\x01\x02"


def test_atomic_write_creates_parent(tmp_path):
    p = tmp_path / "a" / "b" / "c.txt"
    atomic_write(p, "nested")
    assert p.exists()
    assert p.read_text() == "nested"


def test_atomic_write_overwrites(tmp_path):
    p = tmp_path / "f.txt"
    atomic_write(p, "first")
    atomic_write(p, "second")
    assert p.read_text() == "second"


def test_atomic_write_size_cap(tmp_path):
    p = tmp_path / "big.txt"
    with pytest.raises(ValueError, match="10 MiB"):
        atomic_write(p, "x" * (10 * 1024 * 1024 + 1))


def test_atomic_write_from(tmp_path):
    src = tmp_path / "src.txt"
    src.write_text("source content")
    dest = tmp_path / "sub" / "dest.txt"
    atomic_write_from(dest, src)
    assert dest.read_text() == "source content"


def test_mktemp_creates_file(tmp_path):
    p = mktemp(dir=tmp_path)
    assert p.exists()
    assert p.is_file()


def test_cap_file_chars_no_change(tmp_path):
    p = tmp_path / "small.txt"
    text = "Short text"
    p.write_text(text)
    cap_file_chars(p, 100)
    assert p.read_text() == text


def test_cap_file_chars_trims(tmp_path):
    p = tmp_path / "long.txt"
    # 60 A's + 40 B's = 100 chars
    text = "A" * 60 + "B" * 40
    p.write_text(text)
    cap_file_chars(p, 50)
    result = p.read_text()
    assert "[...middle trimmed...]" in result
    assert len(result) < len(text)


def test_cap_file_chars_60_40_split(tmp_path):
    """Head should be ~60% of budget, tail ~40%."""
    p = tmp_path / "split.txt"
    # Create distinctive head/tail
    head_marker = "H" * 1000
    middle = "M" * 5000
    tail_marker = "T" * 1000
    text = head_marker + middle + tail_marker
    p.write_text(text)

    cap_file_chars(p, 200)
    result = p.read_text()

    # Should have head content and tail content
    assert result.startswith("H")
    assert result.endswith("T")
    assert "[...middle trimmed...]" in result


def test_cap_file_chars_missing_file(tmp_path):
    """cap_file_chars is a no-op for missing files."""
    p = tmp_path / "nonexistent.txt"
    cap_file_chars(p, 100)  # Should not raise


def test_prune_old_tmp(tmp_path):
    old_file = tmp_path / "old.txt"
    new_file = tmp_path / "new.txt"

    old_file.write_text("old")
    new_file.write_text("new")

    # Make old_file appear old
    old_time = time.time() - 48 * 3600  # 48 hours ago
    import os
    os.utime(old_file, (old_time, old_time))

    prune_old_tmp(tmp_path, ttl_hours=24)

    assert not old_file.exists()
    assert new_file.exists()


def test_prune_old_tmp_missing_dir(tmp_path):
    """prune_old_tmp is a no-op for missing directories."""
    prune_old_tmp(tmp_path / "nonexistent", ttl_hours=1)  # Should not raise
