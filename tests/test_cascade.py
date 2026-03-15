"""Integration tests for --cascade flag on regen-specs and draft commands."""

from __future__ import annotations

import json
import yaml
import pytest


# ── shared helpers ────────────────────────────────────────────────────────────

class _FakeLLM:
    """Minimal LLM stub — forces offline/stub code paths."""
    class settings:
        has_api_keys = False


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
        "title": "Cascade Test Story",
        "genre": "Fiction",
        "theme": "TBD",
        "chapters": [{"chapter": 1, "title": "Act 1", "beats": beats}],
    }
    p = paths.outline(world, canon, series, story)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.dump(outline))


def _write_dep_map(paths, world, canon, series, story, deps: dict) -> None:
    """Write a custom dependency map dict."""
    paths.dependency_map(world, canon, series, story).write_text(
        json.dumps({"dependencies": deps})
    )


def _setup_regen_story(
    paths, world, canon, series, story,
    beat_ids: list[str],
    deps: dict,
) -> None:
    """Minimal fixture for regen-specs cascade tests: dirs + outline + spine + dep_map."""
    for d in [
        paths.story_input(world, canon, series, story),
        paths.story_planning(world, canon, series, story),
        paths.story_structure(world, canon, series, story),
        paths.story_beats(world, canon, series, story),
    ]:
        d.mkdir(parents=True, exist_ok=True)

    _write_stub_outline(paths, world, canon, series, story, beat_ids)
    _write_dep_map(paths, world, canon, series, story, deps)

    from quillan.structure.story_spine import _stub_spine
    from quillan.io import atomic_write
    spine_path = paths.story_spine(world, canon, series, story)
    spine_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(spine_path, yaml.dump(_stub_spine(beat_ids)))


def _setup_draft_story(
    paths, world, canon, series, story,
    beat_ids: list[str],
    deps: dict,
) -> None:
    """Minimal fixture for draft cascade tests: dirs + outline + specs + dep_map."""
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


# ── regen-specs --cascade tests ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_regen_cascade_expands_to_dependents(paths, world, canon, series, story):
    """--cascade from B1 in a B1→B2→B3 chain regenerates all three."""
    from quillan.structure.story import regen_beat_specs
    from quillan.pipeline.dag import compute_dependents
    from quillan.validate import validate_dependency_map

    beat_ids = ["C1-S1-B1", "C1-S1-B2", "C1-S1-B3"]
    deps = {
        "C1-S1-B1": [],
        "C1-S1-B2": ["C1-S1-B1"],
        "C1-S1-B3": ["C1-S1-B2"],
    }
    _setup_regen_story(paths, world, canon, series, story, beat_ids, deps)

    # Pre-write specs with sentinel
    for bid in beat_ids:
        spec_path = paths.beat_spec(world, canon, series, story, bid)
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(f"beat_id: {bid}\ntitle: OLD\n")

    # Simulate --cascade from B1
    dep_map_data = validate_dependency_map(paths.dependency_map(world, canon, series, story))
    cascade_beats = compute_dependents(dep_map_data, ["C1-S1-B1"])
    assert set(cascade_beats) == {"C1-S1-B1", "C1-S1-B2", "C1-S1-B3"}

    count = await regen_beat_specs(
        paths, world, canon, series, story, _FakeLLM(), beats=cascade_beats
    )

    assert count == 3
    for bid in beat_ids:
        spec_path = paths.beat_spec(world, canon, series, story, bid)
        assert "OLD" not in spec_path.read_text(), f"Spec for {bid} was not regenerated"


@pytest.mark.asyncio
async def test_regen_cascade_leaf_node(paths, world, canon, series, story):
    """Cascading from a leaf beat (no dependents) only touches that beat."""
    from quillan.structure.story import regen_beat_specs
    from quillan.pipeline.dag import compute_dependents
    from quillan.validate import validate_dependency_map

    beat_ids = ["C1-S1-B1", "C1-S1-B2", "C1-S1-B3"]
    deps = {
        "C1-S1-B1": [],
        "C1-S1-B2": ["C1-S1-B1"],
        "C1-S1-B3": ["C1-S1-B2"],  # B3 is the leaf
    }
    _setup_regen_story(paths, world, canon, series, story, beat_ids, deps)

    for bid in beat_ids:
        spec_path = paths.beat_spec(world, canon, series, story, bid)
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(f"beat_id: {bid}\ntitle: ORIGINAL\n")

    dep_map_data = validate_dependency_map(paths.dependency_map(world, canon, series, story))
    cascade_beats = compute_dependents(dep_map_data, ["C1-S1-B3"])

    # Leaf has no successors → only itself
    assert cascade_beats == ["C1-S1-B3"]

    count = await regen_beat_specs(
        paths, world, canon, series, story, _FakeLLM(), beats=cascade_beats
    )

    assert count == 1
    # B1 and B2 were not touched
    for bid in ["C1-S1-B1", "C1-S1-B2"]:
        assert "ORIGINAL" in paths.beat_spec(world, canon, series, story, bid).read_text()


@pytest.mark.asyncio
async def test_regen_cascade_all_is_noop(paths, world, canon, series, story):
    """--cascade with --beats all: beats is None so compute_dependents is not called.

    The regen_beat_specs call with beats=None regenerates everything,
    which is the same as the no-cascade result.
    """
    from quillan.structure.story import regen_beat_specs

    beat_ids = ["C1-S1-B1", "C1-S1-B2"]
    deps = {"C1-S1-B1": [], "C1-S1-B2": ["C1-S1-B1"]}
    _setup_regen_story(paths, world, canon, series, story, beat_ids, deps)

    for bid in beat_ids:
        spec_path = paths.beat_spec(world, canon, series, story, bid)
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(f"beat_id: {bid}\ntitle: OLD\n")

    # beats=None → regenerate all (cascade with "all" is a no-op per plan)
    count = await regen_beat_specs(
        paths, world, canon, series, story, _FakeLLM(), beats=None
    )

    assert count == len(beat_ids)
    for bid in beat_ids:
        assert "OLD" not in paths.beat_spec(world, canon, series, story, bid).read_text()


