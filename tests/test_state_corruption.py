"""Tests for state file corruption detection and patch shape validation.

Covers:
- _validate_patch() rejects malformed set / append / delete fields
- apply_state_patch() propagates those validation errors
- A corrupted current_state.yaml is detected as a pre-flight RuntimeError
  before any LLM calls are made (N8 early detection)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from quillan.continuity.state import _validate_patch, apply_state_patch


# ── _validate_patch — shape rejection ─────────────────────────────────────────

def test_validate_patch_rejects_set_not_dict():
    """'set' must be a dict; a string value raises ValueError."""
    with pytest.raises(ValueError, match="'set' must be a dict"):
        _validate_patch({"set": "not a dict", "append": {}, "delete": []})


def test_validate_patch_rejects_append_not_dict():
    """'append' must be a dict; a list value raises ValueError."""
    with pytest.raises(ValueError, match="'append' must be a dict"):
        _validate_patch({"set": {}, "append": ["nope"], "delete": []})


def test_validate_patch_rejects_delete_not_list():
    """'delete' must be a list; a string value raises ValueError."""
    with pytest.raises(ValueError, match="'delete' must be a list"):
        _validate_patch({"set": {}, "append": {}, "delete": "bad"})


def test_validate_patch_accepts_empty_patch():
    """An empty dict patch (all fields absent) is valid."""
    _validate_patch({})  # must not raise


def test_validate_patch_accepts_valid_patch():
    """A well-formed patch passes validation."""
    _validate_patch({"set": {"foo.bar": "baz"}, "append": {"events": "x"}, "delete": ["old.key"]})


# ── apply_state_patch propagates validation errors ────────────────────────────

def test_apply_state_patch_raises_on_bad_set():
    """apply_state_patch raises ValueError when 'set' is not a dict."""
    with pytest.raises(ValueError, match="'set' must be a dict"):
        apply_state_patch({}, {"set": 42, "append": {}, "delete": []})


def test_apply_state_patch_raises_on_bad_delete():
    """apply_state_patch raises ValueError when 'delete' is not a list."""
    with pytest.raises(ValueError):
        apply_state_patch({}, {"set": {}, "append": {}, "delete": "oops"})


# ── YAML corruption → Phase2 failure in DraftResult ──────────────────────────

async def test_corrupted_state_file_raises_before_llm_calls(tmp_path: Path):
    """N8: A corrupted current_state.yaml raises RuntimeError before any LLM credits are spent.

    The pipeline should detect the corruption at startup (pre-flight check) and fail
    immediately with a message directing the user to 'restore-state'.
    """
    from quillan.config import Settings
    from quillan.paths import Paths
    from quillan.pipeline.runner import draft_story
    from quillan.telemetry import Telemetry

    paths = Paths(tmp_path)
    settings = Settings(data_dir=tmp_path, llm_cache=False, telemetry=False)
    tel = Telemetry(tmp_path / ".runs", enabled=False)
    world, canon, series, story = "w", "c", "s", "st"
    beat_id = "C1-S1-B1"

    dep_path = paths.dependency_map(world, canon, series, story)
    dep_path.parent.mkdir(parents=True, exist_ok=True)
    dep_path.write_text(json.dumps({"dependencies": {beat_id: []}}))

    # Write a state file with invalid YAML (unclosed flow sequence bracket)
    state_path = paths.state_current(world, canon, series, story)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("key: [unclosed bracket\n")

    draft_mock = AsyncMock()
    with (
        patch("quillan.pipeline.runner._draft_and_audit_beat", new=draft_mock),
    ):
        with pytest.raises(RuntimeError, match="orrupt"):
            await draft_story(
                paths, world, canon, series, story,
                beats_mode="all",
                settings=settings,
                llm=MagicMock(),
                telemetry=tel,
            )

    # No LLM calls should have been made
    draft_mock.assert_not_called()


async def test_corrupted_state_error_mentions_restore_state(tmp_path: Path):
    """N8: The RuntimeError from a corrupt state file mentions 'restore-state'."""
    from quillan.config import Settings
    from quillan.paths import Paths
    from quillan.pipeline.runner import draft_story
    from quillan.telemetry import Telemetry

    paths = Paths(tmp_path)
    settings = Settings(data_dir=tmp_path, llm_cache=False, telemetry=False)
    tel = Telemetry(tmp_path / ".runs", enabled=False)
    world, canon, series, story = "w", "c", "s", "st"
    beat_id = "C1-S1-B1"

    dep_path = paths.dependency_map(world, canon, series, story)
    dep_path.parent.mkdir(parents=True, exist_ok=True)
    dep_path.write_text(json.dumps({"dependencies": {beat_id: []}}))

    state_path = paths.state_current(world, canon, series, story)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("key: [unclosed\n")

    with pytest.raises(RuntimeError) as exc_info:
        await draft_story(
            paths, world, canon, series, story,
            beats_mode="all",
            settings=settings,
            llm=MagicMock(),
            telemetry=tel,
        )

    assert "restore-state" in str(exc_info.value)
