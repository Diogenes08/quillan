"""Tests for draft.bundle — context assembly, author context section."""

from __future__ import annotations

import json
import yaml
import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _write_beat_spec(paths, world, canon, series, story, beat_id, spec: dict) -> None:
    p = paths.beat_spec(world, canon, series, story, beat_id)
    paths.ensure(p)
    p.write_text(yaml.dump(spec))


def _write_creative_brief(paths, world, canon, series, story, brief: dict) -> None:
    p = paths.creative_brief(world, canon, series, story)
    paths.ensure(p)
    p.write_text(yaml.dump(brief))


def _make_story_dirs(paths, world, canon, series, story) -> None:
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


# ── _build_author_context (unit tests — pure function) ────────────────────────

def test_build_author_context_empty_spec_no_brief(paths, world, canon, series, story, tmp_path):
    """Empty spec + no brief → empty string (no section added)."""
    from quillan.draft.bundle import _build_author_context
    result = _build_author_context(paths, world, canon, series, story, {})
    assert result == ""


def test_build_author_context_arc_position_and_tension(paths, world, canon, series, story):
    """arc_position and tension_level appear in the output."""
    from quillan.draft.bundle import _build_author_context
    spec = {"arc_position": "rising_action", "tension_level": 7}
    result = _build_author_context(paths, world, canon, series, story, spec)
    assert "rising_action" in result
    assert "7/10" in result


def test_build_author_context_voice_from_brief(paths, world, canon, series, story):
    """Voice fields from Creative_Brief.yaml appear in output."""
    from quillan.draft.bundle import _build_author_context
    brief = {
        "voice": {
            "prose_style": "terse and visceral",
            "pov": "close third",
            "characteristic_patterns": ["short sentences"],
            "avoid": ["purple prose"],
        },
        "arc_intent": "A to B",
    }
    _write_creative_brief(paths, world, canon, series, story, brief)
    spec = {"arc_position": "setup", "tension_level": 3}
    result = _build_author_context(paths, world, canon, series, story, spec)
    assert "terse and visceral" in result
    assert "close third" in result
    assert "short sentences" in result
    assert "purple prose" in result


def test_build_author_context_active_motifs(paths, world, canon, series, story):
    """Active motifs from spec appear in output."""
    from quillan.draft.bundle import _build_author_context
    spec = {
        "active_motifs": [
            {"name": "broken glass", "note": "fractured self"},
        ]
    }
    result = _build_author_context(paths, world, canon, series, story, spec)
    assert "broken glass" in result
    assert "fractured self" in result


def test_build_author_context_char_arc_notes(paths, world, canon, series, story):
    """char_arc_notes from spec appear as character lines."""
    from quillan.draft.bundle import _build_author_context
    spec = {
        "char_arc_notes": {
            "Alice": "positive_change arc — post 'inciting wound'",
        }
    }
    result = _build_author_context(paths, world, canon, series, story, spec)
    assert "Alice" in result
    assert "inciting wound" in result


def test_build_author_context_heading(paths, world, canon, series, story):
    """Non-empty author context starts with '# Author Context'."""
    from quillan.draft.bundle import _build_author_context
    spec = {"arc_position": "midpoint", "tension_level": 6}
    result = _build_author_context(paths, world, canon, series, story, spec)
    assert result.startswith("# Author Context")


def test_build_author_context_motifs_empty_list(paths, world, canon, series, story):
    """Empty motif list produces no motifs section but no error."""
    from quillan.draft.bundle import _build_author_context
    spec = {"active_motifs": [], "arc_position": "setup", "tension_level": 2}
    result = _build_author_context(paths, world, canon, series, story, spec)
    assert "Motifs" not in result
    assert "setup" in result


# ── assemble_bundle integration (offline, no LLM) ────────────────────────────

@pytest.mark.asyncio
async def test_assemble_bundle_creates_context_md(paths, world, canon, series, story, settings):
    """assemble_bundle writes context.md and returns its path."""
    from quillan.draft.bundle import assemble_bundle
    _make_story_dirs(paths, world, canon, series, story)
    beat_id = "C1-S1-B1"
    _write_beat_spec(paths, world, canon, series, story, beat_id, {
        "beat_id": beat_id,
        "goal": "Open the story",
        "tone": "melancholic",
        "scope": ["Character wakes"],
        "out_of_scope": [],
        "rules": [],
        "word_count_target": 1200,
        "arc_position": "setup",
        "tension_level": 2,
        "active_motifs": [],
        "char_arc_notes": {},
    })
    ctx_path = await assemble_bundle(
        paths, world, canon, series, story, beat_id, settings
    )
    assert ctx_path.exists()
    assert ctx_path.name == "context.md"


