"""Tests for the CLI commands: selftest, status, list, export, delete, dry-run."""

from __future__ import annotations

import json
from unittest.mock import patch

import yaml
from click.testing import CliRunner

from quillan.cli import main
from quillan.paths import Paths


# ── Helpers ────────────────────────────────────────────────────────────────────

def _args(data_dir, world="w", canon="c", series="s"):
    return ["--data-dir", str(data_dir), "--world", world, "--canon", canon, "--series", series]


def _write_outline(paths: Paths, world, canon, series, story, beat_ids: list[str]) -> None:
    beats = [
        {"beat_id": bid, "title": f"Beat {bid}", "goal": "test", "characters": []}
        for bid in beat_ids
    ]
    outline = {
        "title": "Test Story",
        "genre": "Fiction",
        "theme": "testing",
        "chapters": [{"chapter": 1, "title": "Act 1", "beats": beats}],
    }
    p = paths.outline(world, canon, series, story)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.dump(outline))


def _write_dep_map(paths: Paths, world, canon, series, story, beat_ids: list[str]) -> None:
    deps = {bid: [] for bid in beat_ids}
    # Chain dependencies: each beat depends on the previous one
    for i in range(1, len(beat_ids)):
        deps[beat_ids[i]] = [beat_ids[i - 1]]
    dep_map = {"dependencies": deps}
    p = paths.dependency_map(world, canon, series, story)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(dep_map))


# ── selftest ────────────────────────────────────────────────────────────────────

def test_selftest_passes(tmp_path):
    """selftest exits 0 and reports all checks passed."""
    runner = CliRunner()
    result = runner.invoke(main, ["--data-dir", str(tmp_path), "selftest"])
    assert result.exit_code == 0, result.output
    assert "passed" in result.output.lower()


# ── status ───────────────────────────────────────────────────────────────────────

def test_status_story_not_found(tmp_path):
    """status exits 1 when story directory does not exist."""
    runner = CliRunner()
    result = runner.invoke(main, _args(tmp_path) + ["status", "no_such_story"])
    assert result.exit_code == 1
    assert "not found" in result.output.lower() or "error" in result.output.lower()


def test_status_shows_planning_artifacts(tmp_path):
    """status lists planning artifacts — at least headings show regardless of missing files."""
    paths = Paths(tmp_path)
    world, canon, series, story = "w", "c", "s", "mystory"
    paths.story(world, canon, series, story).mkdir(parents=True, exist_ok=True)

    runner = CliRunner()
    result = runner.invoke(main, _args(tmp_path) + ["status", story])
    assert result.exit_code == 0
    assert "Planning" in result.output


# ── list ─────────────────────────────────────────────────────────────────────────

def test_list_no_stories(tmp_path):
    """list with empty data dir prints 'No stories found.'"""
    runner = CliRunner()
    result = runner.invoke(main, ["--data-dir", str(tmp_path), "list"])
    assert result.exit_code == 0
    assert "No stories found" in result.output


def test_list_shows_story(tmp_path):
    """list shows a table row for an existing story."""
    paths = Paths(tmp_path)
    world, canon, series, story = "w", "c", "s", "mystory"
    paths.story(world, canon, series, story).mkdir(parents=True, exist_ok=True)
    _write_outline(paths, world, canon, series, story, ["C1-S1-B1", "C1-S1-B2"])

    runner = CliRunner()
    result = runner.invoke(main, ["--data-dir", str(tmp_path), "list"])
    assert result.exit_code == 0
    assert story in result.output


# ── export ────────────────────────────────────────────────────────────────────────

def test_export_missing_outline_exits_nonzero(tmp_path):
    """export exits 1 when the story has no Outline.yaml."""
    paths = Paths(tmp_path)
    world, canon, series, story = "w", "c", "s", "nooutline"
    paths.story(world, canon, series, story).mkdir(parents=True, exist_ok=True)

    runner = CliRunner()
    result = runner.invoke(
        main,
        _args(tmp_path) + ["export", story, "--format", "markdown"],
    )
    assert result.exit_code == 1


# ── delete ────────────────────────────────────────────────────────────────────────

