"""Tests for the 'status' CLI command."""

from __future__ import annotations

import time
import yaml
from click.testing import CliRunner

from quillan.cli import main


def _make_runner():
    return CliRunner()


def _base_args(data_dir: str, world: str = "w", canon: str = "c", series: str = "s"):
    return ["--data-dir", data_dir, "--world", world, "--canon", canon, "--series", series]


def _write_outline(paths, world, canon, series, story, beat_ids: list[str]) -> None:
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


# ── story-not-found guard ──────────────────────────────────────────────────────

def test_status_story_not_found(tmp_path):
    """status exits 1 and prints an error when the story directory does not exist."""
    runner = _make_runner()
    result = runner.invoke(
        main,
        _base_args(str(tmp_path)) + ["status", "ghost_story"],
    )
    assert result.exit_code == 1
    assert "not found" in result.output


# ── artifact presence flags ────────────────────────────────────────────────────

def test_status_shows_checkmarks_for_present_artifacts(tmp_path, paths, world, canon, series, story):
    """Existing planning artifacts get ✓; missing ones get ✗."""
    import yaml as _yaml

    # Create the story directory tree
    paths.story_planning(world, canon, series, story).mkdir(parents=True, exist_ok=True)
    paths.story_structure(world, canon, series, story).mkdir(parents=True, exist_ok=True)

    # Write only the creative brief
    brief = {
        "voice": {"prose_style": "clear", "pov": "third", "characteristic_patterns": [], "avoid": []},
        "tone_palette": [], "themes": [], "motifs": [], "arc_intent": "test",
    }
    paths.creative_brief(world, canon, series, story).write_text(_yaml.dump(brief))

    runner = _make_runner()
    result = runner.invoke(
        main,
        ["--data-dir", str(paths.data_dir), "--world", world,
         "--canon", canon, "--series", series, "status", story],
    )
    assert result.exit_code == 0
    output = result.output
    assert "✓" in output   # brief present
    assert "✗" in output   # others missing


# ── beat coverage counts ───────────────────────────────────────────────────────

def test_status_beat_coverage_all_specs_no_drafts(tmp_path, paths, world, canon, series, story):
    """Status shows correct spec and draft counts."""
    beat_ids = ["C1-S1-B1", "C1-S1-B2", "C1-S1-B3"]
    paths.story_structure(world, canon, series, story).mkdir(parents=True, exist_ok=True)
    paths.story_planning(world, canon, series, story).mkdir(parents=True, exist_ok=True)
    _write_outline(paths, world, canon, series, story, beat_ids)

    # Write specs for all beats, draft for only one
    for bid in beat_ids:
        spec_path = paths.beat_spec(world, canon, series, story, bid)
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(f"beat_id: {bid}\n")

    draft_path = paths.beat_draft(world, canon, series, story, "C1-S1-B1")
    draft_path.write_text("# Draft\n\nSome prose.\n")

    runner = _make_runner()
    result = runner.invoke(
        main,
        ["--data-dir", str(paths.data_dir), "--world", world,
         "--canon", canon, "--series", series, "status", story],
    )
    assert result.exit_code == 0
    output = result.output
    assert "3 / 3" in output   # all specs present
    assert "1 / 3" in output   # one draft


def test_status_no_outline_shows_hint(tmp_path, paths, world, canon, series, story):
    """When no outline exists, status says to run 'create'."""
    paths.story(world, canon, series, story).mkdir(parents=True, exist_ok=True)

    runner = _make_runner()
    result = runner.invoke(
        main,
        ["--data-dir", str(paths.data_dir), "--world", world,
         "--canon", canon, "--series", series, "status", story],
    )
    assert result.exit_code == 0
    assert "create" in result.output


# ── exports section ────────────────────────────────────────────────────────────

def test_status_shows_export_files(tmp_path, paths, world, canon, series, story):
    """Export files are listed with their sizes."""
    paths.story(world, canon, series, story).mkdir(parents=True, exist_ok=True)
    export_dir = paths.story_export(world, canon, series, story)
    export_dir.mkdir(parents=True, exist_ok=True)
    (export_dir / "my_story.md").write_text("# Story\n\nContent.\n")

    runner = _make_runner()
    result = runner.invoke(
        main,
        ["--data-dir", str(paths.data_dir), "--world", world,
         "--canon", canon, "--series", series, "status", story],
    )
    assert result.exit_code == 0
    assert "my_story.md" in result.output


