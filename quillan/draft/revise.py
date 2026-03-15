"""Targeted beat revision via LLM — F7: Revision Workflow.

Unlike draft_beat() which generates prose from scratch using a full context
bundle, revise_beat() takes the existing prose and applies author-supplied
revision notes surgically, preserving everything that wasn't flagged.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from quillan.templates import get_prompt

if TYPE_CHECKING:
    from quillan.llm import LLMClient
    from quillan.paths import Paths
    from quillan.config import Settings


async def revise_beat(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    beat_id: str,
    revision_notes: str,
    llm: "LLMClient",
    settings: "Settings",
    on_chunk: "Callable[[str, str], None] | None" = None,
) -> bool:
    """Apply *revision_notes* to the existing Beat_Draft.md and write the result.

    Steps:
    1. Snapshot the current draft into versions/ (preserves undo history).
    2. Read the existing prose (fails gracefully if missing).
    3. Stream the revised prose from the LLM.
    4. Atomically overwrite Beat_Draft.md.

    Returns True on success, False on LLM failure or missing draft.
    """
    from quillan.draft.draft import snapshot_beat_draft
    from quillan.io import atomic_write
    from quillan.llm import LLMError

    draft_path = paths.beat_draft(world, canon, series, story, beat_id)
    if not draft_path.exists():
        return False

    existing_prose = draft_path.read_text(encoding="utf-8", errors="replace")

    # Snapshot before overwriting so the original is recoverable
    snapshot_beat_draft(paths, world, canon, series, story, beat_id)

    # Load beat spec for context (optional)
    spec_text = "(no beat spec available)"
    spec_path = paths.beat_spec(world, canon, series, story, beat_id)
    if spec_path.exists():
        try:
            spec_raw = spec_path.read_text(encoding="utf-8") or ""
            spec_text = spec_raw.strip() or spec_text
        except OSError:
            pass

    _story_dir = paths.story(world, canon, series, story)
    _world_dir = paths.world(world)

    system = get_prompt("revise_system", story_dir=_story_dir, world_dir=_world_dir)
    user = get_prompt("revise_user", story_dir=_story_dir, world_dir=_world_dir).format(
        spec=spec_text,
        existing_draft=existing_prose,
        revision_notes=revision_notes.strip(),
    )

    if not llm.settings.has_api_keys:
        # Offline stub: annotate draft with revision notes but don't change prose
        stub = f"[REVISION NOTES — offline stub]\n{revision_notes}\n\n{existing_prose}"
        paths.ensure(draft_path)
        atomic_write(draft_path, stub)
        return True

    try:
        partial_path = draft_path.with_suffix(".partial.md")
        chunks: list[str] = []
        _chunk_count = 0
        _last_flush = time.monotonic()

        async for chunk in llm.call_stream("draft", system, user):
            chunks.append(chunk)
            _chunk_count += 1
            now = time.monotonic()
            if _chunk_count % 10 == 0 or (now - _last_flush) >= 0.5:
                partial_path.write_text("".join(chunks), encoding="utf-8")
                _last_flush = now
            if on_chunk is not None:
                on_chunk(beat_id, chunk)

        partial_path.write_text("".join(chunks), encoding="utf-8")
        prose = "".join(chunks)
        atomic_write(draft_path, prose)
        if partial_path.exists():
            partial_path.unlink(missing_ok=True)
        return True

    except LLMError:
        return False
