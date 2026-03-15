"""Unit tests for quillan.web.chunk_bus."""

from __future__ import annotations

import asyncio
import pytest

from quillan.web.chunk_bus import ChunkMessage, create_bus, get_bus, remove_bus


# ── Lifecycle ──────────────────────────────────────────────────────────────────

def test_create_get_remove():
    """create_bus registers queue; remove_bus clears it; get_bus returns None after."""
    job_id = 9001
    q = create_bus(job_id)
    assert get_bus(job_id) is q
    remove_bus(job_id)
    assert get_bus(job_id) is None


def test_get_bus_unknown_returns_none():
    assert get_bus(99999) is None


def test_remove_bus_nonexistent_is_noop():
    remove_bus(88888)  # should not raise


# ── Message flow ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_message_flow():
    """put_nowait followed by get returns messages in FIFO order."""
    job_id = 9002
    q = create_bus(job_id)
    try:
        msgs = [
            ChunkMessage(beat_id="B1", text="hello "),
            ChunkMessage(beat_id="B1", text="world"),
            ChunkMessage(beat_id="B2", text="fin", done=True),
        ]
        for m in msgs:
            q.put_nowait(m)
        received = []
        for _ in msgs:
            received.append(await asyncio.wait_for(q.get(), timeout=1.0))
        assert received == msgs
    finally:
        remove_bus(job_id)


# ── Overflow / maxsize ─────────────────────────────────────────────────────────

def test_maxsize_overflow():
    """Filling the queue to maxsize then one more raises QueueFull."""
    job_id = 9003
    q = create_bus(job_id)
    try:
        # Fill to maxsize
        for i in range(1000):
            q.put_nowait(ChunkMessage(beat_id="B1", text=f"chunk{i}"))
        # One more should raise
        with pytest.raises(asyncio.QueueFull):
            q.put_nowait(ChunkMessage(beat_id="B1", text="overflow"))
    finally:
        remove_bus(job_id)


# ── ChunkMessage dataclass ─────────────────────────────────────────────────────

def test_chunk_message_defaults():
    m = ChunkMessage(beat_id="X", text="hello")
    assert m.done is False


def test_chunk_message_done_sentinel():
    m = ChunkMessage(beat_id="X", text="", done=True)
    assert m.done is True
