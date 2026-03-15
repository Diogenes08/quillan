"""Tests for stale draft detection: _find_stale_beats() and draft --stale-only."""

from __future__ import annotations

import time
import json
import yaml
import pytest

from quillan.cli import _find_stale_beats


# ── shared helpers ────────────────────────────────────────────────────────────


def _make_llm_and_telemetry(settings, paths):
    from quillan.llm import LLMClient
    from quillan.telemetry import Telemetry
    telemetry = Telemetry(paths.runs_dir(), enabled=False)
    llm = LLMClient(settings, telemetry, cache_dir=settings.cache_dir)
    return llm, telemetry


def _write_stub_outline(paths, world, canon, series, story, beat_ids: list[str]) -> None:
    beats = [
        {"beat_id": bid, "title": f"Beat {bid}", "goal": "test", "characters": []}
        for bid in beat_ids
    ]
    outline = {
        "title": "Stale Test Story",
        "genre": "Fiction",
        "theme": "TBD",
        "chapters": [{"chapter": 1, "title": "Act 1", "beats": beats}],
    }
    p = paths.outline(world, canon, series, story)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.dump(outline))


def _write_dep_map(paths, world, canon, series, story, deps: dict) -> None:
    paths.dependency_map(world, canon, series, story).write_text(
        json.dumps({"dependencies": deps})
    )


def _setup_draft_story(
    paths, world, canon, series, story,
    beat_ids: list[str],
    deps: dict,
) -> None:
    """Minimal fixture: dirs + outline + specs + dep_map."""
    for d in [
        paths.story_input(world, canon, series, story),
        paths.story_planning(world, canon, series, story),
        paths.story_structure(world, canon, series, story),
        paths.story_beats(world, canon, series, story),
        paths.story_state(world, canon, series, story),
        paths.story_continuity(world, canon, series, story),
        paths.queue_dir(world, canon, series, story),
    ]:
        d.mkdir(parents=True, exist_ok=True)

    _write_stub_outline(paths, world, canon, series, story, beat_ids)
    _write_dep_map(paths, world, canon, series, story, deps)

    for bid in beat_ids:
        spec_path = paths.beat_spec(world, canon, series, story, bid)
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(yaml.dump({
            "beat_id": bid, "title": f"Beat {bid}", "goal": "test",
            "word_count_target": 100, "scope": [], "out_of_scope": [],
            "rules": [], "tone": "neutral",
        }))


# ── unit tests for _find_stale_beats() ────────────────────────────────────────


def test_find_stale_beats_empty(paths, world, canon, series, story):
    """Empty beat_ids list returns empty list."""
    result = _find_stale_beats(paths, world, canon, series, story, [])
    assert result == []


def test_find_stale_beats_no_draft(paths, world, canon, series, story):
    """Spec exists but no draft → beat is NOT stale (just unwritten)."""
    bid = "C1-S1-B1"
    spec_path = paths.beat_spec(world, canon, series, story, bid)
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(f"beat_id: {bid}\n")

    result = _find_stale_beats(paths, world, canon, series, story, [bid])
    assert result == []


def test_find_stale_beats_fresh_draft(paths, world, canon, series, story):
    """Draft is newer than spec → beat is NOT stale."""
    bid = "C1-S1-B1"
    spec_path = paths.beat_spec(world, canon, series, story, bid)
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(f"beat_id: {bid}\n")

    time.sleep(0.01)  # ensure draft mtime > spec mtime

    draft_path = paths.beat_draft(world, canon, series, story, bid)
    draft_path.write_text("# Draft\n\nFresh prose.\n")

    result = _find_stale_beats(paths, world, canon, series, story, [bid])
    assert result == []


def test_find_stale_beats_stale_draft(paths, world, canon, series, story):
    """Spec is newer than draft → beat IS stale."""
    bid = "C1-S1-B1"
    spec_path = paths.beat_spec(world, canon, series, story, bid)
    spec_path.parent.mkdir(parents=True, exist_ok=True)

    draft_path = paths.beat_draft(world, canon, series, story, bid)
    draft_path.write_text("# Draft\n\nOld prose.\n")

    time.sleep(0.01)  # ensure spec mtime > draft mtime

    spec_path.write_text(f"beat_id: {bid}\n")

    result = _find_stale_beats(paths, world, canon, series, story, [bid])
    assert result == [bid]


