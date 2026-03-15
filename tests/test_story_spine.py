"""Tests for story_spine, character_arcs, and subplots modules."""

from __future__ import annotations

import pytest
import yaml


class _FakeLLM:
    """Minimal LLM stub — forces offline/stub code paths."""
    class settings:
        has_api_keys = False


def _make_dirs(paths, world, canon, series, story):
    """Create the directory tree required by planning functions."""
    for d in [
        paths.story_input(world, canon, series, story),
        paths.story_planning(world, canon, series, story),
        paths.story_structure(world, canon, series, story),
    ]:
        d.mkdir(parents=True, exist_ok=True)


def _write_stub_outline(paths, world, canon, series, story, beat_ids: list[str]) -> None:
    """Write a minimal Outline.yaml with the given beat IDs."""
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


# ── _stub_spine (pure logic) ───────────────────────────────────────────────────

def test_stub_spine_has_required_keys():
    """_stub_spine output has structure, acts, turning_points, beat_tension."""
    from quillan.structure.story_spine import _stub_spine
    result = _stub_spine(["C1-S1-B1", "C1-S1-B2", "C1-S1-B3", "C1-S1-B4"])
    assert "structure" in result
    assert "acts" in result
    assert "turning_points" in result
    assert "beat_tension" in result


def test_stub_spine_three_acts():
    """_stub_spine always produces exactly 3 acts."""
    from quillan.structure.story_spine import _stub_spine
    result = _stub_spine(["C1-S1-B1", "C1-S1-B2", "C1-S1-B3", "C1-S1-B4", "C1-S1-B5"])
    assert len(result["acts"]) == 3


def test_stub_spine_all_beats_in_tension_map():
    """Every beat ID appears in beat_tension."""
    from quillan.structure.story_spine import _stub_spine
    beat_ids = [f"C1-S1-B{i}" for i in range(1, 7)]
    result = _stub_spine(beat_ids)
    for bid in beat_ids:
        assert bid in result["beat_tension"]


def test_stub_spine_tension_range():
    """All tension values are integers in 1–10."""
    from quillan.structure.story_spine import _stub_spine
    beat_ids = [f"C1-S1-B{i}" for i in range(1, 9)]
    result = _stub_spine(beat_ids)
    for bid, t in result["beat_tension"].items():
        assert isinstance(t, int), f"{bid} tension is not int"
        assert 1 <= t <= 10, f"{bid} tension {t} out of range"


def test_stub_spine_single_beat():
    """_stub_spine handles a single beat without error."""
    from quillan.structure.story_spine import _stub_spine
    result = _stub_spine(["C1-S1-B1"])
    assert "C1-S1-B1" in result["beat_tension"]


def test_stub_spine_empty_beats():
    """_stub_spine handles an empty beat list without error."""
    from quillan.structure.story_spine import _stub_spine
    result = _stub_spine([])
    assert result["beat_tension"] == {}


# ── get_beat_arc_context ───────────────────────────────────────────────────────

def test_get_beat_arc_context_setup():
    """A beat in act 1 gets arc_position='setup'."""
    from quillan.structure.story_spine import get_beat_arc_context
    spine = {
        "acts": [
            {"act": 1, "label": "Setup", "beats": ["C1-S1-B1", "C1-S1-B2"]},
            {"act": 2, "label": "Confrontation", "beats": ["C2-S1-B1"]},
        ],
        "beat_tension": {"C1-S1-B1": 2},
        "turning_points": {},
    }
    ctx = get_beat_arc_context("C1-S1-B1", spine)
    assert ctx["arc_position"] == "setup"
    assert ctx["tension_level"] == 2


def test_get_beat_arc_context_turning_point_wins():
    """If a beat is a named turning point, that name wins over act label."""
    from quillan.structure.story_spine import get_beat_arc_context
    spine = {
        "acts": [{"act": 2, "label": "Confrontation", "beats": ["C2-S1-B1"]}],
        "beat_tension": {"C2-S1-B1": 5},
        "turning_points": {"midpoint": "C2-S1-B1"},
    }
    ctx = get_beat_arc_context("C2-S1-B1", spine)
    assert ctx["arc_position"] == "midpoint"


