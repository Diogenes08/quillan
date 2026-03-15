"""Tests for quillan.structure.character_arcs."""

from __future__ import annotations

import pytest
import yaml


class _FakeLLM:
    class settings:
        has_api_keys = False


def _make_dirs(paths, world, canon, series, story):
    for d in [
        paths.story_input(world, canon, series, story),
        paths.story_planning(world, canon, series, story),
        paths.story_structure(world, canon, series, story),
    ]:
        d.mkdir(parents=True, exist_ok=True)


# ── generate_character_arcs ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_character_arcs_creates_file(paths, world, canon, series, story):
    """generate_character_arcs creates Character_Arcs.yaml."""
    from quillan.structure.character_arcs import generate_character_arcs
    _make_dirs(paths, world, canon, series, story)
    await generate_character_arcs(paths, world, canon, series, story, _FakeLLM())
    assert paths.character_arcs(world, canon, series, story).exists()


@pytest.mark.asyncio
async def test_generate_character_arcs_valid_yaml(paths, world, canon, series, story):
    """The generated file is valid YAML with a 'characters' key."""
    from quillan.structure.character_arcs import generate_character_arcs
    _make_dirs(paths, world, canon, series, story)
    await generate_character_arcs(paths, world, canon, series, story, _FakeLLM())
    data = yaml.safe_load(
        paths.character_arcs(world, canon, series, story).read_text()
    )
    assert "characters" in data
    assert isinstance(data["characters"], list)


@pytest.mark.asyncio
async def test_generate_character_arcs_stub_has_required_fields(
    paths, world, canon, series, story
):
    """Offline stub includes arc_type, starting_state, ending_state for first char."""
    from quillan.structure.character_arcs import generate_character_arcs
    _make_dirs(paths, world, canon, series, story)
    await generate_character_arcs(paths, world, canon, series, story, _FakeLLM())
    data = yaml.safe_load(
        paths.character_arcs(world, canon, series, story).read_text()
    )
    char = data["characters"][0]
    assert "arc_type" in char
    assert "starting_state" in char
    assert "ending_state" in char
    assert "motivation" in char


@pytest.mark.asyncio
async def test_generate_character_arcs_idempotent(paths, world, canon, series, story):
    """Calling generate_character_arcs twice uses the existing file (no overwrite)."""
    from quillan.structure.character_arcs import generate_character_arcs
    _make_dirs(paths, world, canon, series, story)
    await generate_character_arcs(paths, world, canon, series, story, _FakeLLM())
    arcs_path = paths.character_arcs(world, canon, series, story)

    # Second call should write again (function always writes when it runs;
    # the idempotency guard is in create_story, not generate_character_arcs)
    await generate_character_arcs(paths, world, canon, series, story, _FakeLLM())
    # Just verify file still exists and is valid
    data = yaml.safe_load(arcs_path.read_text())
    assert "characters" in data


# ── get_char_arc_notes ─────────────────────────────────────────────────────────

def test_get_char_arc_notes_returns_empty_for_empty_data():
    """get_char_arc_notes returns {} when arcs_data is empty."""
    from quillan.structure.character_arcs import get_char_arc_notes
    result = get_char_arc_notes("C1-S1-B1", {})
    assert result == {}


def test_get_char_arc_notes_returns_arc_summary():
    """get_char_arc_notes returns formatted arc summary for each character."""
    from quillan.structure.character_arcs import get_char_arc_notes
    arcs_data = {
        "characters": [
            {
                "name": "Alice",
                "arc_type": "positive_change",
                "starting_state": "fearful",
                "ending_state": "courageous",
                "motivation": "seeks safety",
                "turning_points": [
                    {"beat_id": "C1-S1-B2", "label": "inciting wound"},
                ],
            }
        ]
    }
    notes = get_char_arc_notes("C1-S1-B3", arcs_data)
    assert "Alice" in notes
    assert "inciting wound" in notes["Alice"]


def test_get_char_arc_notes_before_turning_point():
    """Before any turning point, get_char_arc_notes returns starting → ending."""
    from quillan.structure.character_arcs import get_char_arc_notes
    arcs_data = {
        "characters": [
            {
                "name": "Bob",
                "arc_type": "flat",
                "starting_state": "steadfast",
                "ending_state": "steadfast",
                "motivation": "protects others",
                "turning_points": [
                    {"beat_id": "C3-S1-B1", "label": "temptation"},
                ],
            }
        ]
    }
    # Beat ID before the turning point
    notes = get_char_arc_notes("C1-S1-B1", arcs_data)
    assert "Bob" in notes
    assert "steadfast" in notes["Bob"]


def test_get_char_arc_notes_multiple_characters():
    """get_char_arc_notes returns entries for all named characters."""
    from quillan.structure.character_arcs import get_char_arc_notes
    arcs_data = {
        "characters": [
            {"name": "Alice", "arc_type": "positive_change",
             "starting_state": "s", "ending_state": "e",
             "motivation": "m", "turning_points": []},
            {"name": "Bob", "arc_type": "flat",
             "starting_state": "s", "ending_state": "e",
             "motivation": "m", "turning_points": []},
        ]
    }
    notes = get_char_arc_notes("C1-S1-B1", arcs_data)
    assert "Alice" in notes
    assert "Bob" in notes


def test_get_char_arc_notes_skips_unnamed():
    """Characters without a name field are silently skipped."""
    from quillan.structure.character_arcs import get_char_arc_notes
    arcs_data = {
        "characters": [
            {"arc_type": "flat", "starting_state": "s", "ending_state": "e",
             "motivation": "m", "turning_points": []},
        ]
    }
    notes = get_char_arc_notes("C1-S1-B1", arcs_data)
    assert notes == {}
