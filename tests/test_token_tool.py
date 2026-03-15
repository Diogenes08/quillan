"""Tests for quillan.token_tool — estimation and trimming."""

from __future__ import annotations


from quillan.token_tool import estimate_tokens, estimate_tokens_file, trim_to_tokens, trim_file_to_tokens


def test_estimate_tokens_empty():
    assert estimate_tokens("") == 0


def test_estimate_tokens_nonempty():
    n = estimate_tokens("Hello world")
    assert n > 0


def test_estimate_tokens_scaling():
    short = estimate_tokens("Hello")
    long = estimate_tokens("Hello " * 100)
    assert long > short


def test_estimate_tokens_file(tmp_path):
    p = tmp_path / "test.txt"
    p.write_text("Hello world this is a test")
    n = estimate_tokens_file(p)
    assert n > 0


def test_estimate_tokens_file_missing(tmp_path):
    assert estimate_tokens_file(tmp_path / "missing.txt") == 0


def test_trim_to_tokens_no_trim_needed():
    text = "Hello world"
    result = trim_to_tokens(text, 1000)
    assert result == text


def test_trim_to_tokens_zero_limit():
    text = "Hello world"
    result = trim_to_tokens(text, 0)
    assert result == text  # disabled


def test_trim_to_tokens_inserts_marker():
    text = "A" * 10000
    result = trim_to_tokens(text, 50)
    assert "[...middle trimmed...]" in result


def test_trim_to_tokens_result_shorter():
    text = "Hello " * 1000
    trimmed = trim_to_tokens(text, 20)
    assert len(trimmed) < len(text)
    assert estimate_tokens(trimmed) <= 20 + 10  # allow small overage for marker


def test_trim_to_tokens_60_40_split():
    """Head should be ~60% of the token budget."""
    # Create distinctive head and tail content
    head_content = "H" * 5000
    tail_content = "T" * 5000
    text = head_content + "M" * 10000 + tail_content

    result = trim_to_tokens(text, 100)
    assert "[...middle trimmed...]" in result
    # Head comes first, tail comes last
    marker_pos = result.index("[...middle trimmed...]")
    head_part = result[:marker_pos]
    tail_part = result[marker_pos + len("[...middle trimmed...]"):]

    # Both head and tail should be present
    assert "H" in head_part
    assert "T" in tail_part


def test_trim_file_to_tokens(tmp_path):
    p = tmp_path / "big.txt"
    p.write_text("Word " * 2000)
    trim_file_to_tokens(p, 50)
    new_text = p.read_text()
    assert "[...middle trimmed...]" in new_text
    assert estimate_tokens(new_text) < 2000 * 1.3


def test_trim_file_to_tokens_no_change_if_fits(tmp_path):
    p = tmp_path / "small.txt"
    original = "Hello world"
    p.write_text(original)
    trim_file_to_tokens(p, 10000)
    assert p.read_text() == original


def test_trim_file_to_tokens_missing(tmp_path):
    trim_file_to_tokens(tmp_path / "missing.txt", 100)  # No raise


# ── heuristic fallback (tiktoken absent) ─────────────────────────────────────

def test_heuristic_floor_for_spaceless_text():
    """Without tiktoken, long spaceless text gets a char-based token estimate.

    Without the floor, "AAAA..." * 10000 splits to 1 "word" → 1 token,
    which would prevent trim_to_tokens from ever trimming it.
    """
    import quillan.token_tool as _tt
    from unittest.mock import patch

    text = "A" * 10000  # 0 spaces → 1 word → 1*1.3 ≈ 1 token without floor
    with patch.object(_tt, "_TIKTOKEN_AVAILABLE", False):
        n = _tt.estimate_tokens(text)
    # Floor: len(text) // 4 = 2500
    assert n >= 10000 // 4, f"Expected >= 2500, got {n}"


def test_heuristic_trims_spaceless_text():
    """Without tiktoken, trim_to_tokens still trims long spaceless strings."""
    import quillan.token_tool as _tt
    from unittest.mock import patch

    text = "A" * 10000
    with patch.object(_tt, "_TIKTOKEN_AVAILABLE", False):
        result = _tt.trim_to_tokens(text, 50)
    assert "[...middle trimmed...]" in result, "Spaceless text was not trimmed"