# ── draft --cascade tests ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_draft_cascade_redrafts_dependents(paths, settings, world, canon, series, story):
    """Cascade from B1 in B1→B2→B3 chain re-drafts all three; B4 (independent) untouched."""
    from quillan.pipeline.runner import draft_story
    from quillan.pipeline.dag import compute_dependents
    from quillan.validate import validate_dependency_map

    beat_ids = ["C1-S1-B1", "C1-S1-B2", "C1-S1-B3", "C1-S1-B4"]
    deps = {
        "C1-S1-B1": [],
        "C1-S1-B2": ["C1-S1-B1"],
        "C1-S1-B3": ["C1-S1-B2"],
        "C1-S1-B4": [],  # independent
    }
    _setup_draft_story(paths, world, canon, series, story, beat_ids, deps)

    # Pre-write drafts for all beats with sentinel markers
    for bid in beat_ids:
        draft_path = paths.beat_draft(world, canon, series, story, bid)
        draft_path.parent.mkdir(parents=True, exist_ok=True)
        draft_path.write_text(f"ORIGINAL_DRAFT_{bid}\n")

    # Simulate --cascade from B1
    dep_map_data = validate_dependency_map(paths.dependency_map(world, canon, series, story))
    cascade_beats = compute_dependents(dep_map_data, ["C1-S1-B1"])
    assert set(cascade_beats) == {"C1-S1-B1", "C1-S1-B2", "C1-S1-B3"}

    llm, telemetry = _make_llm_and_telemetry(settings, paths)
    await draft_story(
        paths, world, canon, series, story,
        beats_mode="all",
        settings=settings, llm=llm, telemetry=telemetry,
        force=True,
        explicit_beats=cascade_beats,
    )

    # B1, B2, B3 were re-drafted (originals overwritten)
    for bid in ["C1-S1-B1", "C1-S1-B2", "C1-S1-B3"]:
        draft_path = paths.beat_draft(world, canon, series, story, bid)
        assert f"ORIGINAL_DRAFT_{bid}" not in draft_path.read_text(), \
            f"{bid} was not re-drafted"

    # B4 was untouched (not in cascade set)
    b4_path = paths.beat_draft(world, canon, series, story, "C1-S1-B4")
    assert "ORIGINAL_DRAFT_C1-S1-B4" in b4_path.read_text(), "B4 should not be touched"


@pytest.mark.asyncio
async def test_draft_cascade_implies_force(paths, settings, world, canon, series, story):
    """With explicit_beats + force=True, pre-existing drafts in the cascade set are overwritten."""
    from quillan.pipeline.runner import draft_story

    beat_ids = ["C1-S1-B1", "C1-S1-B2"]
    deps = {"C1-S1-B1": [], "C1-S1-B2": ["C1-S1-B1"]}
    _setup_draft_story(paths, world, canon, series, story, beat_ids, deps)

    # Pre-write drafts
    for bid in beat_ids:
        draft_path = paths.beat_draft(world, canon, series, story, bid)
        draft_path.parent.mkdir(parents=True, exist_ok=True)
        draft_path.write_text(f"PRE_EXISTING_{bid}\n")

    llm, telemetry = _make_llm_and_telemetry(settings, paths)

    # explicit_beats + force=True (as cascade implies) overwrites existing drafts
    await draft_story(
        paths, world, canon, series, story,
        beats_mode="all",
        settings=settings, llm=llm, telemetry=telemetry,
        force=True,
        explicit_beats=beat_ids,
    )

    for bid in beat_ids:
        draft_path = paths.beat_draft(world, canon, series, story, bid)
        assert f"PRE_EXISTING_{bid}" not in draft_path.read_text(), \
            f"Pre-existing draft for {bid} was not overwritten"
        # Offline stub produces content containing the beat_id
        assert bid in draft_path.read_text()


@pytest.mark.asyncio
async def test_draft_explicit_beats_without_cascade(paths, settings, world, canon, series, story):
    """--beats B1,B3 without --cascade only drafts exactly those two beats."""
    from quillan.pipeline.runner import draft_story

    beat_ids = ["C1-S1-B1", "C1-S1-B2", "C1-S1-B3"]
    deps = {
        "C1-S1-B1": [],
        "C1-S1-B2": ["C1-S1-B1"],
        "C1-S1-B3": ["C1-S1-B1"],
    }
    _setup_draft_story(paths, world, canon, series, story, beat_ids, deps)

    # B2 pre-drafted to verify it's untouched
    b2_path = paths.beat_draft(world, canon, series, story, "C1-S1-B2")
    b2_path.parent.mkdir(parents=True, exist_ok=True)
    b2_path.write_text("B2_ORIGINAL\n")

    llm, telemetry = _make_llm_and_telemetry(settings, paths)

    # Draft only B1 and B3 explicitly
    await draft_story(
        paths, world, canon, series, story,
        beats_mode="all",
        settings=settings, llm=llm, telemetry=telemetry,
        force=False,
        explicit_beats=["C1-S1-B1", "C1-S1-B3"],
    )

    # B1 and B3 are drafted
    for bid in ["C1-S1-B1", "C1-S1-B3"]:
        assert paths.beat_draft(world, canon, series, story, bid).exists(), \
            f"{bid} was not drafted"

    # B2 was NOT touched — still has the original sentinel
    assert "B2_ORIGINAL" in b2_path.read_text(), "B2 should not be drafted"
