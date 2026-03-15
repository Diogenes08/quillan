"""Continuity delta queue: enqueue non-blocking, many-writers safe."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quillan.paths import Paths


def enqueue_delta(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    beat_id: str,
    beatdir: Path,
) -> None:
    """Write a timestamped JSON queue item.

    Non-blocking, safe for concurrent writers (each writer gets a unique timestamp
    based on monotonic time + beat_id).
    The queue item records the beat_id and the path to its beat directory.
    """
    from quillan.io import atomic_write

    queue_dir = paths.queue_dir(world, canon, series, story)
    queue_dir.mkdir(parents=True, exist_ok=True)

    ts = f"{time.time():.6f}"
    item = {
        "ts": ts,
        "beat_id": beat_id,
        "beatdir": str(beatdir),
    }

    item_path = paths.queue_item(world, canon, series, story, beat_id, ts)
    atomic_write(item_path, json.dumps(item, indent=2))


def drain_queue(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
) -> list[dict]:
    """Read all queue items in timestamp order and remove them.

    Returns list of item dicts, sorted by ts ascending.
    Should only be called from within the continuity lock.
    """
    queue_dir = paths.queue_dir(world, canon, series, story)
    if not queue_dir.exists():
        return []

    items: list[tuple[str, Path, dict]] = []
    for path in queue_dir.iterdir():
        if path.is_file() and path.suffix == ".json":
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                ts = data.get("ts", "0")
                items.append((ts, path, data))
            except (json.JSONDecodeError, OSError):
                # Skip corrupted items
                pass

    # Sort by timestamp
    items.sort(key=lambda x: x[0])

    # Remove files and return data
    result = []
    for ts, path, data in items:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        result.append(data)

    return result