def test_find_stale_beats_mixed(paths, world, canon, series, story):
    """Mix of fresh/stale/undrafted — only stale beat returned."""
    bid_stale = "C1-S1-B1"
    bid_fresh = "C1-S1-B2"
    bid_nodraft = "C1-S1-B3"

    for bid in [bid_stale, bid_fresh, bid_nodraft]:
        spec_path = paths.beat_spec(world, canon, series, story, bid)
        spec_path.parent.mkdir(parents=True, exist_ok=True)

    # Write draft for stale beat first, then update spec
    draft_path = paths.beat_draft(world, canon, series, story, bid_stale)
    draft_path.write_text("# Old draft\n")
    time.sleep(0.01)
    paths.beat_spec(world, canon, series, story, bid_stale).write_text(f"beat_id: {bid_stale}\n")

    # Write spec for fresh beat first, then write draft
    paths.beat_spec(world, canon, series, story, bid_fresh).write_text(f"beat_id: {bid_fresh}\n")
    time.sleep(0.01)
    draft_path2 = paths.beat_draft(world, canon, series, story, bid_fresh)
    draft_path2.write_text("# Fresh draft\n")

    # No draft for bid_nodraft
    paths.beat_spec(world, canon, series, story, bid_nodraft).write_text(f"beat_id: {bid_nodraft}\n")

    result = _find_stale_beats(
        paths, world, canon, series, story,
        [bid_stale, bid_fresh, bid_nodraft],
    )
    assert result == [bid_stale]


def test_find_stale_beats_returns_sorted(paths, world, canon, series, story):
    """Output is always sorted regardless of input order."""
    beat_ids = ["C1-S1-B3", "C1-S1-B1", "C1-S1-B2"]

    for bid in beat_ids:
        spec_path = paths.beat_spec(world, canon, series, story, bid)
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        # Write draft first, then spec → all stale
        draft_path = paths.beat_draft(world, canon, series, story, bid)
        draft_path.write_text(f"# Old draft {bid}\n")
        time.sleep(0.01)
        spec_path.write_text(f"beat_id: {bid}\n")

    result = _find_stale_beats(paths, world, canon, series, story, beat_ids)
    assert result == sorted(beat_ids)
    assert result == ["C1-S1-B1", "C1-S1-B2", "C1-S1-B3"]


# ── integration tests via draft_story() ───────────────────────────────────────


@pytest.mark.asyncio
async def test_draft_stale_only_redrafts_stale(paths, settings, world, canon, series, story):
    """--stale-only: stale draft is overwritten; fresh draft untouched."""
    from quillan.pipeline.runner import draft_story

    beat_ids = ["C1-S1-B1", "C1-S1-B2"]
    deps = {"C1-S1-B1": [], "C1-S1-B2": []}
    _setup_draft_story(paths, world, canon, series, story, beat_ids, deps)

    # Write drafts for both beats
    for bid in beat_ids:
        dp = paths.beat_draft(world, canon, series, story, bid)
        dp.parent.mkdir(parents=True, exist_ok=True)
        dp.write_text(f"ORIGINAL_{bid}\n")

    # Make B1 stale: touch its spec after the draft
    time.sleep(0.01)
    paths.beat_spec(world, canon, series, story, "C1-S1-B1").write_text(
        yaml.dump({
            "beat_id": "C1-S1-B1", "title": "Beat C1-S1-B1 updated", "goal": "test",
            "word_count_target": 100, "scope": [], "out_of_scope": [],
            "rules": [], "tone": "neutral",
        })
    )

    stale = _find_stale_beats(paths, world, canon, series, story, beat_ids)
    assert stale == ["C1-S1-B1"]

    llm, telemetry = _make_llm_and_telemetry(settings, paths)
    await draft_story(
        paths, world, canon, series, story,
        beats_mode="all",
        settings=settings, llm=llm, telemetry=telemetry,
        force=True,
        explicit_beats=stale,
    )

    # B1 was re-drafted
    b1_text = paths.beat_draft(world, canon, series, story, "C1-S1-B1").read_text()
    assert "ORIGINAL_C1-S1-B1" not in b1_text

    # B2 was untouched
    b2_text = paths.beat_draft(world, canon, series, story, "C1-S1-B2").read_text()
    assert "ORIGINAL_C1-S1-B2" in b2_text


