"""Tests for regen_beat_specs() and _parse_beats_arg()."""

from __future__ import annotations

import pytest
import yaml


class _FakeLLM:
    """Minimal LLM stub — forces offline/stub code paths."""
    class settings:
        has_api_keys = False


def _make_dirs(paths, world, canon, series, story):
    for d in [
        paths.story_input(world, canon, series, story),
        paths.story_planning(world, canon, series, story),
        paths.story_structure(world, canon, series, story),
        paths.story_beats(world, canon, series, story),
    ]:
        d.mkdir(parents=True, exist_ok=True)


def _write_stub_outline(paths, world, canon, series, story, beat_ids: list[str]) -> None:
    beats = [
        {"beat_id": bid, "title": f"Beat {bid}", "goal": "test", "characters": []}
        for bid in beat_ids
    ]
    outline = {
        "title": "Test Story",
        "genre": "Fiction",
        "theme": "TBD",
        "chapters": [{"chapter": 1, "title": "Act 1", "beats": beats}],
    }
    p = paths.outline(world, canon, series, story)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.dump(outline))


def _write_stub_spine(paths, world, canon, series, story, beat_ids: list[str]) -> None:
    from quillan.structure.story_spine import _stub_spine
    from quillan.io import atomic_write
    spine_path = paths.story_spine(world, canon, series, story)
    spine_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(spine_path, yaml.dump(_stub_spine(beat_ids)))


def _setup_story_for_regen(paths, world, canon, series, story, beat_ids: list[str]) -> None:
    """Create minimal story fixture: dirs + outline + spine."""
    _make_dirs(paths, world, canon, series, story)
    _write_stub_outline(paths, world, canon, series, story, beat_ids)
    _write_stub_spine(paths, world, canon, series, story, beat_ids)


# ── test_regen_specs_regenerates_all ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_regen_specs_regenerates_all(paths, world, canon, series, story):
    """regen_beat_specs() with beats=None regenerates all specs from the outline."""
    from quillan.structure.story import regen_beat_specs

    beat_ids = ["C1-S1-B1", "C1-S1-B2", "C1-S1-B3"]
    _setup_story_for_regen(paths, world, canon, series, story, beat_ids)

    # Pre-create specs so we can verify they get replaced
    for bid in beat_ids:
        spec_path = paths.beat_spec(world, canon, series, story, bid)
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(f"beat_id: {bid}\ntitle: OLD\n")

    count = await regen_beat_specs(
        paths, world, canon, series, story, _FakeLLM(), beats=None
    )

    assert count == len(beat_ids)
    for bid in beat_ids:
        spec_path = paths.beat_spec(world, canon, series, story, bid)
        assert spec_path.exists(), f"Spec missing for {bid}"
        content = spec_path.read_text()
        # The old "OLD" title was replaced
        assert "OLD" not in content


# ── test_regen_specs_specific_beats ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_regen_specs_specific_beats(paths, world, canon, series, story):
    """regen_beat_specs() with an explicit beats list only touches named beats."""
    from quillan.structure.story import regen_beat_specs

    beat_ids = ["C1-S1-B1", "C1-S1-B2", "C1-S1-B3"]
    _setup_story_for_regen(paths, world, canon, series, story, beat_ids)

    # Pre-create all specs with marker text
    for bid in beat_ids:
        spec_path = paths.beat_spec(world, canon, series, story, bid)
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(f"beat_id: {bid}\ntitle: ORIGINAL\n")

    # Only regen B1 and B3
    target = ["C1-S1-B1", "C1-S1-B3"]
    count = await regen_beat_specs(
        paths, world, canon, series, story, _FakeLLM(), beats=target
    )

    assert count == 2

    # B2 was NOT touched — still has ORIGINAL
    b2_path = paths.beat_spec(world, canon, series, story, "C1-S1-B2")
    assert "ORIGINAL" in b2_path.read_text()

    # B1 and B3 were replaced
    for bid in target:
        spec_path = paths.beat_spec(world, canon, series, story, bid)
        assert spec_path.exists()
        assert "ORIGINAL" not in spec_path.read_text()


# ── test_regen_specs_uses_current_artifacts ───────────────────────────────────

@pytest.mark.asyncio
async def test_regen_specs_uses_current_artifacts(paths, world, canon, series, story):
    """regen_beat_specs() reads spine/brief from disk, not hard-coded defaults."""
    from quillan.structure.story import regen_beat_specs
    from quillan.io import atomic_write

    beat_ids = ["C1-S1-B1", "C1-S1-B2"]
    _setup_story_for_regen(paths, world, canon, series, story, beat_ids)

    # Write a custom spine with high tension for B1
    custom_spine = {
        "structure": "three_act",
        "acts": [{"act": 1, "label": "Setup", "beats": beat_ids, "tension_range": [2, 4]}],
        "turning_points": {},
        "beat_tension": {"C1-S1-B1": 9, "C1-S1-B2": 2},
    }
    spine_path = paths.story_spine(world, canon, series, story)
    atomic_write(spine_path, yaml.dump(custom_spine))

    # Write a simple brief
    custom_brief = {
        "voice": {"prose_style": "terse and visceral", "pov": "close third",
                  "characteristic_patterns": [], "avoid": []},
        "tone_palette": [],
        "themes": [],
        "motifs": [],
        "arc_intent": "test arc",
    }
    brief_path = paths.creative_brief(world, canon, series, story)
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(brief_path, yaml.dump(custom_brief))

    count = await regen_beat_specs(
        paths, world, canon, series, story, _FakeLLM(), beats=["C1-S1-B1"]
    )

    assert count == 1
    spec_path = paths.beat_spec(world, canon, series, story, "C1-S1-B1")
    assert spec_path.exists()
    spec_data = yaml.safe_load(spec_path.read_text())
    # The custom spine tension (9) must be reflected in the generated stub
    assert spec_data.get("tension_level") == 9
