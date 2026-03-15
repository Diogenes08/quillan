"""Tests for quillan.continuity.aggregator."""

from __future__ import annotations

import json
import time
import pytest


class _FakeLLM:
    class settings:
        has_api_keys = False


class _FakeLLMWithKeys:
    """Fake LLM with API keys and a controllable call_json mock."""

    class settings:
        has_api_keys = True

    def __init__(self, side_effects=None):
        """side_effects: list of return values or exceptions for successive call_json calls."""
        self._call_count = 0
        self._side_effects = side_effects or []
        self._calls: list[dict] = []

    async def call_json(self, stage, system, user, required_keys=None):
        idx = self._call_count
        self._call_count += 1
        self._calls.append({"stage": stage, "system": system, "user": user, "required_keys": required_keys})
        if idx < len(self._side_effects):
            effect = self._side_effects[idx]
            if isinstance(effect, Exception):
                raise effect
            return effect
        # Default success response
        return {
            "summary": "Updated summary",
            "threads": "- Thread A",
            "ledger_entry": "- Event happened",
            "ledger_entries": [
                {"beat_id": "unknown", "entry": "- Event happened"}
            ],
        }

    async def call(self, stage, system, user):
        return "LLM text response"


def _make_dirs(paths, world, canon, series, story):
    for d in [
        paths.story_continuity(world, canon, series, story),
        paths.queue_dir(world, canon, series, story),
        paths.story_beats(world, canon, series, story),
    ]:
        d.mkdir(parents=True, exist_ok=True)


def _write_queue_item(paths, world, canon, series, story, beat_id, beatdir):
    """Helper: write one queue item the way enqueue_delta would."""
    from quillan.io import atomic_write
    ts = f"{time.time():.6f}"
    item = {"ts": ts, "beat_id": beat_id, "beatdir": str(beatdir)}
    item_path = paths.queue_item(world, canon, series, story, beat_id, ts)
    atomic_write(item_path, json.dumps(item, indent=2))
    return item_path


# ── run_aggregator processes queue ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_aggregator_empty_queue_is_noop(paths, world, canon, series, story, settings):
    """run_aggregator with no queue items does nothing and does not create files."""
    from quillan.continuity.aggregator import run_aggregator
    _make_dirs(paths, world, canon, series, story)
    await run_aggregator(paths, world, canon, series, story, _FakeLLM(), settings)
    # No continuity files should have been created
    summary_path = paths.continuity_summary(world, canon, series, story)
    assert not summary_path.exists()


@pytest.mark.asyncio
async def test_run_aggregator_processes_queue(paths, world, canon, series, story, settings):
    """run_aggregator creates summary/threads/ledger from queue items (offline mode)."""
    from quillan.continuity.aggregator import run_aggregator
    _make_dirs(paths, world, canon, series, story)

    # Create a beat dir with a draft
    beat_dir = paths.beat(world, canon, series, story, "C1-S1-B1")
    beat_dir.mkdir(parents=True, exist_ok=True)
    (beat_dir / "Beat_Draft.md").write_text("Alice walked into the rain.")

    _write_queue_item(paths, world, canon, series, story, "C1-S1-B1", beat_dir)

    await run_aggregator(paths, world, canon, series, story, _FakeLLM(), settings)

    # All three continuity artifacts should exist
    assert paths.continuity_summary(world, canon, series, story).exists()
    assert paths.continuity_threads(world, canon, series, story).exists()
    assert paths.continuity_ledger(world, canon, series, story).exists()


@pytest.mark.asyncio
async def test_run_aggregator_clears_queue(paths, world, canon, series, story, settings):
    """After run_aggregator, the queue directory is empty."""
    from quillan.continuity.aggregator import run_aggregator
    _make_dirs(paths, world, canon, series, story)

    beat_dir = paths.beat(world, canon, series, story, "C1-S1-B2")
    beat_dir.mkdir(parents=True, exist_ok=True)
    _write_queue_item(paths, world, canon, series, story, "C1-S1-B2", beat_dir)

    queue_dir = paths.queue_dir(world, canon, series, story)
    assert len(list(queue_dir.iterdir())) == 1

    await run_aggregator(paths, world, canon, series, story, _FakeLLM(), settings)

    remaining = list(queue_dir.iterdir())
    assert len(remaining) == 0


