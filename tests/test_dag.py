"""Tests for quillan.pipeline.dag — topological sort and dependency expansion."""

from __future__ import annotations

import pytest

from quillan.pipeline.dag import compute_batches, compute_dependents, CycleError


def dep_map(*pairs) -> dict:
    """Helper: build dep_map from pairs (node, [deps...])."""
    return {"dependencies": dict(pairs)}


def test_empty():
    assert compute_batches({"dependencies": {}}) == []


def test_single_node():
    batches = compute_batches(dep_map(("A", [])))
    assert batches == [["A"]]


def test_two_independent():
    batches = compute_batches(dep_map(("A", []), ("B", [])))
    assert len(batches) == 1
    assert set(batches[0]) == {"A", "B"}


def test_linear_chain():
    batches = compute_batches(dep_map(("A", []), ("B", ["A"]), ("C", ["B"])))
    assert batches == [["A"], ["B"], ["C"]]


def test_diamond_pattern():
    """Diamond: A → B,C → D."""
    batches = compute_batches(
        dep_map(
            ("A", []),
            ("B", ["A"]),
            ("C", ["A"]),
            ("D", ["B", "C"]),
        )
    )
    assert batches[0] == ["A"]
    assert set(batches[1]) == {"B", "C"}
    assert batches[2] == ["D"]


def test_beat_id_format():
    """Real beat IDs (C1-S1-B1) sort correctly."""
    batches = compute_batches(
        dep_map(
            ("C1-S1-B1", []),
            ("C1-S1-B2", ["C1-S1-B1"]),
            ("C1-S1-B3", ["C1-S1-B1"]),
            ("C1-S1-B4", ["C1-S1-B2", "C1-S1-B3"]),
        )
    )
    assert batches[0] == ["C1-S1-B1"]
    assert set(batches[1]) == {"C1-S1-B2", "C1-S1-B3"}
    assert batches[2] == ["C1-S1-B4"]


def test_cycle_detected():
    with pytest.raises(CycleError):
        compute_batches(dep_map(("A", ["B"]), ("B", ["A"])))


def test_self_cycle():
    with pytest.raises(CycleError):
        compute_batches(dep_map(("A", ["A"])))


def test_unknown_dependency():
    with pytest.raises(ValueError, match="undeclared beat"):
        compute_batches(dep_map(("A", ["B"])))  # B not declared


def test_batches_sorted():
    """Within each batch, beat IDs are sorted for determinism."""
    batches = compute_batches(
        dep_map(("Z", []), ("A", []), ("M", []))
    )
    assert batches[0] == ["A", "M", "Z"]


def test_raw_dict_input():
    """compute_batches should also accept raw dependencies dict (no wrapper)."""
    raw = {"A": [], "B": ["A"]}
    batches = compute_batches(raw)
    assert batches == [["A"], ["B"]]


def test_complex_graph():
    """Multi-level dependency graph."""
    batches = compute_batches(
        dep_map(
            ("L1A", []),
            ("L1B", []),
            ("L2A", ["L1A"]),
            ("L2B", ["L1A", "L1B"]),
            ("L3A", ["L2A", "L2B"]),
        )
    )
    assert set(batches[0]) == {"L1A", "L1B"}
    assert set(batches[1]) == {"L2A", "L2B"}
    assert batches[2] == ["L3A"]


# ── compute_dependents tests ──────────────────────────────────────────────────

def test_compute_dependents_direct():
    """B depends on A → compute_dependents([A]) includes both A and B."""
    dm = dep_map(("A", []), ("B", ["A"]))
    result = compute_dependents(dm, ["A"])
    assert result == ["A", "B"]


def test_compute_dependents_transitive():
    """Linear chain A→B→C→D: compute_dependents([A]) returns all four."""
    raw = {"A": [], "B": ["A"], "C": ["B"], "D": ["C"]}
    result = compute_dependents(raw, ["A"])
    assert result == ["A", "B", "C", "D"]


def test_compute_dependents_diamond():
    """Diamond A→B, A→C, B→D, C→D: from [A] returns all four."""
    dm = dep_map(
        ("A", []),
        ("B", ["A"]),
        ("C", ["A"]),
        ("D", ["B", "C"]),
    )
    result = compute_dependents(dm, ["A"])
    assert result == ["A", "B", "C", "D"]


def test_compute_dependents_unknown_start():
    """Unknown start beat IDs are silently ignored, not an error."""
    dm = dep_map(("A", []), ("B", ["A"]))
    result = compute_dependents(dm, ["UNKNOWN", "A"])
    assert result == ["A", "B"]  # UNKNOWN silently dropped
