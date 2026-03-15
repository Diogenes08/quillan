"""End-to-end integration test: create → draft → export with offline stubs.

No LLM calls are made. create_story() and draft_story() both stub out
all LLM responses, exercising the full data-flow from seed text to
exported Markdown.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest


# ── Fixtures ────────────────────────────────────────────────────────────────────

@pytest.fixture
def e2e_settings(tmp_path):
    from quillan.config import Settings
    return Settings(data_dir=tmp_path, llm_cache=False, telemetry=False)


@pytest.fixture
def e2e_paths(tmp_path):
    from quillan.paths import Paths
    return Paths(tmp_path)


@pytest.fixture
def e2e_llm(e2e_settings):
    from quillan.telemetry import Telemetry
    from quillan.llm import LLMClient

    tel = Telemetry(e2e_settings.data_dir / ".runs", enabled=False)
    # Return a real LLMClient but with no API keys → offline stubs throughout
    return LLMClient(e2e_settings, tel, cache_dir=None)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _write_minimal_story_structure(paths, world, canon, series, story):
    """Manually create the minimum filesystem artefacts that draft_story needs."""
    import yaml
    from quillan.io import atomic_write

    beat_id = "C1-S1-B1"

    outline = {
        "title": "Test Story",
        "genre": "test",
        "theme": "testing",
        "chapters": [
            {
                "chapter": 1,
                "title": "Chapter One",
                "beats": [{"beat_id": beat_id, "title": "Opening Beat"}],
            }
        ],
    }
    dep_map = {"dependencies": {beat_id: []}}
    spec = {"beat_id": beat_id, "goal": "open the story", "word_count_target": 50}

    atomic_write(paths.outline(world, canon, series, story), yaml.dump(outline))
    atomic_write(paths.dependency_map(world, canon, series, story), json.dumps(dep_map))
    atomic_write(paths.beat_spec(world, canon, series, story, beat_id), yaml.dump(spec))
    paths.beat(world, canon, series, story, beat_id).mkdir(parents=True, exist_ok=True)

    return beat_id


# ── Test ───────────────────────────────────────────────────────────────────────


async def test_draft_then_export_roundtrip(tmp_path, e2e_settings, e2e_paths, e2e_llm):
    """draft_story() writes Beat_Draft.md; export_story() assembles it into Markdown."""
    from quillan.pipeline.runner import draft_story
    from quillan.export import export_story
    from quillan.telemetry import Telemetry

    world, canon, series, story = "w", "c", "s", "test_e2e"
    beat_id = _write_minimal_story_structure(e2e_paths, world, canon, series, story)

    telemetry = Telemetry(tmp_path / ".runs", enabled=False)

    # draft_story with no API keys → offline stubs
    result = await draft_story(
        e2e_paths, world, canon, series, story,
        beats_mode="all",
        settings=e2e_settings,
        llm=e2e_llm,
        telemetry=telemetry,
    )

    # Beat should be completed (offline stub counts as success)
    assert beat_id in result.completed
    assert not result.has_failures

    draft_path = e2e_paths.beat_draft(world, canon, series, story, beat_id)
    assert draft_path.exists()
    prose = draft_path.read_text(encoding="utf-8")
    assert len(prose) > 0

    # Export to Markdown
    export_result = export_story(e2e_paths, world, canon, series, story, fmt="markdown")
    assert export_result.path.exists()
    assert export_result.fmt == "markdown"
    assert not export_result.degraded

    content = export_result.path.read_text(encoding="utf-8")
    assert "Test Story" in content
    assert "Chapter One" in content
    # The offline stub prose should be assembled into the manuscript
    assert len(content) > 50


async def test_export_degrades_gracefully_without_pandoc(tmp_path, e2e_settings, e2e_paths, e2e_llm):
    """Requesting epub without pandoc returns an ExportResult with degraded=True."""
    from quillan.pipeline.runner import draft_story
    from quillan.export import export_story
    from quillan.telemetry import Telemetry

    world, canon, series, story = "w", "c", "s", "test_degrade"
    _write_minimal_story_structure(e2e_paths, world, canon, series, story)

    telemetry = Telemetry(tmp_path / ".runs", enabled=False)
    await draft_story(
        e2e_paths, world, canon, series, story, "all",
        e2e_settings, e2e_llm, telemetry,
    )

    with patch("quillan.export._pandoc_available", return_value=False):
        result = export_story(e2e_paths, world, canon, series, story, fmt="epub")

    assert result.degraded is True
    assert result.fmt == "markdown"
    assert result.requested_fmt == "epub"
    assert result.path.suffix == ".md"
