"""Beat prose generation via LLM."""

from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from quillan.templates import get_prompt

if TYPE_CHECKING:
    from quillan.llm import LLMClient
    from quillan.paths import Paths
    from quillan.config import Settings


def snapshot_beat_draft(paths: "Paths", world: str, canon: str, series: str,
                        story: str, beat_id: str) -> "Path | None":
    """Copy the current Beat_Draft.md into the versions directory.

    Returns the snapshot path, or None if there was no existing draft.
    Safe to call even if the draft does not yet exist.
    """
    draft_path = paths.beat_draft(world, canon, series, story, beat_id)
    if not draft_path.exists():
        return None
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ver_dir = paths.beat_versions_dir(world, canon, series, story, beat_id)
    ver_dir.mkdir(parents=True, exist_ok=True)
    snap_path = paths.beat_version(world, canon, series, story, beat_id, ts)
    shutil.copy2(draft_path, snap_path)
    return snap_path



async def draft_beat(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    beat_id: str,
    attempt: int,
    llm: "LLMClient",
    settings: "Settings",
    on_chunk: "Callable[[str, str], None] | None" = None,
) -> bool:
    """Assemble context bundle, call LLM, write Beat_Draft.md.

    Returns True on success, False on LLM failure.
    """
    from quillan.draft.bundle import assemble_bundle
    from quillan.io import atomic_write
    from quillan.llm import LLMError
    import yaml

    # Assemble context bundle
    context_path = await assemble_bundle(
        paths, world, canon, series, story, beat_id, settings, attempt=attempt
    )
    context_text = context_path.read_text(encoding="utf-8", errors="replace")

    # Get word count target from spec
    spec_path = paths.beat_spec(world, canon, series, story, beat_id)
    word_count = 1500
    if spec_path.exists():
        try:
            spec_data = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
            word_count = spec_data.get("word_count_target", 1500)
        except yaml.YAMLError:
            pass

    _story_dir = paths.story(world, canon, series, story)
    _world_dir = paths.world(world)
    user_prompt = get_prompt("draft_user", story_dir=_story_dir, world_dir=_world_dir).format(
        context=context_text,
        word_count=word_count,
    )

    if not llm.settings.has_api_keys:
        # Offline stub
        stub = f"[Beat {beat_id} — offline stub. No API keys configured.]\n"
        draft_path = paths.beat_draft(world, canon, series, story, beat_id)
        paths.ensure(draft_path)
        atomic_write(draft_path, stub)
        return True

    try:
        draft_path = paths.beat_draft(world, canon, series, story, beat_id)
        paths.ensure(draft_path)
        # Stream output: write chunks to a partial file so the UI can preview in-progress prose
        partial_path = draft_path.with_suffix(".partial.md")
        chunks: list[str] = []
        _chunk_count = 0
        _last_flush = time.monotonic()
        async for chunk in llm.call_stream(
            "draft", get_prompt("draft_system", story_dir=_story_dir, world_dir=_world_dir),
            user_prompt,
        ):
            chunks.append(chunk)
            _chunk_count += 1
            now = time.monotonic()
            if _chunk_count % 10 == 0 or (now - _last_flush) >= 0.5:
                partial_path.write_text("".join(chunks), encoding="utf-8")
                _last_flush = now
            if on_chunk is not None:
                on_chunk(beat_id, chunk)
        # Final flush
        partial_path.write_text("".join(chunks), encoding="utf-8")
        prose = "".join(chunks)
        snapshot_beat_draft(paths, world, canon, series, story, beat_id)
        atomic_write(draft_path, prose)
        # Remove partial file once draft is committed
        if partial_path.exists():
            partial_path.unlink(missing_ok=True)
        return True
    except LLMError:
        return False
