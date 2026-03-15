"""Tests for quillan.structure.subplots."""

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


# ── generate_subplot_register ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_subplot_register_creates_file(paths, world, canon, series, story):
    """generate_subplot_register creates Subplot_Register.yaml."""
    from quillan.structure.subplots import generate_subplot_register
    _make_dirs(paths, world, canon, series, story)
    await generate_subplot_register(paths, world, canon, series, story, _FakeLLM())
    assert paths.subplot_register(world, canon, series, story).exists()


@pytest.mark.asyncio
async def test_generate_subplot_register_valid_yaml(paths, world, canon, series, story):
    """The generated file is valid YAML with a 'subplots' key."""
    from quillan.structure.subplots import generate_subplot_register
    _make_dirs(paths, world, canon, series, story)
    await generate_subplot_register(paths, world, canon, series, story, _FakeLLM())
    data = yaml.safe_load(
        paths.subplot_register(world, canon, series, story).read_text()
    )
    assert "subplots" in data
    assert isinstance(data["subplots"], list)


@pytest.mark.asyncio
async def test_generate_subplot_register_offline_stub_empty_list(
    paths, world, canon, series, story
):
    """Offline stub returns subplots: [] (no invented subplots without LLM)."""
    from quillan.structure.subplots import generate_subplot_register
    _make_dirs(paths, world, canon, series, story)
    await generate_subplot_register(paths, world, canon, series, story, _FakeLLM())
    data = yaml.safe_load(
        paths.subplot_register(world, canon, series, story).read_text()
    )
    assert data["subplots"] == []


@pytest.mark.asyncio
async def test_generate_subplot_register_reads_outline_if_exists(
    paths, world, canon, series, story
):
    """generate_subplot_register reads Outline.yaml when available."""
    from quillan.structure.subplots import generate_subplot_register
    _make_dirs(paths, world, canon, series, story)
    outline_path = paths.outline(world, canon, series, story)
    outline_path.parent.mkdir(parents=True, exist_ok=True)
    outline_path.write_text("title: Test Story\nchapters: []")
    await generate_subplot_register(paths, world, canon, series, story, _FakeLLM())
    # Offline stub is still produced (no API keys), but no error
    assert paths.subplot_register(world, canon, series, story).exists()


@pytest.mark.asyncio
async def test_generate_subplot_register_validate_passes(paths, world, canon, series, story):
    """validate_subplot_register passes on generated output."""
    from quillan.structure.subplots import generate_subplot_register
    from quillan.validate import validate_subplot_register
    _make_dirs(paths, world, canon, series, story)
    await generate_subplot_register(paths, world, canon, series, story, _FakeLLM())
    # Should not raise
    data = validate_subplot_register(paths.subplot_register(world, canon, series, story))
    assert "subplots" in data
