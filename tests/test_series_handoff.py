"""Tests for series_handoff: register_and_get_prior_story + build_prior_story_section."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from quillan.paths import Paths
from quillan.structure.series_handoff import (
    build_prior_story_section,
    register_and_get_prior_story,
)


@pytest.fixture
def p(tmp_path: Path) -> Paths:
    return Paths(tmp_path / "data")


W, C, S = "world", "canon", "series"


# ── register_and_get_prior_story ─────────────────────────────────────────────


def test_register_first_story_creates_file(p: Paths) -> None:
    prior = register_and_get_prior_story(p, W, C, S, "book1")
    assert prior is None
    order_path = p.series_order(W, C, S)
    assert order_path.exists()
    data = yaml.safe_load(order_path.read_text(encoding="utf-8"))
    assert data == {"stories": ["book1"]}


def test_register_second_story_appends(p: Paths) -> None:
    register_and_get_prior_story(p, W, C, S, "book1")
    prior = register_and_get_prior_story(p, W, C, S, "book2")
    assert prior == "book1"
    data = yaml.safe_load(p.series_order(W, C, S).read_text(encoding="utf-8"))
    assert data["stories"] == ["book1", "book2"]


def test_register_idempotent(p: Paths) -> None:
    register_and_get_prior_story(p, W, C, S, "book1")
    register_and_get_prior_story(p, W, C, S, "book2")
    # Register book2 again — should not duplicate
    prior = register_and_get_prior_story(p, W, C, S, "book2")
    assert prior == "book1"
    data = yaml.safe_load(p.series_order(W, C, S).read_text(encoding="utf-8"))
    assert data["stories"].count("book2") == 1


def test_register_preserves_manual_order(p: Paths) -> None:
    # Hand-write a custom order
    order_path = p.series_order(W, C, S)
    p.ensure(order_path)
    order_path.write_text(
        yaml.dump({"stories": ["prequel", "book1", "book2"]}), encoding="utf-8"
    )
    # Registering book2 should respect existing order
    prior = register_and_get_prior_story(p, W, C, S, "book2")
    assert prior == "book1"
    data = yaml.safe_load(order_path.read_text(encoding="utf-8"))
    # No duplication or reordering
    assert data["stories"] == ["prequel", "book1", "book2"]


def test_prior_none_for_only_story(p: Paths) -> None:
    prior = register_and_get_prior_story(p, W, C, S, "solo")
    assert prior is None


def test_prior_returns_predecessor(p: Paths) -> None:
    for name in ("book1", "book2", "book3"):
        register_and_get_prior_story(p, W, C, S, name)
    prior = register_and_get_prior_story(p, W, C, S, "book3")
    assert prior == "book2"


# ── build_prior_story_section ─────────────────────────────────────────────────


def test_build_section_empty_when_no_artefacts(p: Paths) -> None:
    section = build_prior_story_section(p, W, C, S, "book1")
    assert section == ""


def test_build_section_includes_state_snapshot(p: Paths) -> None:
    state_path = p.state_current(W, C, S, "book1")
    p.ensure(state_path)
    state_path.write_text(
        yaml.dump({"characters": {"alice": "alive"}, "world_state": {"war": True}}),
        encoding="utf-8",
    )
    section = build_prior_story_section(p, W, C, S, "book1")
    assert "## Prior Story: book1" in section
    assert "### Final State Snapshot" in section
    assert "alice" in section


def test_build_section_meta_keys_excluded(p: Paths) -> None:
    state_path = p.state_current(W, C, S, "book1")
    p.ensure(state_path)
    state_path.write_text(
        yaml.dump({
            "characters": {"alice": "alive"},
            "_meta": {"version": 1},
            "_locked": ["alice"],
        }),
        encoding="utf-8",
    )
    section = build_prior_story_section(p, W, C, S, "book1")
    assert "_meta" not in section
    assert "_locked" not in section
    assert "alice" in section


def test_build_section_includes_summary(p: Paths) -> None:
    summary_path = p.continuity_summary(W, C, S, "book1")
    p.ensure(summary_path)
    summary_path.write_text("Alice defeated the dragon.\n", encoding="utf-8")
    section = build_prior_story_section(p, W, C, S, "book1")
    assert "### Narrative Summary" in section
    assert "Alice defeated the dragon." in section


def test_build_section_caps_long_summary(p: Paths) -> None:
    summary_path = p.continuity_summary(W, C, S, "book1")
    p.ensure(summary_path)
    long_text = "x" * 5000
    summary_path.write_text(long_text, encoding="utf-8")
    section = build_prior_story_section(p, W, C, S, "book1")
    # Section should not contain more than _SUMMARY_CAP x's (3000)
    assert section.count("x") <= 3000