def test_status_no_exports_shows_none(tmp_path, paths, world, canon, series, story):
    """When no exports exist, status says '(none)'."""
    paths.story(world, canon, series, story).mkdir(parents=True, exist_ok=True)

    runner = _make_runner()
    result = runner.invoke(
        main,
        ["--data-dir", str(paths.data_dir), "--world", world,
         "--canon", canon, "--series", series, "status", story],
    )
    assert result.exit_code == 0
    assert "(none)" in result.output


# ── stale draft detection ──────────────────────────────────────────────────────


def _write_spec_then_draft(paths, world, canon, series, story, bid: str) -> None:
    """Write spec, sleep, write draft → draft is fresh (not stale)."""
    spec_path = paths.beat_spec(world, canon, series, story, bid)
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(f"beat_id: {bid}\n")
    time.sleep(0.01)
    draft_path = paths.beat_draft(world, canon, series, story, bid)
    draft_path.write_text(f"# Draft {bid}\n\nFresh prose.\n")


def _write_draft_then_spec(paths, world, canon, series, story, bid: str) -> None:
    """Write draft, sleep, write spec → spec is newer (stale)."""
    spec_path = paths.beat_spec(world, canon, series, story, bid)
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path = paths.beat_draft(world, canon, series, story, bid)
    draft_path.write_text(f"# Draft {bid}\n\nOld prose.\n")
    time.sleep(0.01)
    spec_path.write_text(f"beat_id: {bid}\n")


def test_status_shows_stale_count(paths, world, canon, series, story):
    """When a stale beat exists, status shows the Stale line with the count and hint."""
    beat_ids = ["C1-S1-B1", "C1-S1-B2"]
    paths.story_structure(world, canon, series, story).mkdir(parents=True, exist_ok=True)
    paths.story_planning(world, canon, series, story).mkdir(parents=True, exist_ok=True)
    _write_outline(paths, world, canon, series, story, beat_ids)

    # B1: stale; B2: fresh
    _write_draft_then_spec(paths, world, canon, series, story, "C1-S1-B1")
    _write_spec_then_draft(paths, world, canon, series, story, "C1-S1-B2")

    runner = _make_runner()
    result = runner.invoke(
        main,
        ["--data-dir", str(paths.data_dir), "--world", world,
         "--canon", canon, "--series", series, "status", story],
    )
    assert result.exit_code == 0
    assert "Stale" in result.output
    assert "stale-only" in result.output


def test_status_no_stale_hides_stale_line(paths, world, canon, series, story):
    """When no beats are stale, the Stale line is absent from status output."""
    beat_ids = ["C1-S1-B1", "C1-S1-B2"]
    paths.story_structure(world, canon, series, story).mkdir(parents=True, exist_ok=True)
    paths.story_planning(world, canon, series, story).mkdir(parents=True, exist_ok=True)
    _write_outline(paths, world, canon, series, story, beat_ids)

    # Both fresh
    for bid in beat_ids:
        _write_spec_then_draft(paths, world, canon, series, story, bid)

    runner = _make_runner()
    result = runner.invoke(
        main,
        ["--data-dir", str(paths.data_dir), "--world", world,
         "--canon", canon, "--series", series, "status", story],
    )
    assert result.exit_code == 0
    assert "Stale" not in result.output


def test_status_lists_stale_beat_ids(paths, world, canon, series, story):
    """When ≤5 beats are stale, their IDs are listed inline below the Stale line."""
    beat_ids = ["C1-S1-B1", "C1-S1-B2", "C1-S1-B3"]
    paths.story_structure(world, canon, series, story).mkdir(parents=True, exist_ok=True)
    paths.story_planning(world, canon, series, story).mkdir(parents=True, exist_ok=True)
    _write_outline(paths, world, canon, series, story, beat_ids)

    # All three stale
    for bid in beat_ids:
        _write_draft_then_spec(paths, world, canon, series, story, bid)

    runner = _make_runner()
    result = runner.invoke(
        main,
        ["--data-dir", str(paths.data_dir), "--world", world,
         "--canon", canon, "--series", series, "status", story],
    )
    assert result.exit_code == 0
    for bid in beat_ids:
        assert bid in result.output