def test_delete_requires_confirm_by_default(tmp_path):
    """delete without --force prompts; answering 'n' leaves the story intact."""
    paths = Paths(tmp_path)
    world, canon, series, story = "w", "c", "s", "deleteme"
    story_dir = paths.story(world, canon, series, story)
    story_dir.mkdir(parents=True, exist_ok=True)

    runner = CliRunner()
    runner.invoke(
        main,
        _args(tmp_path) + ["delete", story],
        input="n\n",
    )
    # Story directory must still exist after 'n'
    assert story_dir.exists(), "Story should not be deleted when user answers 'n'"


def test_delete_force_removes_story(tmp_path):
    """delete --force removes the story directory without prompting."""
    paths = Paths(tmp_path)
    world, canon, series, story = "w", "c", "s", "gonestory"
    story_dir = paths.story(world, canon, series, story)
    story_dir.mkdir(parents=True, exist_ok=True)
    (story_dir / "outline.yaml").write_text("title: Gone\n")

    runner = CliRunner()
    result = runner.invoke(
        main,
        _args(tmp_path) + ["delete", story, "--force"],
    )
    assert result.exit_code == 0, result.output
    assert not story_dir.exists(), "Story directory should be deleted with --force"
    assert "Deleted" in result.output


# ── cover (no-keys error path) ────────────────────────────────────────────────────

def test_cover_no_keys_no_image_exits(tmp_path):
    """cover exits 1 and shows a hint when no API key and no --image are provided."""
    paths = Paths(tmp_path)
    world, canon, series, story = "w", "c", "s", "covertest"
    paths.story(world, canon, series, story).mkdir(parents=True, exist_ok=True)

    runner = CliRunner()
    # Ensure no API keys bleed in from the environment
    import os
    clean_env = {k: v for k, v in os.environ.items()
                 if k not in ("OPENAI_API_KEY", "XAI_API_KEY", "GEMINI_API_KEY")}
    with patch.dict(os.environ, clean_env, clear=True):
        result = runner.invoke(
            main,
            _args(tmp_path) + ["cover", story],
        )
    assert result.exit_code == 1
    # Should mention either the key name or --image option as a hint
    assert "OPENAI_API_KEY" in result.output or "--image" in result.output


# ── draft --dry-run ────────────────────────────────────────────────────────────────

def test_draft_dry_run_prints_beats(tmp_path):
    """draft --dry-run prints beat IDs and exits 0 without writing any files."""
    paths = Paths(tmp_path)
    world, canon, series, story = "w", "c", "s", "dryrunstory"
    beat_ids = ["C1-S1-B1", "C1-S1-B2", "C1-S1-B3"]

    paths.story_structure(world, canon, series, story).mkdir(parents=True, exist_ok=True)
    _write_dep_map(paths, world, canon, series, story, beat_ids)

    runner = CliRunner()
    result = runner.invoke(
        main,
        _args(tmp_path) + ["draft", story, "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert "Dry run" in result.output
    for bid in beat_ids:
        assert bid in result.output

    # No beat drafts should have been written
    for bid in beat_ids:
        assert not paths.beat_draft(world, canon, series, story, bid).exists()


# ── N5: pre-flight API key check ───────────────────────────────────────────────

def test_create_exits_if_no_api_keys(tmp_path):
    """create exits 1 with a helpful message when no API keys are configured."""
    import tempfile

    runner = CliRunner()
    with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
        f.write("A detective story.\n")
        idea_file = f.name

    # Unset all API keys so has_api_keys is False
    with runner.isolated_filesystem():
        result = runner.invoke(
            main,
            ["--data-dir", str(tmp_path), "create", idea_file],
            env={
                "OPENAI_API_KEY": "",
                "XAI_API_KEY": "",
                "GEMINI_API_KEY": "",
                "QUILLAN_PLANNING_API_BASE": "",
                "QUILLAN_DRAFT_API_BASE": "",
                "QUILLAN_FORENSIC_API_BASE": "",
                "QUILLAN_STRUCT_API_BASE": "",
            },
            catch_exceptions=False,
        )

    assert result.exit_code == 1
    assert "API key" in result.output


def test_selftest_suggests_doctor(tmp_path):
    """selftest output suggests running 'quillan doctor' on success."""
    runner = CliRunner()
    result = runner.invoke(main, ["--data-dir", str(tmp_path), "selftest"])
    assert result.exit_code == 0, result.output
    assert "doctor" in result.output
