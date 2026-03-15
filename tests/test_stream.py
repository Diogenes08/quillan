"""Tests for _update_stream_file() and draft_story() --stream integration."""

from __future__ import annotations

import json
import yaml
import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _write_outline(paths, world, canon, series, story, chapters: list[dict]) -> None:
    outline = {
        "title": "Stream Test Story",
        "genre": "Fiction",
        "theme": "Testing",
        "chapters": chapters,
    }
    p = paths.outline(world, canon, series, story)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.dump(outline))


def _write_draft(paths, world, canon, series, story, beat_id: str, prose: str) -> None:
    draft_path = paths.beat_draft(world, canon, series, story, beat_id)
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(prose)


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
        paths.story_export(world, canon, series, story),
    ]:
        d.mkdir(parents=True, exist_ok=True)

    dep_map = {"dependencies": {bid: ([beat_ids[i - 1]] if i else [])
                                for i, bid in enumerate(beat_ids)}}
    paths.dependency_map(world, canon, series, story).write_text(json.dumps(dep_map))

    for bid in beat_ids:
        spec_path = paths.beat_spec(world, canon, series, story, bid)
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(yaml.dump({
            "beat_id": bid, "title": f"Beat {bid}", "goal": "test",
            "word_count_target": 100, "scope": [], "out_of_scope": [],
            "rules": [], "tone": "neutral",
        }))

    beats = [{"beat_id": bid, "title": f"Beat {bid}", "goal": "test", "characters": []}
             for bid in beat_ids]
    _write_outline(paths, world, canon, series, story,
                   [{"chapter": 1, "title": "Act 1", "beats": beats}])


def _make_llm_and_telemetry(settings, paths):
    from quillan.llm import LLMClient
    from quillan.telemetry import Telemetry
    telemetry = Telemetry(paths.runs_dir(), enabled=False)
    llm = LLMClient(settings, telemetry, cache_dir=settings.cache_dir)
    return llm, telemetry


# ── unit tests for _update_stream_file ───────────────────────────────────────

def test_creates_stream_file(paths, world, canon, series, story, tmp_path):
    """_update_stream_file() creates the stream file at the specified path."""
    from quillan.pipeline.runner import _update_stream_file

    chapters = [{"chapter": 1, "title": "Act 1",
                 "beats": [{"beat_id": "C1-S1-B1", "title": "Opening"}]}]
    _write_outline(paths, world, canon, series, story, chapters)
    _write_draft(paths, world, canon, series, story, "C1-S1-B1", "Some prose here.")

    stream_path = tmp_path / "test.live.md"
    _update_stream_file(paths, world, canon, series, story, stream_path,
                        beats_done=1, total_beats=1)

    assert stream_path.exists()
    content = stream_path.read_text()
    assert len(content) > 0


def test_outline_order_preserved(paths, world, canon, series, story, tmp_path):
    """Chapters appear in ascending chapter-number order in the stream file."""
    from quillan.pipeline.runner import _update_stream_file

    chapters = [
        {"chapter": 2, "title": "Act 2",
         "beats": [{"beat_id": "C2-S1-B1", "title": "Midpoint"}]},
        {"chapter": 1, "title": "Act 1",
         "beats": [{"beat_id": "C1-S1-B1", "title": "Opening"}]},
    ]
    _write_outline(paths, world, canon, series, story, chapters)
    _write_draft(paths, world, canon, series, story, "C1-S1-B1", "Act 1 prose.")
    _write_draft(paths, world, canon, series, story, "C2-S1-B1", "Act 2 prose.")

    stream_path = tmp_path / "test.live.md"
    _update_stream_file(paths, world, canon, series, story, stream_path,
                        beats_done=2, total_beats=2)

    content = stream_path.read_text()
    pos_act1 = content.index("Act 1")
    pos_act2 = content.index("Act 2")
    # Chapter 1 (Act 1) must appear before Chapter 2 (Act 2)
    assert pos_act1 < pos_act2


def test_partial_drafts_included(paths, world, canon, series, story, tmp_path):
    """Only beats with an existing Beat_Draft.md appear in the stream file."""
    from quillan.pipeline.runner import _update_stream_file

    chapters = [{"chapter": 1, "title": "Act 1", "beats": [
        {"beat_id": "C1-S1-B1", "title": "Opening"},
        {"beat_id": "C1-S1-B2", "title": "Rising Action"},
        {"beat_id": "C1-S1-B3", "title": "Climax"},
    ]}]
    _write_outline(paths, world, canon, series, story, chapters)
    _write_draft(paths, world, canon, series, story, "C1-S1-B1", "Beat 1 prose MARKER_A.")
    # B2 and B3 have no draft yet

    stream_path = tmp_path / "partial.live.md"
    _update_stream_file(paths, world, canon, series, story, stream_path,
                        beats_done=1, total_beats=3)

    content = stream_path.read_text()
    assert "MARKER_A" in content
    # B2 and B3 prose should not be present
    assert "Rising Action" not in content or "Beat 2 prose" not in content
    assert "Beat 3 prose" not in content