@pytest.mark.asyncio
async def test_run_aggregator_multiple_beats_ordered(paths, world, canon, series, story, settings):
    """run_aggregator processes multiple queue items and updates summary for each."""
    from quillan.continuity.aggregator import run_aggregator
    _make_dirs(paths, world, canon, series, story)

    for bid in ["C1-S1-B1", "C1-S1-B2"]:
        beat_dir = paths.beat(world, canon, series, story, bid)
        beat_dir.mkdir(parents=True, exist_ok=True)
        (beat_dir / "Beat_Draft.md").write_text(f"Events for {bid}.")
        _write_queue_item(paths, world, canon, series, story, bid, beat_dir)

    await run_aggregator(paths, world, canon, series, story, _FakeLLM(), settings)

    summary = paths.continuity_summary(world, canon, series, story).read_text()
    # Offline mode appends beat markers
    assert "C1-S1-B1" in summary
    assert "C1-S1-B2" in summary


# ── distill fires on threshold ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_distill_does_not_fire_below_threshold(paths, world, canon, series, story, settings):
    """Distillation is not attempted when summary is below the 70% threshold."""
    from quillan.continuity.aggregator import run_aggregator
    from quillan.config import Settings

    settings_with_distill = Settings(
        data_dir=settings.data_dir, llm_cache=False, telemetry=False,
        distill_continuity=True,
        continuity_summary_max_chars=10000,
    )
    _make_dirs(paths, world, canon, series, story)

    # Short summary — well below threshold
    summary_path = paths.continuity_summary(world, canon, series, story)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("Short summary.")

    beat_dir = paths.beat(world, canon, series, story, "C1-S1-B1")
    beat_dir.mkdir(parents=True, exist_ok=True)
    _write_queue_item(paths, world, canon, series, story, "C1-S1-B1", beat_dir)

    # Should not raise; distill is a no-op (offline + below threshold)
    await run_aggregator(
        paths, world, canon, series, story, _FakeLLM(), settings_with_distill
    )
    # Summary was updated but not distilled (offline)
    assert summary_path.exists()


@pytest.mark.asyncio
async def test_distill_no_op_without_api_keys(paths, world, canon, series, story, settings):
    """_maybe_distill_summary is a no-op when no API keys are configured."""
    from quillan.continuity.aggregator import _maybe_distill_summary
    from quillan.config import Settings

    settings_distill = Settings(
        data_dir=settings.data_dir, llm_cache=False, telemetry=False,
        distill_continuity=True, continuity_summary_max_chars=100,
    )
    _make_dirs(paths, world, canon, series, story)
    summary_path = paths.continuity_summary(world, canon, series, story)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    big_text = "x" * 90  # > 70% of 100
    summary_path.write_text(big_text)

    # No API keys → no distillation → text unchanged
    await _maybe_distill_summary(
        paths, world, canon, series, story, _FakeLLM(), settings_distill
    )
    assert summary_path.read_text() == big_text


# ── Multi-beat batching ────────────────────────────────────────────────────────

def _write_beat_with_prose(paths, world, canon, series, story, beat_id, prose):
    """Helper: create beat dir + draft + queue item."""
    beat_dir = paths.beat(world, canon, series, story, beat_id)
    beat_dir.mkdir(parents=True, exist_ok=True)
    (beat_dir / "Beat_Draft.md").write_text(prose)
    _write_queue_item(paths, world, canon, series, story, beat_id, beat_dir)
    return beat_dir


@pytest.mark.asyncio
async def test_multi_beat_single_call(paths, world, canon, series, story, settings):
    """3 beats with prose → call_json called once with ledger_entries key."""
    from quillan.continuity.aggregator import run_aggregator

    _make_dirs(paths, world, canon, series, story)

    beat_ids = ["C1-S1-B1", "C1-S1-B2", "C1-S1-B3"]
    ledger_entries_response = [
        {"beat_id": bid, "entry": f"- Events for {bid}"} for bid in beat_ids
    ]
    llm = _FakeLLMWithKeys(side_effects=[{
        "summary": "Combined summary",
        "threads": "- Thread A",
        "ledger_entries": ledger_entries_response,
    }])

    for bid in beat_ids:
        _write_beat_with_prose(paths, world, canon, series, story, bid, f"Prose for {bid}.")

    await run_aggregator(paths, world, canon, series, story, llm, settings)

    assert llm._call_count == 1
    call = llm._calls[0]
    assert call["required_keys"] == ["summary", "threads", "ledger_entries"]

    ledger = paths.continuity_ledger(world, canon, series, story).read_text()
    for bid in beat_ids:
        assert bid in ledger