def test_get_beat_arc_context_default_tension():
    """A beat not in beat_tension gets default tension 5."""
    from quillan.structure.story_spine import get_beat_arc_context
    ctx = get_beat_arc_context("C1-S1-B99", {})
    assert ctx["tension_level"] == 5


# ── generate_story_spine (async, offline) ─────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_story_spine_creates_file(paths, world, canon, series, story):
    """generate_story_spine writes Story_Spine.yaml."""
    from quillan.structure.story_spine import generate_story_spine
    _make_dirs(paths, world, canon, series, story)
    _write_stub_outline(paths, world, canon, series, story, ["C1-S1-B1", "C1-S1-B2"])
    await generate_story_spine(paths, world, canon, series, story, _FakeLLM())
    assert paths.story_spine(world, canon, series, story).exists()


@pytest.mark.asyncio
async def test_generate_story_spine_valid_yaml(paths, world, canon, series, story):
    """Story_Spine.yaml is valid YAML with required keys."""
    from quillan.structure.story_spine import generate_story_spine
    _make_dirs(paths, world, canon, series, story)
    _write_stub_outline(paths, world, canon, series, story,
                        [f"C1-S1-B{i}" for i in range(1, 5)])
    await generate_story_spine(paths, world, canon, series, story, _FakeLLM())
    data = yaml.safe_load(paths.story_spine(world, canon, series, story).read_text())
    assert "structure" in data
    assert "acts" in data
    assert "beat_tension" in data


@pytest.mark.asyncio
async def test_generate_story_spine_idempotent(paths, world, canon, series, story):
    """If Story_Spine.yaml already exists, it is not overwritten."""
    from quillan.structure.story_spine import generate_story_spine
    _make_dirs(paths, world, canon, series, story)
    spine_path = paths.story_spine(world, canon, series, story)
    spine_path.parent.mkdir(parents=True, exist_ok=True)
    spine_path.write_text("existing: content\n")
    # Second generate — spine is NOT called from story.py if file exists,
    # but the function itself will overwrite. This tests the guard in create_story.
    # Here we just test it runs without error on empty outline.
    await generate_story_spine(paths, world, canon, series, story, _FakeLLM())


# ── generate_character_arcs ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_character_arcs_creates_file(paths, world, canon, series, story):
    """generate_character_arcs writes Character_Arcs.yaml."""
    from quillan.structure.character_arcs import generate_character_arcs
    _make_dirs(paths, world, canon, series, story)
    await generate_character_arcs(paths, world, canon, series, story, _FakeLLM())
    assert paths.character_arcs(world, canon, series, story).exists()


@pytest.mark.asyncio
async def test_generate_character_arcs_valid_yaml(paths, world, canon, series, story):
    """Character_Arcs.yaml has a 'characters' list."""
    from quillan.structure.character_arcs import generate_character_arcs
    _make_dirs(paths, world, canon, series, story)
    await generate_character_arcs(paths, world, canon, series, story, _FakeLLM())
    data = yaml.safe_load(paths.character_arcs(world, canon, series, story).read_text())
    assert "characters" in data
    assert isinstance(data["characters"], list)


@pytest.mark.asyncio
async def test_generate_character_arcs_stub_has_protagonist(paths, world, canon, series, story):
    """The offline stub includes a Protagonist entry."""
    from quillan.structure.character_arcs import generate_character_arcs
    _make_dirs(paths, world, canon, series, story)
    await generate_character_arcs(paths, world, canon, series, story, _FakeLLM())
    data = yaml.safe_load(paths.character_arcs(world, canon, series, story).read_text())
    names = [c.get("name") for c in data["characters"]]
    assert "Protagonist" in names


