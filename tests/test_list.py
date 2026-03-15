"""Tests for the 'list' CLI command."""

from __future__ import annotations

import yaml
from click.testing import CliRunner

from quillan.cli import main


def _runner():
    return CliRunner()


def _base_args(data_dir: str):
    return ["--data-dir", data_dir]


def _make_story(
    paths,
    world: str,
    canon: str,
    series: str,
    story: str,
    beat_ids: list[str] | None = None,
    drafted: list[str] | None = None,
    export_files: list[str] | None = None,
) -> None:
    """Create a minimal story structure for testing."""
    beat_ids = beat_ids or ["C1-S1-B1", "C1-S1-B2"]
    drafted = drafted or []
    export_files = export_files or []

    # Outline
    outline_path = paths.outline(world, canon, series, story)
    outline_path.parent.mkdir(parents=True, exist_ok=True)
    beats_data = [
        {"beat_id": bid, "title": f"Beat {bid}", "goal": "test", "characters": []}
        for bid in beat_ids
    ]
    outline_data = {
        "title": story.replace("_", " ").title(),
        "genre": "Fiction",
        "theme": "TBD",
        "chapters": [{"chapter": 1, "title": "Act 1", "beats": beats_data}],
    }
    outline_path.write_text(yaml.dump(outline_data))

    # Drafted beats
    for bid in drafted:
        draft_path = paths.beat_draft(world, canon, series, story, bid)
        draft_path.parent.mkdir(parents=True, exist_ok=True)
        draft_path.write_text(f"# {bid}\n\nSome prose.\n")

    # Export files
    if export_files:
        export_dir = paths.story_export(world, canon, series, story)
        export_dir.mkdir(parents=True, exist_ok=True)
        for fname in export_files:
            (export_dir / fname).write_text("content")


# ── no stories ─────────────────────────────────────────────────────────────────

def test_list_no_stories(tmp_path):
    """list with no stories prints a helpful message."""
    result = _runner().invoke(main, _base_args(str(tmp_path)) + ["list"])
    assert result.exit_code == 0
    assert "No stories found" in result.output


def test_list_no_stories_suggests_create(tmp_path):
    result = _runner().invoke(main, _base_args(str(tmp_path)) + ["list"])
    assert "create" in result.output


# ── single story ────────────────────────────────────────────────────────────────

def test_list_shows_story(tmp_path, paths, world, canon, series, story):
    """A story with some drafts shows up in the table."""
    _make_story(
        paths, world, canon, series, story,
        beat_ids=["C1-S1-B1", "C1-S1-B2", "C1-S1-B3"],
        drafted=["C1-S1-B1"],
    )
    result = _runner().invoke(
        main,
        _base_args(str(paths.data_dir)) + ["list"],
    )
    assert result.exit_code == 0
    assert story in result.output
    assert world in result.output


def test_list_shows_beat_counts(tmp_path, paths, world, canon, series, story):
    """list shows total and drafted beat counts."""
    _make_story(
        paths, world, canon, series, story,
        beat_ids=["C1-S1-B1", "C1-S1-B2"],
        drafted=["C1-S1-B1"],
    )
    result = _runner().invoke(
        main,
        _base_args(str(paths.data_dir)) + ["list"],
    )
    assert result.exit_code == 0
    # "1/2" or "50%" somewhere in the output
    output = result.output
    assert "1/2" in output or "50%" in output


def test_list_shows_export_count(tmp_path, paths, world, canon, series, story):
    """list shows non-zero export count when exports exist."""
    _make_story(
        paths, world, canon, series, story,
        export_files=["story.epub", "story.md"],
    )
    result = _runner().invoke(
        main,
        _base_args(str(paths.data_dir)) + ["list"],
    )
    assert result.exit_code == 0
    assert "2" in result.output  # 2 exports


def test_list_zero_drafts_all_beats_present(tmp_path, paths, world, canon, series, story):
    """A story with no drafts at all still shows correctly."""
    _make_story(paths, world, canon, series, story, beat_ids=["C1-S1-B1"])
    result = _runner().invoke(
        main,
        _base_args(str(paths.data_dir)) + ["list"],
    )
    assert result.exit_code == 0
    assert story in result.output


# ── multiple stories ────────────────────────────────────────────────────────────

def test_list_multiple_worlds(tmp_path, paths):
    """Multiple stories across different worlds are all listed."""
    _make_story(paths, "worldA", "default", "default", "story1")
    _make_story(paths, "worldB", "default", "default", "story2")

    result = _runner().invoke(main, _base_args(str(paths.data_dir)) + ["list"])
    assert result.exit_code == 0
    assert "worldA" in result.output
    assert "worldB" in result.output
    assert "story1" in result.output
    assert "story2" in result.output


# ── filters ────────────────────────────────────────────────────────────────────

def test_list_filter_world(tmp_path, paths):
    """--world filter shows only the matching world."""
    _make_story(paths, "noir", "default", "default", "detective_story")
    _make_story(paths, "scifi", "default", "default", "space_opera")

    result = _runner().invoke(
        main,
        _base_args(str(paths.data_dir)) + ["list", "--world", "noir"],
    )
    assert result.exit_code == 0
    assert "detective_story" in result.output
    assert "space_opera" not in result.output


def test_list_filter_world_no_match(tmp_path, paths):
    """--world filter with no matching world shows 'No stories found'."""
    _make_story(paths, "noir", "default", "default", "story1")

    result = _runner().invoke(
        main,
        _base_args(str(paths.data_dir)) + ["list", "--world", "fantasy"],
    )
    assert result.exit_code == 0
    assert "No stories found" in result.output


def test_list_filter_series(tmp_path, paths):
    """--series filter shows only stories in the matching series."""
    _make_story(paths, "default", "default", "trilogy", "book1")
    _make_story(paths, "default", "default", "standalone", "oneshot")

    result = _runner().invoke(
        main,
        _base_args(str(paths.data_dir)) + ["list", "--series", "trilogy"],
    )
    assert result.exit_code == 0
    assert "book1" in result.output
    assert "oneshot" not in result.output