@pytest.mark.asyncio
async def test_draft_stale_only_no_stale_is_noop(paths, settings, world, canon, series, story):
    """When all drafts are fresh, stale set is empty → no drafting occurs."""
    from quillan.pipeline.runner import draft_story

    beat_ids = ["C1-S1-B1", "C1-S1-B2"]
    deps = {"C1-S1-B1": [], "C1-S1-B2": []}
    _setup_draft_story(paths, world, canon, series, story, beat_ids, deps)

    # Write specs first, then drafts → all fresh
    for bid in beat_ids:
        time.sleep(0.01)
        dp = paths.beat_draft(world, canon, series, story, bid)
        dp.parent.mkdir(parents=True, exist_ok=True)
        dp.write_text(f"FRESH_{bid}\n")

    stale = _find_stale_beats(paths, world, canon, series, story, beat_ids)
    assert stale == []

    # Confirm: calling draft_story with explicit_beats=[] does nothing
    llm, telemetry = _make_llm_and_telemetry(settings, paths)
    await draft_story(
        paths, world, canon, series, story,
        beats_mode="all",
        settings=settings, llm=llm, telemetry=telemetry,
        force=True,
        explicit_beats=[],
    )

    # Originals untouched
    for bid in beat_ids:
        assert f"FRESH_{bid}" in paths.beat_draft(world, canon, series, story, bid).read_text()


@pytest.mark.asyncio
async def test_draft_stale_only_with_cascade(paths, settings, world, canon, series, story):
    """--stale-only + --cascade: stale beats are the BFS seed; dependents included."""
    from quillan.pipeline.runner import draft_story
    from quillan.pipeline.dag import compute_dependents
    from quillan.validate import validate_dependency_map

    beat_ids = ["C1-S1-B1", "C1-S1-B2", "C1-S1-B3"]
    deps = {
        "C1-S1-B1": [],
        "C1-S1-B2": ["C1-S1-B1"],
        "C1-S1-B3": ["C1-S1-B2"],
    }
    _setup_draft_story(paths, world, canon, series, story, beat_ids, deps)

    # Write drafts for all beats
    for bid in beat_ids:
        dp = paths.beat_draft(world, canon, series, story, bid)
        dp.parent.mkdir(parents=True, exist_ok=True)
        dp.write_text(f"ORIGINAL_{bid}\n")

    # Make only B1 stale
    time.sleep(0.01)
    paths.beat_spec(world, canon, series, story, "C1-S1-B1").write_text(
        yaml.dump({
            "beat_id": "C1-S1-B1", "title": "B1 updated", "goal": "test",
            "word_count_target": 100, "scope": [], "out_of_scope": [],
            "rules": [], "tone": "neutral",
        })
    )

    stale = _find_stale_beats(paths, world, canon, series, story, beat_ids)
    assert stale == ["C1-S1-B1"]

    # Expand stale set via cascade (B1 → B2 → B3)
    dep_map_data = validate_dependency_map(paths.dependency_map(world, canon, series, story))
    cascade_beats = compute_dependents(dep_map_data, stale)
    assert set(cascade_beats) == {"C1-S1-B1", "C1-S1-B2", "C1-S1-B3"}

    llm, telemetry = _make_llm_and_telemetry(settings, paths)
    await draft_story(
        paths, world, canon, series, story,
        beats_mode="all",
        settings=settings, llm=llm, telemetry=telemetry,
        force=True,
        explicit_beats=cascade_beats,
    )

    # All three beats were re-drafted
    for bid in beat_ids:
        text = paths.beat_draft(world, canon, series, story, bid).read_text()
        assert f"ORIGINAL_{bid}" not in text, f"{bid} should have been re-drafted"