@pytest.mark.asyncio
async def test_multi_beat_fallback(paths, world, canon, series, story, settings):
    """Multi-beat call raises → falls back to per-beat calls, all beats processed."""
    from quillan.continuity.aggregator import run_aggregator

    _make_dirs(paths, world, canon, series, story)

    beat_ids = ["C1-S1-B1", "C1-S1-B2", "C1-S1-B3"]
    # First call (multi-beat) raises; subsequent per-beat calls succeed
    per_beat_responses = [
        {
            "summary": f"Summary after {bid}",
            "threads": "- Thread",
            "ledger_entry": f"- Event {bid}",
        }
        for bid in beat_ids
    ]
    llm = _FakeLLMWithKeys(side_effects=[RuntimeError("LLM error")] + per_beat_responses)

    for bid in beat_ids:
        _write_beat_with_prose(paths, world, canon, series, story, bid, f"Prose for {bid}.")

    await run_aggregator(paths, world, canon, series, story, llm, settings)

    # 1 failed multi-beat + 3 per-beat fallback calls
    assert llm._call_count == 4

    ledger = paths.continuity_ledger(world, canon, series, story).read_text()
    for bid in beat_ids:
        assert bid in ledger


@pytest.mark.asyncio
async def test_single_beat_uses_existing_path(paths, world, canon, series, story, settings):
    """Single beat with prose uses _update_all_batch (ledger_entry key, not ledger_entries)."""
    from quillan.continuity.aggregator import run_aggregator

    _make_dirs(paths, world, canon, series, story)

    llm = _FakeLLMWithKeys(side_effects=[{
        "summary": "Summary",
        "threads": "- Thread",
        "ledger_entry": "- Single beat event",
    }])

    _write_beat_with_prose(paths, world, canon, series, story, "C1-S1-B1", "Prose text.")

    await run_aggregator(paths, world, canon, series, story, llm, settings)

    assert llm._call_count == 1
    call = llm._calls[0]
    assert call["required_keys"] == ["summary", "threads", "ledger_entry"]


@pytest.mark.asyncio
async def test_multi_beat_ordering(paths, world, canon, series, story, settings):
    """Beats queued in timestamp order appear in ledger in the same order."""
    from quillan.continuity.aggregator import run_aggregator

    _make_dirs(paths, world, canon, series, story)

    beat_ids = ["C1-S1-B1", "C1-S1-B2", "C1-S1-B3"]
    ledger_entries_response = [
        {"beat_id": bid, "entry": f"- Entry {bid}"} for bid in beat_ids
    ]
    llm = _FakeLLMWithKeys(side_effects=[{
        "summary": "Summary",
        "threads": "- Thread",
        "ledger_entries": ledger_entries_response,
    }])

    # Write beats with increasing timestamps (small sleep ensures order)
    for bid in beat_ids:
        _write_beat_with_prose(paths, world, canon, series, story, bid, f"Prose {bid}.")
        time.sleep(0.01)

    await run_aggregator(paths, world, canon, series, story, llm, settings)

    ledger = paths.continuity_ledger(world, canon, series, story).read_text()
    positions = [ledger.index(bid) for bid in beat_ids]
    assert positions == sorted(positions), "Beats should appear in timestamp order"


@pytest.mark.asyncio
async def test_multi_beat_sub_batching(paths, world, canon, series, story, settings):
    """When max_prompt_tokens is tiny, beats are split into multiple sub-batches."""
    from quillan.continuity.aggregator import run_aggregator
    from quillan.config import Settings

    _make_dirs(paths, world, canon, series, story)

    # Very small token budget forces each beat into its own sub-batch
    tight_settings = Settings(
        data_dir=settings.data_dir, llm_cache=False, telemetry=False,
        max_prompt_tokens=4000,  # _MULTI_BEAT_OVERHEAD_TOKENS=3500, budget=500 per sub-batch
    )

    beat_ids = ["C1-S1-B1", "C1-S1-B2", "C1-S1-B3"]
    # Each beat response is a valid multi-beat response (1 entry each)
    side_effects = [
        {
            "summary": f"Summary {i}",
            "threads": "- Thread",
            "ledger_entries": [{"beat_id": bid, "entry": f"- Entry {bid}"}],
        }
        for i, bid in enumerate(beat_ids)
    ]
    llm = _FakeLLMWithKeys(side_effects=side_effects)

    long_prose = "word " * 500  # ~500 words → well over 500 token budget per beat
    for bid in beat_ids:
        _write_beat_with_prose(paths, world, canon, series, story, bid, long_prose)

    await run_aggregator(paths, world, canon, series, story, llm, settings=tight_settings)

    # Each beat forced into its own sub-batch → multiple call_json calls
    assert llm._call_count > 1