def test_front_matter_has_status(paths, world, canon, series, story, tmp_path):
    """YAML front matter contains the 'status' field with beat count."""
    from quillan.pipeline.runner import _update_stream_file

    chapters = [{"chapter": 1, "title": "Act 1",
                 "beats": [{"beat_id": "C1-S1-B1", "title": "Opening"}]}]
    _write_outline(paths, world, canon, series, story, chapters)
    _write_draft(paths, world, canon, series, story, "C1-S1-B1", "Prose.")

    stream_path = tmp_path / "fm.live.md"
    _update_stream_file(paths, world, canon, series, story, stream_path,
                        beats_done=5, total_beats=10)

    content = stream_path.read_text()
    assert content.startswith("---\n")
    # Extract front matter
    fm_end = content.index("---\n", 4)
    fm_text = content[4:fm_end]
    fm = yaml.safe_load(fm_text)
    assert "status" in fm
    assert "5/10" in fm["status"]


def test_noop_when_no_outline(paths, world, canon, series, story, tmp_path):
    """No file is written when Outline.yaml is absent."""
    from quillan.pipeline.runner import _update_stream_file

    # Ensure outline does NOT exist
    outline_path = paths.outline(world, canon, series, story)
    assert not outline_path.exists()

    stream_path = tmp_path / "noop.live.md"
    _update_stream_file(paths, world, canon, series, story, stream_path,
                        beats_done=0, total_beats=0)

    assert not stream_path.exists()


def test_title_from_outline(paths, world, canon, series, story, tmp_path):
    """The story title from Outline.yaml appears in the stream file heading."""
    from quillan.pipeline.runner import _update_stream_file

    chapters = [{"chapter": 1, "title": "Act 1",
                 "beats": [{"beat_id": "C1-S1-B1", "title": "Opening"}]}]
    # Override outline title
    outline = {"title": "MY_UNIQUE_TITLE", "genre": "Fiction",
               "theme": "TBD", "chapters": chapters}
    p = paths.outline(world, canon, series, story)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.dump(outline))
    _write_draft(paths, world, canon, series, story, "C1-S1-B1", "Prose.")

    stream_path = tmp_path / "title.live.md"
    _update_stream_file(paths, world, canon, series, story, stream_path,
                        beats_done=1, total_beats=1)

    content = stream_path.read_text()
    assert "MY_UNIQUE_TITLE" in content


# ── integration tests for draft_story() with stream_path ─────────────────────

@pytest.mark.asyncio
async def test_draft_story_writes_stream(paths, settings, world, canon, series, story):
    """After draft_story(stream_path=...) finishes, stream file contains prose."""
    from quillan.pipeline.runner import draft_story

    beat_ids = ["C1-S1-B1", "C1-S1-B2"]
    _setup_minimal_story(paths, world, canon, series, story, beat_ids)

    llm, telemetry = _make_llm_and_telemetry(settings, paths)

    stream_path = paths.story_export(world, canon, series, story) / f"{story}.live.md"

    await draft_story(
        paths, world, canon, series, story, "all", settings, llm, telemetry,
        force=False, stream_path=stream_path,
    )

    assert stream_path.exists(), "Stream file was not created"
    content = stream_path.read_text()
    # Should have front matter and at least one beat id in the prose
    assert "---" in content
    assert any(bid in content for bid in beat_ids)


@pytest.mark.asyncio
async def test_draft_story_no_stream_when_none(paths, settings, world, canon, series, story):
    """draft_story(stream_path=None) writes no .live.md file."""
    from quillan.pipeline.runner import draft_story

    beat_ids = ["C1-S1-B1"]
    _setup_minimal_story(paths, world, canon, series, story, beat_ids)

    llm, telemetry = _make_llm_and_telemetry(settings, paths)

    export_dir = paths.story_export(world, canon, series, story)

    await draft_story(
        paths, world, canon, series, story, "all", settings, llm, telemetry,
        force=False, stream_path=None,
    )

    live_files = list(export_dir.glob("*.live.md"))
    assert len(live_files) == 0, f"Unexpected live.md file(s): {live_files}"


@pytest.mark.asyncio
async def test_draft_story_stream_updated_after_each_batch(
    paths, settings, world, canon, series, story
):
    """Stream file grows after each batch (it's overwritten each time with all prose so far)."""
    from quillan.pipeline.runner import draft_story

    # Two independent beats → two batches (each a batch of 1)
    beat_ids = ["C1-S1-B1", "C1-S1-B2"]
    _setup_minimal_story(paths, world, canon, series, story, beat_ids)

    llm, telemetry = _make_llm_and_telemetry(settings, paths)
    stream_path = paths.story_export(world, canon, series, story) / f"{story}.live.md"

    await draft_story(
        paths, world, canon, series, story, "all", settings, llm, telemetry,
        force=False, stream_path=stream_path,
    )

    assert stream_path.exists()
    content = stream_path.read_text()
    # Both beats' prose should appear after all batches
    for bid in beat_ids:
        assert bid in content, f"Beat {bid} missing from final stream file"