@pytest.mark.asyncio
async def test_assemble_bundle_contains_scope_contract(paths, world, canon, series, story, settings):
    """context.md includes the Scope Contract section."""
    from quillan.draft.bundle import assemble_bundle
    _make_story_dirs(paths, world, canon, series, story)
    beat_id = "C1-S1-B1"
    _write_beat_spec(paths, world, canon, series, story, beat_id, {
        "beat_id": beat_id,
        "goal": "Introduce Maren at the lighthouse",
        "tone": "tense",
        "scope": ["Maren notices the light is wrong"],
        "out_of_scope": [],
        "rules": [],
        "word_count_target": 1500,
    })
    ctx_path = await assemble_bundle(
        paths, world, canon, series, story, beat_id, settings
    )
    text = ctx_path.read_text()
    assert "Scope Contract" in text
    assert "Introduce Maren" in text


@pytest.mark.asyncio
async def test_assemble_bundle_author_context_present_when_enriched(
    paths, world, canon, series, story, settings
):
    """context.md includes Author Context section when spec has arc fields."""
    from quillan.draft.bundle import assemble_bundle
    _make_story_dirs(paths, world, canon, series, story)
    beat_id = "C1-S1-B1"
    _write_beat_spec(paths, world, canon, series, story, beat_id, {
        "beat_id": beat_id,
        "goal": "Open",
        "tone": "dread",
        "scope": [],
        "out_of_scope": [],
        "rules": [],
        "word_count_target": 1000,
        "arc_position": "setup",
        "tension_level": 3,
        "active_motifs": [{"name": "fog", "note": "isolation"}],
        "char_arc_notes": {"Maren": "pre-wound, still functional"},
    })
    ctx_path = await assemble_bundle(
        paths, world, canon, series, story, beat_id, settings
    )
    text = ctx_path.read_text()
    assert "Author Context" in text
    assert "setup" in text
    assert "fog" in text
    assert "Maren" in text


@pytest.mark.asyncio
async def test_assemble_bundle_author_context_absent_when_no_arc_fields(
    paths, world, canon, series, story, settings
):
    """context.md has no Author Context section when spec has no arc fields."""
    from quillan.draft.bundle import assemble_bundle
    _make_story_dirs(paths, world, canon, series, story)
    beat_id = "C1-S1-B1"
    _write_beat_spec(paths, world, canon, series, story, beat_id, {
        "beat_id": beat_id,
        "goal": "Open",
        "tone": "neutral",
        "scope": [],
        "out_of_scope": [],
        "rules": [],
        "word_count_target": 1000,
    })
    ctx_path = await assemble_bundle(
        paths, world, canon, series, story, beat_id, settings
    )
    text = ctx_path.read_text()
    assert "Author Context" not in text


@pytest.mark.asyncio
async def test_assemble_bundle_inputs_json_written(paths, world, canon, series, story, settings):
    """inputs.json is written alongside context.md."""
    from quillan.draft.bundle import assemble_bundle
    _make_story_dirs(paths, world, canon, series, story)
    beat_id = "C1-S1-B1"
    _write_beat_spec(paths, world, canon, series, story, beat_id, {
        "beat_id": beat_id, "goal": "g", "tone": "t",
        "scope": [], "out_of_scope": [], "rules": [], "word_count_target": 800,
    })
    await assemble_bundle(paths, world, canon, series, story, beat_id, settings)
    inputs_path = paths.beat_inputs(world, canon, series, story, beat_id)
    assert inputs_path.exists()
    data = json.loads(inputs_path.read_text())
    assert "sha256" in data


@pytest.mark.asyncio
async def test_assemble_bundle_brief_hash_in_inputs_when_brief_present(
    paths, world, canon, series, story, settings
):
    """When Creative_Brief.yaml exists, its hash appears in inputs.json."""
    from quillan.draft.bundle import assemble_bundle
    _make_story_dirs(paths, world, canon, series, story)
    beat_id = "C1-S1-B1"
    _write_beat_spec(paths, world, canon, series, story, beat_id, {
        "beat_id": beat_id, "goal": "g", "tone": "t",
        "scope": [], "out_of_scope": [], "rules": [], "word_count_target": 800,
        "arc_position": "setup", "tension_level": 2,
    })
    _write_creative_brief(paths, world, canon, series, story, {
        "voice": {"pov": "third"}, "arc_intent": "A to B"
    })
    await assemble_bundle(paths, world, canon, series, story, beat_id, settings)
    inputs_path = paths.beat_inputs(world, canon, series, story, beat_id)
    data = json.loads(inputs_path.read_text())
    assert "creative_brief" in data["sha256"]
