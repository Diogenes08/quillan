"""Tests for quillan.structure.conflicts — Conflict Map generation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import yaml


# ── Helpers ────────────────────────────────────────────────────────────────────


def _offline_llm():
    llm = MagicMock()
    llm.settings = MagicMock()
    llm.settings.has_api_keys = False
    return llm


def _online_llm(response: str):
    llm = MagicMock()
    llm.settings = MagicMock()
    llm.settings.has_api_keys = True
    llm.call = AsyncMock(return_value=response)
    return llm


# ── generate_conflict_map ──────────────────────────────────────────────────────


async def test_generate_conflict_map_offline_writes_stub(paths, world, canon, series, story):
    """Without API keys, generate_conflict_map writes a YAML stub."""
    from quillan.structure.conflicts import generate_conflict_map

    await generate_conflict_map(paths, world, canon, series, story, _offline_llm())

    out_path = paths.conflict_map(world, canon, series, story)
    assert out_path.exists()

    data = yaml.safe_load(out_path.read_text())
    assert "protagonist_goal" in data
    assert "antagonist" in data
    assert "core_conflict" in data


async def test_generate_conflict_map_offline_stub_has_valid_conflict_type(
    paths, world, canon, series, story
):
    """Stub conflict_type must be one of the allowed values."""
    from quillan.structure.conflicts import generate_conflict_map

    await generate_conflict_map(paths, world, canon, series, story, _offline_llm())

    data = yaml.safe_load(paths.conflict_map(world, canon, series, story).read_text())
    allowed = {"internal", "external", "societal", "nature", "fate", "interpersonal"}
    assert data.get("conflict_type") in allowed


async def test_generate_conflict_map_online_uses_llm_response(
    paths, world, canon, series, story
):
    """With API keys and an outline present, LLM output is written to Conflict_Map.yaml."""
    from quillan.io import atomic_write
    from quillan.structure.conflicts import generate_conflict_map

    # Provide a minimal outline so the online branch is triggered
    atomic_write(
        paths.outline(world, canon, series, story),
        "title: Test\nchapters:\n  - chapter: 1\n    beats: []\n",
    )

    llm_yaml = (
        "protagonist_goal: Find the artifact\n"
        "antagonist: The Shadow Guild\n"
        "antagonist_goal: Steal the artifact\n"
        "core_conflict: Hero vs guild\n"
        "conflict_type: external\n"
        "resolution_arc: Hero defeats guild\n"
        "antagonist_pressure: []\n"
        "stakes: The world will fall\n"
    )
    llm = _online_llm(llm_yaml)
    await generate_conflict_map(paths, world, canon, series, story, llm)

    out_path = paths.conflict_map(world, canon, series, story)
    data = yaml.safe_load(out_path.read_text())
    assert data["antagonist"] == "The Shadow Guild"
    llm.call.assert_awaited_once()


async def test_generate_conflict_map_online_strips_yaml_fences(
    paths, world, canon, series, story
):
    """LLM response wrapped in ```yaml ... ``` fences is unwrapped correctly."""
    from quillan.io import atomic_write
    from quillan.structure.conflicts import generate_conflict_map

    atomic_write(
        paths.outline(world, canon, series, story),
        "title: T\nchapters: []\n",
    )
    fenced = (
        "```yaml\n"
        "protagonist_goal: Survive\n"
        "antagonist: Nature\n"
        "antagonist_goal: Kill all\n"
        "core_conflict: Man vs nature\n"
        "conflict_type: nature\n"
        "resolution_arc: Protagonist adapts\n"
        "antagonist_pressure: []\n"
        "stakes: Death\n"
        "```"
    )
    await generate_conflict_map(paths, world, canon, series, story, _online_llm(fenced))

    data = yaml.safe_load(paths.conflict_map(world, canon, series, story).read_text())
    assert data["conflict_type"] == "nature"


# ── get_antagonist_pressure ────────────────────────────────────────────────────


def test_get_antagonist_pressure_found():
    from quillan.structure.conflicts import get_antagonist_pressure

    conflict_data = {
        "antagonist_pressure": [
            {"beat_id": "C1-S1-B1", "pressure": "The guild attacks"},
            {"beat_id": "C1-S1-B2", "pressure": "Spy is revealed"},
        ]
    }
    result = get_antagonist_pressure("C1-S1-B1", conflict_data)
    assert result == "The guild attacks"


def test_get_antagonist_pressure_not_found():
    from quillan.structure.conflicts import get_antagonist_pressure

    conflict_data = {"antagonist_pressure": []}
    result = get_antagonist_pressure("C99-S1-B1", conflict_data)
    assert result == ""


def test_get_antagonist_pressure_empty_dict():
    from quillan.structure.conflicts import get_antagonist_pressure

    result = get_antagonist_pressure("C1-S1-B1", {})
    assert result == ""
