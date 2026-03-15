"""Tests for quillan.continuity.queue — enqueue and drain."""

from __future__ import annotations

import json
import time


# ── enqueue_delta ──────────────────────────────────────────────────────────────


def test_enqueue_creates_json_file(paths, world, canon, series, story):
    from quillan.continuity.queue import enqueue_delta

    beat_id = "C1-S1-B1"
    beatdir = paths.beat(world, canon, series, story, beat_id)
    beatdir.mkdir(parents=True, exist_ok=True)

    enqueue_delta(paths, world, canon, series, story, beat_id, beatdir)

    queue_dir = paths.queue_dir(world, canon, series, story)
    items = list(queue_dir.glob("*.json"))
    assert len(items) == 1

    data = json.loads(items[0].read_text())
    assert data["beat_id"] == beat_id
    assert "ts" in data
    assert data["beatdir"] == str(beatdir)


def test_enqueue_multiple_beats_creates_multiple_files(paths, world, canon, series, story):
    from quillan.continuity.queue import enqueue_delta

    for i in range(3):
        beat_id = f"C1-S1-B{i + 1}"
        beatdir = paths.beat(world, canon, series, story, beat_id)
        beatdir.mkdir(parents=True, exist_ok=True)
        enqueue_delta(paths, world, canon, series, story, beat_id, beatdir)
        # Small sleep to ensure unique timestamps
        time.sleep(0.001)

    queue_dir = paths.queue_dir(world, canon, series, story)
    items = list(queue_dir.glob("*.json"))
    assert len(items) == 3


# ── drain_queue ────────────────────────────────────────────────────────────────


def test_drain_queue_returns_items_in_timestamp_order(paths, world, canon, series, story):
    from quillan.continuity.queue import enqueue_delta, drain_queue

    beat_ids = ["C1-S1-B1", "C1-S1-B2", "C1-S1-B3"]
    for bid in beat_ids:
        beatdir = paths.beat(world, canon, series, story, bid)
        beatdir.mkdir(parents=True, exist_ok=True)
        enqueue_delta(paths, world, canon, series, story, bid, beatdir)
        time.sleep(0.002)  # ensure distinct timestamps

    items = drain_queue(paths, world, canon, series, story)

    assert len(items) == 3
    returned_ids = [item["beat_id"] for item in items]
    assert returned_ids == beat_ids


def test_drain_queue_removes_files(paths, world, canon, series, story):
    from quillan.continuity.queue import enqueue_delta, drain_queue

    beat_id = "C1-S1-B1"
    beatdir = paths.beat(world, canon, series, story, beat_id)
    beatdir.mkdir(parents=True, exist_ok=True)
    enqueue_delta(paths, world, canon, series, story, beat_id, beatdir)

    queue_dir = paths.queue_dir(world, canon, series, story)
    assert len(list(queue_dir.glob("*.json"))) == 1

    drain_queue(paths, world, canon, series, story)

    assert len(list(queue_dir.glob("*.json"))) == 0


def test_drain_queue_empty_returns_empty_list(paths, world, canon, series, story):
    from quillan.continuity.queue import drain_queue

    result = drain_queue(paths, world, canon, series, story)
    assert result == []


def test_drain_queue_skips_corrupted_files(paths, world, canon, series, story):
    from quillan.continuity.queue import enqueue_delta, drain_queue
    from quillan.io import atomic_write

    # Valid item
    beat_id = "C1-S1-B1"
    beatdir = paths.beat(world, canon, series, story, beat_id)
    beatdir.mkdir(parents=True, exist_ok=True)
    enqueue_delta(paths, world, canon, series, story, beat_id, beatdir)

    # Corrupted item
    queue_dir = paths.queue_dir(world, canon, series, story)
    atomic_write(queue_dir / "bad_item.json", "not valid json {{{")

    items = drain_queue(paths, world, canon, series, story)
    # Only the valid item should be returned; corrupt file silently skipped
    assert len(items) == 1
    assert items[0]["beat_id"] == beat_id
