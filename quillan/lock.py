"""Asyncio-safe advisory file locking via fcntl.flock.

Provides:
- file_lock(path, timeout) — async context manager (runs flock in thread executor)
- sync_file_lock(path, timeout) — synchronous context manager for non-async callers
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path
from typing import IO, Generator

try:
    import fcntl as _fcntl
    _FCNTL_AVAILABLE = True
except ImportError:
    _fcntl = None  # type: ignore[assignment]
    _FCNTL_AVAILABLE = False


def _require_fcntl() -> None:
    if not _FCNTL_AVAILABLE:
        raise NotImplementedError(
            "File locking requires fcntl (Linux/macOS only). "
            "On Windows, run Quillan under WSL."
        )


def _acquire_flock(fd: IO[str], timeout: float) -> None:
    """Blocking flock acquire with timeout (poll-based for portability)."""
    _require_fcntl()
    deadline = time.monotonic() + timeout
    while True:
        try:
            _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            return
        except BlockingIOError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"Could not acquire file lock within {timeout:.1f}s"
                ) from None
            time.sleep(min(0.05, remaining))


@contextlib.asynccontextmanager
async def file_lock(lockpath: Path, timeout: float = 30.0):
    """Asyncio-compatible advisory lock via fcntl.flock.

    Acquires in a thread executor to avoid blocking the event loop.
    """
    lockpath = Path(lockpath)
    lockpath.parent.mkdir(parents=True, exist_ok=True)

    _require_fcntl()
    loop = asyncio.get_running_loop()
    fd = open(lockpath, "w")
    try:
        await asyncio.wait_for(
            loop.run_in_executor(None, _acquire_flock, fd, timeout),
            timeout=timeout + 1.0,  # outer timeout slightly longer than inner
        )
        yield
    finally:
        try:
            _fcntl.flock(fd, _fcntl.LOCK_UN)
        finally:
            fd.close()


@contextlib.contextmanager
def sync_file_lock(lockpath: Path, timeout: float = 30.0) -> Generator[None, None, None]:
    """Synchronous advisory lock via fcntl.flock.

    For use in non-async callers (export, tests, CLI).
    """
    lockpath = Path(lockpath)
    lockpath.parent.mkdir(parents=True, exist_ok=True)

    _require_fcntl()
    fd = open(lockpath, "w")
    try:
        _acquire_flock(fd, timeout)
        yield
    finally:
        try:
            _fcntl.flock(fd, _fcntl.LOCK_UN)
        finally:
            fd.close()
