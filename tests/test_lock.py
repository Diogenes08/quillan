"""Tests for quillan.lock — sync_file_lock and file_lock."""

from __future__ import annotations

import threading
import time

import pytest

from quillan.lock import file_lock, sync_file_lock


# ── sync_file_lock ────────────────────────────────────────────────────────────

def test_sync_file_lock_acquires_and_releases(tmp_path):
    lockfile = tmp_path / "test.lock"
    with sync_file_lock(lockfile):
        assert lockfile.exists()
    # Lock released — re-acquiring must succeed immediately
    with sync_file_lock(lockfile):
        pass


def test_sync_file_lock_creates_parent_dir(tmp_path):
    lockfile = tmp_path / "subdir" / "nested" / "test.lock"
    with sync_file_lock(lockfile):
        assert lockfile.exists()


def test_sync_file_lock_sequential_reuse(tmp_path):
    lockfile = tmp_path / "seq.lock"
    results = []
    for i in range(3):
        with sync_file_lock(lockfile):
            results.append(i)
    assert results == [0, 1, 2]


def test_sync_file_lock_contention_serialises(tmp_path):
    """Two threads contend for the same lock — only one runs the critical section at a time."""
    lockfile = tmp_path / "contend.lock"
    in_section: list[int] = []
    overlap_detected = False

    def worker(tid: int) -> None:
        nonlocal overlap_detected
        with sync_file_lock(lockfile, timeout=5.0):
            in_section.append(tid)
            time.sleep(0.02)
            if len(in_section) > 1:
                overlap_detected = True
            in_section.remove(tid)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not overlap_detected, "Critical section overlap detected — locking failed"


def test_sync_file_lock_timeout(tmp_path):
    """A lock held by another thread should cause TimeoutError after the timeout."""
    lockfile = tmp_path / "timeout.lock"
    lock_held = threading.Event()
    release_lock = threading.Event()

    def holder():
        with sync_file_lock(lockfile, timeout=10.0):
            lock_held.set()
            release_lock.wait(timeout=5.0)

    holder_thread = threading.Thread(target=holder)
    holder_thread.start()
    lock_held.wait(timeout=2.0)

    try:
        with pytest.raises(TimeoutError):
            with sync_file_lock(lockfile, timeout=0.1):
                pass
    finally:
        release_lock.set()
        holder_thread.join()


# ── file_lock (async) ─────────────────────────────────────────────────────────

async def test_file_lock_acquires_and_releases(tmp_path):
    lockfile = tmp_path / "async.lock"
    async with file_lock(lockfile):
        assert lockfile.exists()
    # Re-acquire after release
    async with file_lock(lockfile):
        pass


async def test_file_lock_creates_parent_dir(tmp_path):
    lockfile = tmp_path / "a" / "b" / "c.lock"
    async with file_lock(lockfile):
        assert lockfile.exists()


async def test_file_lock_sequential(tmp_path):
    lockfile = tmp_path / "seq_async.lock"
    order: list[int] = []
    for i in range(3):
        async with file_lock(lockfile):
            order.append(i)
    assert order == [0, 1, 2]
