"""Tests for F9 — Plugin/Hook System (quillan/hooks.py)."""

from __future__ import annotations

import stat

import pytest
from click.testing import CliRunner

from quillan.hooks import (
    HOOK_EVENTS,
    _build_env,
    discover_hooks,
    run_hooks,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_story(paths, world, canon, series, story):
    paths.story(world, canon, series, story).mkdir(parents=True, exist_ok=True)


def _install_hook(directory, event: str, script_body: str = "#!/bin/sh\necho 'hook ran'\n") -> None:
    """Create an executable hook script in *directory*."""
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / f"{event}.sh"
    script.write_text(script_body, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


# ── HOOK_EVENTS ───────────────────────────────────────────────────────────────

def test_hook_events_contains_expected():
    assert "post_beat" in HOOK_EVENTS
    assert "post_draft" in HOOK_EVENTS
    assert "post_create" in HOOK_EVENTS
    assert "post_revise" in HOOK_EVENTS
    assert "post_ingest" in HOOK_EVENTS
    assert "post_continuity_check" in HOOK_EVENTS


# ── _build_env ────────────────────────────────────────────────────────────────

def test_build_env_contains_core_vars(paths, world, canon, series, story):
    env = _build_env("post_beat", paths, world, canon, series, story, None)
    assert env["QUILLAN_EVENT"] == "post_beat"
    assert env["QUILLAN_STORY"] == story
    assert env["QUILLAN_WORLD"] == world
    assert env["QUILLAN_CANON"] == canon
    assert env["QUILLAN_SERIES"] == series
    assert env["QUILLAN_DATA_DIR"] == str(paths.data_dir)


def test_build_env_merges_extra(paths, world, canon, series, story):
    env = _build_env("post_beat", paths, world, canon, series, story,
                     {"QUILLAN_BEAT_ID": "C1-S1-B1"})
    assert env["QUILLAN_BEAT_ID"] == "C1-S1-B1"


def test_build_env_inherits_process_env(paths, world, canon, series, story, monkeypatch):
    monkeypatch.setenv("MY_CUSTOM_VAR", "hello")
    env = _build_env("post_create", paths, world, canon, series, story, None)
    assert env["MY_CUSTOM_VAR"] == "hello"


# ── discover_hooks ────────────────────────────────────────────────────────────

def test_discover_hooks_empty_dirs(paths, world, canon, series, story):
    _make_story(paths, world, canon, series, story)
    result = discover_hooks("post_beat", paths, world, canon, series, story)
    assert result == []


def test_discover_hooks_story_level(paths, world, canon, series, story):
    _make_story(paths, world, canon, series, story)
    hooks_dir = paths.story_hooks_dir(world, canon, series, story)
    _install_hook(hooks_dir, "post_beat")
    result = discover_hooks("post_beat", paths, world, canon, series, story)
    assert len(result) == 1
    assert result[0].name == "post_beat.sh"


def test_discover_hooks_world_level(paths, world, canon, series, story):
    _make_story(paths, world, canon, series, story)
    _install_hook(paths.world_hooks_dir(world), "post_draft")
    result = discover_hooks("post_draft", paths, world, canon, series, story)
    assert len(result) == 1


def test_discover_hooks_global_level(paths, world, canon, series, story):
    _make_story(paths, world, canon, series, story)
    _install_hook(paths.global_hooks_dir(), "post_create")
    result = discover_hooks("post_create", paths, world, canon, series, story)
    assert len(result) == 1


def test_discover_hooks_all_three_tiers(paths, world, canon, series, story):
    """All three tiers are returned when all have the same event hook."""
    _make_story(paths, world, canon, series, story)
    _install_hook(paths.story_hooks_dir(world, canon, series, story), "post_beat")
    _install_hook(paths.world_hooks_dir(world), "post_beat")
    _install_hook(paths.global_hooks_dir(), "post_beat")
    result = discover_hooks("post_beat", paths, world, canon, series, story)
    assert len(result) == 3


def test_discover_hooks_order_story_first(paths, world, canon, series, story):
    """Story-level hook comes before world-level, world before global."""
    _make_story(paths, world, canon, series, story)
    _install_hook(paths.story_hooks_dir(world, canon, series, story), "post_beat")
    _install_hook(paths.global_hooks_dir(), "post_beat")
    result = discover_hooks("post_beat", paths, world, canon, series, story)
    assert len(result) == 2
    # Story hook path contains "stories"
    assert "stories" in str(result[0])


def test_discover_hooks_non_executable_ignored(paths, world, canon, series, story):
    """Non-executable scripts are not returned."""
    _make_story(paths, world, canon, series, story)
    hooks_dir = paths.story_hooks_dir(world, canon, series, story)
    hooks_dir.mkdir(parents=True, exist_ok=True)
    script = hooks_dir / "post_beat.sh"
    script.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    # Deliberately NOT making it executable
    script.chmod(0o644)
    result = discover_hooks("post_beat", paths, world, canon, series, story)
    assert result == []


def test_discover_hooks_unknown_event_returns_empty(paths, world, canon, series, story):
    result = discover_hooks("nonexistent_event", paths, world, canon, series, story)
    assert result == []


# ── run_hooks ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_hooks_executes_script(paths, world, canon, series, story, tmp_path):
    """A hook script runs and its side-effect (writing a file) is visible."""
    _make_story(paths, world, canon, series, story)
    sentinel = tmp_path / "hook_ran.txt"
    _install_hook(
        paths.story_hooks_dir(world, canon, series, story),
        "post_beat",
        f"#!/bin/sh\ntouch {sentinel}\n",
    )
    await run_hooks("post_beat", paths, world, canon, series, story)
    assert sentinel.exists()


@pytest.mark.asyncio
async def test_run_hooks_passes_env_vars(paths, world, canon, series, story, tmp_path):
    """Environment variables are available inside the hook script."""
    _make_story(paths, world, canon, series, story)
    out_file = tmp_path / "env_out.txt"
    _install_hook(
        paths.story_hooks_dir(world, canon, series, story),
        "post_beat",
        f'#!/bin/sh\necho "$QUILLAN_BEAT_ID" > {out_file}\n',
    )
    await run_hooks(
        "post_beat", paths, world, canon, series, story,
        extra_env={"QUILLAN_BEAT_ID": "C1-S1-B1"},
    )
    assert out_file.read_text().strip() == "C1-S1-B1"


@pytest.mark.asyncio
async def test_run_hooks_no_hooks_is_noop(paths, world, canon, series, story):
    """run_hooks with no scripts installed completes without error."""
    _make_story(paths, world, canon, series, story)
    await run_hooks("post_create", paths, world, canon, series, story)  # no exception


@pytest.mark.asyncio
async def test_run_hooks_failing_script_does_not_raise(paths, world, canon, series, story):
    """A hook that exits non-zero logs a warning but does not propagate."""
    _make_story(paths, world, canon, series, story)
    _install_hook(
        paths.story_hooks_dir(world, canon, series, story),
        "post_beat",
        "#!/bin/sh\nexit 1\n",
    )
    # Should not raise
    await run_hooks("post_beat", paths, world, canon, series, story)


@pytest.mark.asyncio
async def test_run_hooks_all_three_tiers_run(paths, world, canon, series, story, tmp_path):
    """All three tiers fire for a single event."""
    _make_story(paths, world, canon, series, story)
    counters = [tmp_path / f"c{i}.txt" for i in range(3)]
    _install_hook(paths.story_hooks_dir(world, canon, series, story), "post_draft",
                  f"#!/bin/sh\ntouch {counters[0]}\n")
    _install_hook(paths.world_hooks_dir(world), "post_draft",
                  f"#!/bin/sh\ntouch {counters[1]}\n")
    _install_hook(paths.global_hooks_dir(), "post_draft",
                  f"#!/bin/sh\ntouch {counters[2]}\n")
    await run_hooks("post_draft", paths, world, canon, series, story)
    assert all(c.exists() for c in counters)


# ── runner integration: on_beat_complete ──────────────────────────────────────

@pytest.mark.asyncio
async def test_on_beat_complete_called_per_beat(paths, world, canon, series, story, settings):
    """on_beat_complete fires once per successfully drafted beat."""
    import json
    import yaml
    from quillan.pipeline.runner import draft_story

    # Set up minimal story structure
    beat_id = "C1-S1-B1"
    spec = paths.beat_spec(world, canon, series, story, beat_id)
    paths.ensure(spec)
    spec.write_text(yaml.dump({"beat_id": beat_id, "goal": "Test beat",
                                "word_count_target": 50}), encoding="utf-8")

    dep_path = paths.dependency_map(world, canon, series, story)
    paths.ensure(dep_path)
    dep_path.write_text(json.dumps({"dependencies": {beat_id: []}}), encoding="utf-8")

    completed_beats: list[str] = []

    async def _on_complete(bid: str) -> None:
        completed_beats.append(bid)

    # Offline LLM (no API keys) — stubs the draft
    class _OfflineTel:
        def record_phase_time(self, *a): pass
        def record_call(self, *a): pass
        def record_cache_hit(self, *a): pass

    _settings_ref = settings

    class _OfflineLLM:
        settings = _settings_ref  # has_api_keys = False
        telemetry = _OfflineTel()

    await draft_story(
        paths, world, canon, series, story,
        beats_mode="all",
        settings=settings,
        llm=_OfflineLLM(),
        telemetry=_OfflineTel(),
        on_beat_complete=_on_complete,
    )

    assert beat_id in completed_beats


# ── CLI: hooks list ───────────────────────────────────────────────────────────

def test_cli_hooks_list_no_hooks(tmp_path):
    from quillan.cli import main
    from quillan.paths import Paths

    p = Paths(tmp_path)
    _make_story(p, "w", "c", "s", "mystory")

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--data-dir", str(tmp_path), "--world", "w", "--canon", "c",
         "--series", "s", "hooks", "mystory"],
    )
    assert result.exit_code == 0
    assert "No hooks installed" in result.output


def test_cli_hooks_list_shows_installed(tmp_path):
    from quillan.cli import main
    from quillan.paths import Paths

    p = Paths(tmp_path)
    _make_story(p, "w", "c", "s", "mystory")
    _install_hook(p.story_hooks_dir("w", "c", "s", "mystory"), "post_beat")

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--data-dir", str(tmp_path), "--world", "w", "--canon", "c",
         "--series", "s", "hooks", "mystory"],
    )
    assert result.exit_code == 0
    assert "post_beat" in result.output


def test_cli_hooks_list_shows_supported_events(tmp_path):
    from quillan.cli import main
    from quillan.paths import Paths

    p = Paths(tmp_path)
    _make_story(p, "w", "c", "s", "mystory")

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--data-dir", str(tmp_path), "--world", "w", "--canon", "c",
         "--series", "s", "hooks", "mystory"],
    )
    assert "Supported events" in result.output
    assert "post_beat" in result.output
