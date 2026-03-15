"""Integration tests for draft_story() pipeline orchestration.

Uses fully-mocked Phase 1 and Phase 2 internals so no LLM calls are made.
Tests the runner's orchestration logic: batching, error isolation, explicit
beat filtering, DraftResult population, and state checkpointing.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import yaml

from quillan.config import Settings
from quillan.paths import Paths
from quillan.pipeline.runner import DraftResult, draft_story
from quillan.telemetry import Telemetry


# ── Test helpers ───────────────────────────────────────────────────────────────

def _settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path, llm_cache=False, telemetry=False)


def _telemetry(tmp_path: Path) -> Telemetry:
    return Telemetry(tmp_path / ".runs", enabled=False)


def _make_dep_map_flat(beat_ids: list[str]) -> dict:
    """All beats independent — they all end up in a single batch."""
    return {"dependencies": {bid: [] for bid in beat_ids}}


def _make_dep_map_chain(beat_ids: list[str]) -> dict:
    """Linear chain — each beat depends on the previous one."""
    deps: dict[str, list[str]] = {bid: [] for bid in beat_ids}
    for i in range(1, len(beat_ids)):
        deps[beat_ids[i]] = [beat_ids[i - 1]]
    return {"dependencies": deps}


def _setup_story(
    paths: Paths,
    world: str,
    canon: str,
    series: str,
    story: str,
    dep_map: dict,
) -> None:
    dep_path = paths.dependency_map(world, canon, series, story)
    dep_path.parent.mkdir(parents=True, exist_ok=True)
    dep_path.write_text(json.dumps(dep_map))


# ── Basic DraftResult contract ─────────────────────────────────────────────────

async def test_draft_story_returns_draft_result(tmp_path: Path):
    """draft_story() returns a DraftResult — not None."""
    paths = Paths(tmp_path)
    world, canon, series, story = "w", "c", "s", "st"
    _setup_story(paths, world, canon, series, story, _make_dep_map_flat(["C1-S1-B1"]))

    with (
        patch("quillan.pipeline.runner._draft_and_audit_beat", new=AsyncMock()),
        patch("quillan.pipeline.runner._run_phase2_beat", new=AsyncMock()),
        patch("quillan.continuity.aggregator.run_aggregator", new=AsyncMock()),
    ):
        result = await draft_story(
            paths, world, canon, series, story,
            beats_mode="all",
            settings=_settings(tmp_path),
            llm=MagicMock(),
            telemetry=_telemetry(tmp_path),
        )

    assert isinstance(result, DraftResult)
    assert result.failed == {}
    assert not result.has_failures


async def test_empty_dep_map_returns_empty_result(tmp_path: Path):
    """An empty dep map returns an empty DraftResult immediately."""
    paths = Paths(tmp_path)
    world, canon, series, story = "w", "c", "s", "st"
    _setup_story(paths, world, canon, series, story, {"dependencies": {}})

    result = await draft_story(
        paths, world, canon, series, story,
        beats_mode="all",
        settings=_settings(tmp_path),
        llm=MagicMock(),
        telemetry=_telemetry(tmp_path),
    )

    assert result.completed == []
    assert result.failed == {}


# ── Beat-level error isolation ─────────────────────────────────────────────────

async def test_phase1_beat_failure_isolated(tmp_path: Path):
    """One beat failing in Phase 1 does not abort the other beats in the same batch."""
    paths = Paths(tmp_path)
    world, canon, series, story = "w", "c", "s", "st"
    beat_ids = ["C1-S1-B1", "C1-S1-B2", "C1-S1-B3"]
    # Flat dep map → single batch (all three attempted in parallel)
    _setup_story(paths, world, canon, series, story, _make_dep_map_flat(beat_ids))

    async def fake_phase1(
        paths, world, canon, series, story, beat_id, settings, llm, telemetry,
        throttled_until_ref, **kwargs
    ):
        if beat_id == "C1-S1-B2":
            raise RuntimeError("B2 exploded in Phase 1")

    with (
        patch("quillan.pipeline.runner._draft_and_audit_beat", new=fake_phase1),
        patch("quillan.pipeline.runner._run_phase2_beat", new=AsyncMock()),
        patch("quillan.continuity.aggregator.run_aggregator", new=AsyncMock()),
    ):
        result = await draft_story(
            paths, world, canon, series, story,
            beats_mode="all",
            settings=_settings(tmp_path),
            llm=MagicMock(),
            telemetry=_telemetry(tmp_path),
        )

    assert "C1-S1-B2" in result.failed
    assert "B2 exploded in Phase 1" in result.failed["C1-S1-B2"]
    assert result.has_failures
    # B1 and B3 must have completed Phase 2 successfully
    assert "C1-S1-B1" in result.completed
    assert "C1-S1-B3" in result.completed


async def test_phase1_failure_prevents_phase2_for_that_beat(tmp_path: Path):
    """A beat that fails in Phase 1 is NOT passed to Phase 2."""
    paths = Paths(tmp_path)
    world, canon, series, story = "w", "c", "s", "st"
    _setup_story(paths, world, canon, series, story, _make_dep_map_flat(["C1-S1-B1"]))

    phase2_calls: list[str] = []

    async def fake_phase1(*args, **kwargs):
        raise RuntimeError("always fail phase 1")

    async def tracking_phase2(
        paths, world, canon, series, story, beat_id, *args, **kwargs
    ):
        phase2_calls.append(beat_id)

    with (
        patch("quillan.pipeline.runner._draft_and_audit_beat", new=fake_phase1),
        patch("quillan.pipeline.runner._run_phase2_beat", new=tracking_phase2),
        patch("quillan.continuity.aggregator.run_aggregator", new=AsyncMock()),
    ):
        result = await draft_story(
            paths, world, canon, series, story,
            beats_mode="all",
            settings=_settings(tmp_path),
            llm=MagicMock(),
            telemetry=_telemetry(tmp_path),
        )

    assert "C1-S1-B1" in result.failed
    assert phase2_calls == []  # Phase 2 never called for the failed beat


async def test_phase2_failure_captured_in_result(tmp_path: Path):
    """A Phase 2 exception is captured in DraftResult.failed — pipeline does not crash."""
    paths = Paths(tmp_path)
    world, canon, series, story = "w", "c", "s", "st"
    _setup_story(paths, world, canon, series, story, _make_dep_map_flat(["C1-S1-B1"]))

    async def boom_phase2(*args, **kwargs):
        raise RuntimeError("Phase 2 exploded")

    with (
        patch("quillan.pipeline.runner._draft_and_audit_beat", new=AsyncMock()),
        patch("quillan.pipeline.runner._run_phase2_beat", new=boom_phase2),
        patch("quillan.continuity.aggregator.run_aggregator", new=AsyncMock()),
    ):
        result = await draft_story(
            paths, world, canon, series, story,
            beats_mode="all",
            settings=_settings(tmp_path),
            llm=MagicMock(),
            telemetry=_telemetry(tmp_path),
        )

    assert "C1-S1-B1" in result.failed
    assert "Phase2" in result.failed["C1-S1-B1"]
    assert "Phase 2 exploded" in result.failed["C1-S1-B1"]


# ── explicit_beats filtering ────────────────────────────────────────────────────

async def test_explicit_beats_restricts_processing(tmp_path: Path):
    """explicit_beats=[B1, B3] — only B1 and B3 are drafted, not B2."""
    paths = Paths(tmp_path)
    world, canon, series, story = "w", "c", "s", "st"
    beat_ids = ["C1-S1-B1", "C1-S1-B2", "C1-S1-B3"]
    _setup_story(paths, world, canon, series, story, _make_dep_map_flat(beat_ids))

    drafted: list[str] = []

    async def tracking_phase1(
        paths, world, canon, series, story, beat_id, *args, **kwargs
    ):
        drafted.append(beat_id)

    with (
        patch("quillan.pipeline.runner._draft_and_audit_beat", new=tracking_phase1),
        patch("quillan.pipeline.runner._run_phase2_beat", new=AsyncMock()),
        patch("quillan.continuity.aggregator.run_aggregator", new=AsyncMock()),
    ):
        await draft_story(
            paths, world, canon, series, story,
            beats_mode="all",
            settings=_settings(tmp_path),
            llm=MagicMock(),
            telemetry=_telemetry(tmp_path),
            explicit_beats=["C1-S1-B1", "C1-S1-B3"],
        )

    assert "C1-S1-B2" not in drafted
    assert set(drafted) == {"C1-S1-B1", "C1-S1-B3"}


async def test_explicit_beats_unknown_ids_ignored(tmp_path: Path):
    """explicit_beats with an ID not in the dep map silently produces an empty run."""
    paths = Paths(tmp_path)
    world, canon, series, story = "w", "c", "s", "st"
    _setup_story(paths, world, canon, series, story, _make_dep_map_flat(["C1-S1-B1"]))

    with (
        patch("quillan.pipeline.runner._draft_and_audit_beat", new=AsyncMock()),
        patch("quillan.pipeline.runner._run_phase2_beat", new=AsyncMock()),
        patch("quillan.continuity.aggregator.run_aggregator", new=AsyncMock()),
    ):
        result = await draft_story(
            paths, world, canon, series, story,
            beats_mode="all",
            settings=_settings(tmp_path),
            llm=MagicMock(),
            telemetry=_telemetry(tmp_path),
            explicit_beats=["X-NONEXISTENT"],
        )

    assert result.completed == []
    assert result.failed == {}


# ── State checkpointing ────────────────────────────────────────────────────────

async def test_checkpoint_written_before_state_update(tmp_path: Path):
    """A timestamped checkpoint file is written to state/checkpoints/ before the state update."""
    paths = Paths(tmp_path)
    world, canon, series, story = "w", "c", "s", "st"
    beat_id = "C1-S1-B1"
    _setup_story(paths, world, canon, series, story, _make_dep_map_flat([beat_id]))

    # Write an existing state file so there is something to checkpoint
    state_path = paths.state_current(world, canon, series, story)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    existing_state = {"characters": {"Alice": {"location": "home"}}, "events": []}
    state_path.write_text(yaml.dump(existing_state))

    async def fake_extract(*args, **kwargs):
        return {"set": {}, "append": {}, "delete": []}

    with (
        patch("quillan.pipeline.runner._draft_and_audit_beat", new=AsyncMock()),
        patch("quillan.continuity.state.extract_state_patch", new=AsyncMock(return_value={"set": {}, "append": {}, "delete": []})),
        patch("quillan.continuity.queue.enqueue_delta"),
        patch("quillan.continuity.aggregator.run_aggregator", new=AsyncMock()),
    ):
        await draft_story(
            paths, world, canon, series, story,
            beats_mode="all",
            settings=_settings(tmp_path),
            llm=MagicMock(),
            telemetry=_telemetry(tmp_path),
        )

    ckpt_dir = paths.state_checkpoints_dir(world, canon, series, story)
    checkpoints = list(ckpt_dir.glob(f"*_{beat_id}.yaml"))
    assert len(checkpoints) == 1, "Expected exactly one checkpoint file"
    # Checkpoint content must match the state that existed BEFORE the update
    saved = yaml.safe_load(checkpoints[0].read_text())
    assert saved["characters"]["Alice"]["location"] == "home"


async def test_no_checkpoint_when_state_file_absent(tmp_path: Path):
    """No checkpoint is written when there is no existing current_state.yaml."""
    paths = Paths(tmp_path)
    world, canon, series, story = "w", "c", "s", "st"
    beat_id = "C1-S1-B1"
    _setup_story(paths, world, canon, series, story, _make_dep_map_flat([beat_id]))

    # Do NOT write a state file — this is the first beat of a fresh story

    with (
        patch("quillan.pipeline.runner._draft_and_audit_beat", new=AsyncMock()),
        patch("quillan.continuity.state.extract_state_patch", new=AsyncMock(return_value={"set": {}, "append": {}, "delete": []})),
        patch("quillan.continuity.queue.enqueue_delta"),
        patch("quillan.continuity.aggregator.run_aggregator", new=AsyncMock()),
    ):
        await draft_story(
            paths, world, canon, series, story,
            beats_mode="all",
            settings=_settings(tmp_path),
            llm=MagicMock(),
            telemetry=_telemetry(tmp_path),
        )

    ckpt_dir = paths.state_checkpoints_dir(world, canon, series, story)
    assert not ckpt_dir.exists() or list(ckpt_dir.iterdir()) == []


# ── Schema version in initial state ───────────────────────────────────────────

async def test_initial_state_has_schema_version(tmp_path: Path):
    """When no prior state exists, the written state contains _meta.schema_version = 1."""
    paths = Paths(tmp_path)
    world, canon, series, story = "w", "c", "s", "st"
    beat_id = "C1-S1-B1"
    _setup_story(paths, world, canon, series, story, _make_dep_map_flat([beat_id]))

    with (
        patch("quillan.pipeline.runner._draft_and_audit_beat", new=AsyncMock()),
        patch("quillan.continuity.state.extract_state_patch", new=AsyncMock(return_value={"set": {}, "append": {}, "delete": []})),
        patch("quillan.continuity.queue.enqueue_delta"),
        patch("quillan.continuity.aggregator.run_aggregator", new=AsyncMock()),
    ):
        await draft_story(
            paths, world, canon, series, story,
            beats_mode="all",
            settings=_settings(tmp_path),
            llm=MagicMock(),
            telemetry=_telemetry(tmp_path),
        )

    state_path = paths.state_current(world, canon, series, story)
    assert state_path.exists()
    state_data = yaml.safe_load(state_path.read_text())
    assert state_data.get("_meta", {}).get("schema_version") == 1