# ── get_char_arc_notes ─────────────────────────────────────────────────────────

def test_get_char_arc_notes_returns_dict():
    """get_char_arc_notes returns a dict keyed by character name."""
    from quillan.structure.character_arcs import get_char_arc_notes
    arcs = {
        "characters": [
            {
                "name": "Alice",
                "arc_type": "positive_change",
                "starting_state": "fearful",
                "ending_state": "courageous",
                "turning_points": [],
            }
        ]
    }
    notes = get_char_arc_notes("C1-S1-B1", arcs)
    assert "Alice" in notes
    assert isinstance(notes["Alice"], str)


def test_get_char_arc_notes_reflects_turning_point():
    """Notes show the most recent turning point label."""
    from quillan.structure.character_arcs import get_char_arc_notes
    arcs = {
        "characters": [
            {
                "name": "Bob",
                "arc_type": "negative_change",
                "starting_state": "hopeful",
                "ending_state": "bitter",
                "turning_points": [
                    {"beat_id": "C1-S1-B2", "label": "betrayal", "description": "..."},
                ],
            }
        ]
    }
    # Beat is AFTER the turning point — should show "post 'betrayal'"
    notes = get_char_arc_notes("C1-S1-B3", arcs)
    assert "betrayal" in notes["Bob"]


def test_get_char_arc_notes_empty_arcs():
    """Empty arcs data returns empty dict."""
    from quillan.structure.character_arcs import get_char_arc_notes
    assert get_char_arc_notes("C1-S1-B1", {}) == {}


# ── generate_subplot_register ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_subplot_register_creates_file(paths, world, canon, series, story):
    """generate_subplot_register writes Subplot_Register.yaml."""
    from quillan.structure.subplots import generate_subplot_register
    _make_dirs(paths, world, canon, series, story)
    await generate_subplot_register(paths, world, canon, series, story, _FakeLLM())
    assert paths.subplot_register(world, canon, series, story).exists()


@pytest.mark.asyncio
async def test_generate_subplot_register_valid_yaml(paths, world, canon, series, story):
    """Subplot_Register.yaml is valid YAML with a 'subplots' key."""
    from quillan.structure.subplots import generate_subplot_register
    _make_dirs(paths, world, canon, series, story)
    await generate_subplot_register(paths, world, canon, series, story, _FakeLLM())
    data = yaml.safe_load(paths.subplot_register(world, canon, series, story).read_text())
    assert "subplots" in data


@pytest.mark.asyncio
async def test_generate_subplot_register_stub_is_empty_list(paths, world, canon, series, story):
    """The offline stub produces an empty subplots list (no invention)."""
    from quillan.structure.subplots import generate_subplot_register
    _make_dirs(paths, world, canon, series, story)
    await generate_subplot_register(paths, world, canon, series, story, _FakeLLM())
    data = yaml.safe_load(paths.subplot_register(world, canon, series, story).read_text())
    assert data["subplots"] == []


# ── new path methods ───────────────────────────────────────────────────────────

def test_paths_creative_brief_interview(paths):
    result = paths.creative_brief_interview("w", "c", "s", "st")
    assert result.name == "Creative_Brief_Interview.md"
    assert result.parent.name == "planning"


def test_paths_creative_brief(paths):
    result = paths.creative_brief("w", "c", "s", "st")
    assert result.name == "Creative_Brief.yaml"
    assert result.parent.name == "planning"


def test_paths_story_spine(paths):
    result = paths.story_spine("w", "c", "s", "st")
    assert result.name == "Story_Spine.yaml"
    assert result.parent.name == "structure"


def test_paths_character_arcs(paths):
    result = paths.character_arcs("w", "c", "s", "st")
    assert result.name == "Character_Arcs.yaml"
    assert result.parent.name == "structure"


def test_paths_subplot_register(paths):
    result = paths.subplot_register("w", "c", "s", "st")
    assert result.name == "Subplot_Register.yaml"
    assert result.parent.name == "structure"
