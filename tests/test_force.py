"""Tests for draft --force flag and the default skip-existing-draft behaviour."""

from __future__ import annotations

import json
import pytest
import yaml


# ── fixtures / helpers ────────────────────────────────────────────────────────

def _setup_minimal_story(paths, world, canon, series, story, beat_ids: list[str]) -> None:
    """Create the minimum filesystem layout for draft_story to run offline."""
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

    # Dependency map — linear chain
    dep_map = {"dependencies": {bid: ([beat_ids[i - 1]] if i else [])
                                for i, bid in enumerate(beat_ids)}}
    paths.dependency_map(world, canon, series, story).write_text(json.dumps(dep_map))

    # Minimal beat spec for each beat
    for bid in beat_ids:
        spec_path = paths.beat_spec(world, canon, series, story, bid)
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(yaml.dump({
            "beat_id": bid, "title": f"Beat {bid}", "goal": "test",
            "word_count_target": 100, "scope": [], "out_of_scope": [],
            "rules": [], "tone": "neutral",
        }))


def _make_llm_and_telemetry(settings, paths):
    from quillan.llm import LLMClient
    from quillan.telemetry import Telemetry
    telemetry = Telemetry(paths.runs_dir(), enabled=False)
    llm = LLMClient(settings, telemetry, cache_dir=settings.cache_dir)
    return llm, telemetry


# ── default skip behaviour ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_draft_skips_existing_draft_by_default(paths, settings, world, canon, series, story):
    """Without --force, a beat with an existing draft is not re-written."""
    beat_ids = ["C1-S1-B1"]
    _setup_minimal_story(paths, world, canon, series, story, beat_ids)

    # Pre-write a draft with a known marker
    draft_path = paths.beat_draft(world, canon, series, story, "C1-S1-B1")
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text("ORIGINAL DRAFT MARKER\n")

    llm, telemetry = _make_llm_and_telemetry(settings, paths)

    from quillan.pipeline.runner import draft_story
    await draft_story(
        paths, world, canon, series, story, "all", settings, llm, telemetry,
        force=False,
    )

    # Draft must still contain the original marker — was not overwritten
    assert "ORIGINAL DRAFT MARKER" in draft_path.read_text()


@pytest.mark.asyncio
async def test_draft_force_overwrites_existing_draft(paths, settings, world, canon, series, story):
    """With force=True, an existing draft is replaced by the new stub."""
    beat_ids = ["C1-S1-B1"]
    _setup_minimal_story(paths, world, canon, series, story, beat_ids)

    draft_path = paths.beat_draft(world, canon, series, story, "C1-S1-B1")
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text("ORIGINAL DRAFT MARKER\n")

    llm, telemetry = _make_llm_and_telemetry(settings, paths)

    from quillan.pipeline.runner import draft_story
    await draft_story(
        paths, world, canon, series, story, "all", settings, llm, telemetry,
        force=True,
    )

    content = draft_path.read_text()
    # Original marker was overwritten by the offline stub
    assert "ORIGINAL DRAFT MARKER" not in content
    assert "C1-S1-B1" in content   # offline stub includes the beat ID


@pytest.mark.asyncio
async def test_draft_writes_new_draft_without_force(paths, settings, world, canon, series, story):
    """Without --force, a beat with no existing draft is written normally."""
    beat_ids = ["C1-S1-B1"]
    _setup_minimal_story(paths, world, canon, series, story, beat_ids)

    draft_path = paths.beat_draft(world, canon, series, story, "C1-S1-B1")
    assert not draft_path.exists()

    llm, telemetry = _make_llm_and_telemetry(settings, paths)

    from quillan.pipeline.runner import draft_story
    await draft_story(
        paths, world, canon, series, story, "all", settings, llm, telemetry,
        force=False,
    )

    assert draft_path.exists()
    assert "C1-S1-B1" in draft_path.read_text()


@pytest.mark.asyncio
async def test_draft_force_false_partial_skip(paths, settings, world, canon, series, story):
    """With force=False, drafted beats are skipped and un-drafted beats are written."""
    beat_ids = ["C1-S1-B1", "C1-S1-B2"]
    _setup_minimal_story(paths, world, canon, series, story, beat_ids)

    # B1 already drafted, B2 not yet
    b1_draft = paths.beat_draft(world, canon, series, story, "C1-S1-B1")
    b1_draft.parent.mkdir(parents=True, exist_ok=True)
    b1_draft.write_text("B1 ORIGINAL\n")

    b2_draft = paths.beat_draft(world, canon, series, story, "C1-S1-B2")

    llm, telemetry = _make_llm_and_telemetry(settings, paths)

    from quillan.pipeline.runner import draft_story
    await draft_story(
        paths, world, canon, series, story, "all", settings, llm, telemetry,
        force=False,
    )

    assert "B1 ORIGINAL" in b1_draft.read_text()   # B1 untouched
    assert b2_draft.exists()                        # B2 was drafted
    assert "C1-S1-B2" in b2_draft.read_text()
