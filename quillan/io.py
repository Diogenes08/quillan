"""Atomic writes, temp files, character-cap sliding window, and TTL cleanup."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

_MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MiB hard cap on atomic writes


def atomic_write(dest: Path, content: str | bytes) -> None:
    """Write *content* to *dest* atomically (temp-file + rename).

    Raises ValueError if content exceeds 10 MiB.
    Parent directory is created if missing.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(content, str):
        data = content.encode()
    else:
        data = content

    if len(data) > _MAX_FILE_BYTES:
        raise ValueError(
            f"atomic_write: content size {len(data)} exceeds 10 MiB cap for {dest}"
        )

    old_umask = os.umask(0o077)
    try:
        fd, tmp_path = tempfile.mkstemp(dir=dest.parent, prefix=".qtmp_")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp_path, dest)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    finally:
        os.umask(old_umask)


def atomic_write_from(dest: Path, src: Path) -> None:
    """Copy *src* to *dest* atomically (temp-file + rename)."""
    dest = Path(dest)
    src = Path(src)
    dest.parent.mkdir(parents=True, exist_ok=True)

    old_umask = os.umask(0o077)
    try:
        fd, tmp_path = tempfile.mkstemp(dir=dest.parent, prefix=".qtmp_")
        os.close(fd)
        try:
            shutil.copy2(src, tmp_path)
            os.replace(tmp_path, dest)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    finally:
        os.umask(old_umask)


def mktemp(prefix: str = "qtmp", suffix: str = "", dir: Path | None = None) -> Path:
    """Create a temp file with umask 077 and return its Path."""
    old_umask = os.umask(0o077)
    try:
        fd, path = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=dir)
        os.close(fd)
        return Path(path)
    finally:
        os.umask(old_umask)


def cap_file_chars(path: Path, max_chars: int) -> None:
    """In-place 60/40 head/tail sliding window.

    If the file content exceeds *max_chars*, replace it with:
        <head 60%> + "\\n\\n[...middle trimmed...]\\n\\n" + <tail 40%>
    """
    path = Path(path)
    if not path.exists():
        return

    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= max_chars:
        return

    head_chars = int(max_chars * 0.60)
    tail_chars = max_chars - head_chars
    marker = "\n\n[...middle trimmed...]\n\n"

    trimmed = text[:head_chars] + marker + text[len(text) - tail_chars:]
    atomic_write(path, trimmed)


def prune_old_tmp(tmp_dir: Path, ttl_hours: int) -> None:
    """Delete files in *tmp_dir* older than *ttl_hours* hours."""
    tmp_dir = Path(tmp_dir)
    if not tmp_dir.is_dir():
        return

    cutoff = time.time() - ttl_hours * 3600
    for item in tmp_dir.iterdir():
        try:
            if item.is_file() and item.stat().st_mtime < cutoff:
                item.unlink(missing_ok=True)
        except OSError:
            pass


def prune_old_cache(cache_dir: Path, ttl_days: int) -> int:
    """Delete cache entries older than *ttl_days* days.

    Walks the two-level shard structure used by LLMClient (``cache_dir/<xx>/<hash>.txt``).
    Returns the number of files deleted.
    """
    cache_dir = Path(cache_dir)
    if not cache_dir.is_dir() or ttl_days <= 0:
        return 0

    cutoff = time.time() - ttl_days * 86400
    deleted = 0
    for shard in cache_dir.iterdir():
        if not shard.is_dir():
            continue
        for entry in shard.iterdir():
            try:
                if entry.is_file() and entry.stat().st_mtime < cutoff:
                    entry.unlink(missing_ok=True)
                    deleted += 1
            except OSError:
                pass
    return deleted
