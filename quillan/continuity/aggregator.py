"""Locked continuity aggregator: update summary, threads, ledger."""

from __future__ import annotations

import logging
from pathlib import Path
from quillan.templates import get_prompt
from typing import TYPE_CHECKING

logger = logging.getLogger("quillan.continuity.aggregator")

if TYPE_CHECKING:
    from quillan.config import Settings
    from quillan.llm import LLMClient
    from quillan.paths import Paths

# Token budget constants for multi-beat batching
_PER_BEAT_EXCERPT_TOKENS = 800
_MULTI_BEAT_OVERHEAD_TOKENS = 3500










def _compute_sub_batches(
    items_with_prose: list[dict],
    max_prompt_tokens: int,
) -> list[list[dict]]:
    """Group beat items into sub-batches that fit within the token budget.

    Each item dict must have 'beat_id', 'prose_excerpt', and 'excerpt_tokens' keys.
    Greedy first-fit: fill a batch until adding the next item would exceed the budget,
    then start a new batch.
    """
    from quillan.token_tool import estimate_tokens

    budget = max_prompt_tokens - _MULTI_BEAT_OVERHEAD_TOKENS
    if budget <= 0:
        # Fall back to one item per sub-batch
        return [[item] for item in items_with_prose]

    batches: list[list[dict]] = []
    current_batch: list[dict] = []
    current_tokens = 0

    for item in items_with_prose:
        cost = item.get("excerpt_tokens", estimate_tokens(item.get("prose_excerpt", "")))
        if current_batch and current_tokens + cost > budget:
            batches.append(current_batch)
            current_batch = []
            current_tokens = 0
        current_batch.append(item)
        current_tokens += cost

    if current_batch:
        batches.append(current_batch)

    return batches


async def _update_all_multi_beat(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    items: list[dict],
    llm: "LLMClient",
    settings: "Settings",
) -> None:
    """Single LLM call that updates summary, threads, and ledger for N beats at once.

    items: list of dicts with 'beat_id' and 'prose_excerpt'.
    Falls back to sequential per-beat _update_all_batch() on any exception.
    """
    from quillan.io import atomic_write

    summary_path = paths.continuity_summary(world, canon, series, story)
    threads_path = paths.continuity_threads(world, canon, series, story)
    ledger_path = paths.continuity_ledger(world, canon, series, story)

    paths.ensure(summary_path)
    paths.ensure(threads_path)
    paths.ensure(ledger_path)

    current_summary = summary_path.read_text(encoding="utf-8") if summary_path.exists() else ""
    current_threads = threads_path.read_text(encoding="utf-8") if threads_path.exists() else ""
    current_ledger = ledger_path.read_text(encoding="utf-8") if ledger_path.exists() else ""
    ledger_tail = current_ledger[-2000:] if len(current_ledger) > 2000 else current_ledger

    beats_section = "\n\n".join(
        f"### Beat {item['beat_id']}\n\n{item['prose_excerpt']}"
        for item in items
    )

    user_prompt = get_prompt("continuity_multi_beat_user").format(
        summary=current_summary[:4000],
        threads=current_threads[:3000],
        ledger_tail=ledger_tail,
        beats_section=beats_section,
        summary_max=settings.continuity_summary_max_chars,
        threads_max=settings.continuity_open_threads_max_chars,
    )

    try:
        result = await llm.call_json(
            "planning",
            get_prompt("continuity_multi_beat_system"),
            user_prompt,
            required_keys=["summary", "threads", "ledger_entries"],
        )
        # Validate ledger_entries shape
        ledger_entries = result.get("ledger_entries", [])
        if not isinstance(ledger_entries, list):
            raise ValueError("ledger_entries must be a list")
        for entry_obj in ledger_entries:
            if not isinstance(entry_obj, dict) or "beat_id" not in entry_obj or "entry" not in entry_obj:
                raise ValueError(f"Invalid ledger entry shape: {entry_obj!r}")
    except Exception as exc:
        logger.warning("Batch continuity update failed, falling back to individual calls: %s", exc)
        # Fallback: process each beat individually
        for item in items:
            await _update_all_batch(
                paths, world, canon, series, story,
                item["beat_id"], item["prose_excerpt"], llm, settings,
            )
        return

    atomic_write(summary_path, result.get("summary", current_summary))
    atomic_write(threads_path, result.get("threads", current_threads))

    updated_ledger = current_ledger
    for entry_obj in ledger_entries:
        bid = entry_obj["beat_id"]
        entry = entry_obj["entry"]
        if entry:
            updated_ledger = updated_ledger.rstrip() + f"\n\n### {bid}\n\n{entry.strip()}\n"
    if updated_ledger != current_ledger:
        atomic_write(ledger_path, updated_ledger)


async def run_aggregator(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    llm: "LLMClient",
    settings: "Settings",
) -> None:
    """Under async file_lock: process queue in timestamp order.

    For each item:
    - Update Summary + Open_Threads + Ledger (with LLM if keys present)
    - Cap all artifacts via cap_file_chars()

    Optionally distill Summary if ≥70% of cap and distill_continuity=True.
    """
    from quillan.continuity.queue import drain_queue
    from quillan.io import cap_file_chars
    from quillan.lock import file_lock

    lock_path = paths.continuity_lock(world, canon, series, story)

    async with file_lock(lock_path, timeout=60.0):
        items = drain_queue(paths, world, canon, series, story)
        if not items:
            return

        # Pre-process all items: extract prose excerpts with token estimates
        from quillan.token_tool import estimate_tokens, trim_to_tokens

        online_items: list[dict] = []   # have prose + API keys
        offline_items: list[dict] = []  # no prose or no API keys

        for item in items:
            beat_id = item.get("beat_id", "unknown")
            beatdir_str = item.get("beatdir", "")
            beatdir = Path(beatdir_str) if beatdir_str else None

            prose_excerpt = ""
            if beatdir:
                draft_path = beatdir / "Beat_Draft.md"
                if draft_path.exists():
                    prose = draft_path.read_text(encoding="utf-8", errors="replace")
                    prose_excerpt = trim_to_tokens(prose, _PER_BEAT_EXCERPT_TOKENS)

            enriched = dict(item)
            enriched["beat_id"] = beat_id
            enriched["prose_excerpt"] = prose_excerpt
            enriched["excerpt_tokens"] = estimate_tokens(prose_excerpt)

            if llm.settings.has_api_keys and prose_excerpt:
                online_items.append(enriched)
            else:
                offline_items.append(enriched)

        # Route: multi-beat, single-beat, or offline
        if len(online_items) >= 2:
            sub_batches = _compute_sub_batches(online_items, settings.max_prompt_tokens)
            for sub_batch in sub_batches:
                await _update_all_multi_beat(
                    paths, world, canon, series, story, sub_batch, llm, settings
                )
        elif len(online_items) == 1:
            item = online_items[0]
            await _update_all_batch(
                paths, world, canon, series, story,
                item["beat_id"], item["prose_excerpt"], llm, settings,
            )

        for item in offline_items:
            await _update_summary(
                paths, world, canon, series, story, item["beat_id"], item["prose_excerpt"], llm, settings
            )
            await _update_threads(
                paths, world, canon, series, story, item["beat_id"], item["prose_excerpt"], llm, settings
            )
            await _update_ledger(
                paths, world, canon, series, story, item["beat_id"], item["prose_excerpt"], llm, settings
            )

        # Cap all artifacts
        summary_path = paths.continuity_summary(world, canon, series, story)
        threads_path = paths.continuity_threads(world, canon, series, story)
        ledger_path = paths.continuity_ledger(world, canon, series, story)

        cap_file_chars(summary_path, settings.continuity_summary_max_chars)
        cap_file_chars(threads_path, settings.continuity_open_threads_max_chars)
        cap_file_chars(ledger_path, settings.continuity_ledger_max_chars)

        # Optionally distill summary
        if settings.distill_continuity and summary_path.exists():
            await _maybe_distill_summary(
                paths, world, canon, series, story, llm, settings
            )


async def _update_all_batch(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    beat_id: str,
    prose_excerpt: str,
    llm: "LLMClient",
    settings: "Settings",
) -> None:
    """Single LLM call that updates summary, threads, and ledger together.

    Reduces 3 API calls to 1 per beat — a 67% reduction in continuity call volume.
    Falls back to individual updates if JSON parsing fails.
    """
    from quillan.io import atomic_write

    summary_path = paths.continuity_summary(world, canon, series, story)
    threads_path = paths.continuity_threads(world, canon, series, story)
    ledger_path = paths.continuity_ledger(world, canon, series, story)

    paths.ensure(summary_path)
    paths.ensure(threads_path)
    paths.ensure(ledger_path)

    current_summary = summary_path.read_text(encoding="utf-8") if summary_path.exists() else ""
    current_threads = threads_path.read_text(encoding="utf-8") if threads_path.exists() else ""
    current_ledger = ledger_path.read_text(encoding="utf-8") if ledger_path.exists() else ""
    ledger_tail = current_ledger[-2000:] if len(current_ledger) > 2000 else current_ledger

    user_prompt = get_prompt("continuity_batch_user").format(
        summary=current_summary[:4000],
        threads=current_threads[:3000],
        ledger_tail=ledger_tail,
        beat_id=beat_id,
        prose_excerpt=prose_excerpt,
        summary_max=settings.continuity_summary_max_chars,
        threads_max=settings.continuity_open_threads_max_chars,
    )

    try:
        result = await llm.call_json(
            "planning",
            get_prompt("continuity_batch_system"),
            user_prompt,
            required_keys=["summary", "threads", "ledger_entry"],
        )
    except Exception as exc:
        logger.warning("Single-beat batch update failed, falling back to individual calls: %s", exc)
        # Fall back to individual calls on parse error
        await _update_summary(paths, world, canon, series, story, beat_id, prose_excerpt, llm, settings)
        await _update_threads(paths, world, canon, series, story, beat_id, prose_excerpt, llm, settings)
        await _update_ledger(paths, world, canon, series, story, beat_id, prose_excerpt, llm, settings)
        return

    atomic_write(summary_path, result.get("summary", current_summary))
    atomic_write(threads_path, result.get("threads", current_threads))
    # Append the new ledger entry (don't overwrite full ledger)
    entry = result.get("ledger_entry", "")
    if entry:
        updated_ledger = current_ledger.rstrip() + f"\n\n### {beat_id}\n\n{entry.strip()}\n"
        atomic_write(ledger_path, updated_ledger)


async def _update_summary(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    beat_id: str,
    prose_excerpt: str,
    llm: "LLMClient",
    settings: "Settings",
) -> None:
    from quillan.io import atomic_write

    summary_path = paths.continuity_summary(world, canon, series, story)
    paths.ensure(summary_path)

    current = summary_path.read_text(encoding="utf-8") if summary_path.exists() else ""

    if llm.settings.has_api_keys and prose_excerpt:
        user_prompt = get_prompt("continuity_summary_user").format(
            summary=current[:4000],
            beat_id=beat_id,
            prose_excerpt=prose_excerpt,
            max_chars=settings.continuity_summary_max_chars,
        )
        updated = await llm.call("planning", get_prompt("continuity_summary_system"), user_prompt)
    else:
        # Offline: append excerpt
        marker = f"\n\n## Beat {beat_id}\n\n"
        updated = current + marker + prose_excerpt[:500]

    atomic_write(summary_path, updated)


async def _update_threads(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    beat_id: str,
    prose_excerpt: str,
    llm: "LLMClient",
    settings: "Settings",
) -> None:
    from quillan.io import atomic_write

    threads_path = paths.continuity_threads(world, canon, series, story)
    paths.ensure(threads_path)

    current = threads_path.read_text(encoding="utf-8") if threads_path.exists() else ""

    if llm.settings.has_api_keys and prose_excerpt:
        user_prompt = get_prompt("continuity_threads_user").format(
            threads=current[:3000],
            beat_id=beat_id,
            prose_excerpt=prose_excerpt,
            max_chars=settings.continuity_open_threads_max_chars,
        )
        updated = await llm.call("planning", get_prompt("continuity_threads_system"), user_prompt)
    else:
        updated = current + f"\n- Beat {beat_id} processed"

    atomic_write(threads_path, updated)


async def _update_ledger(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    beat_id: str,
    prose_excerpt: str,
    llm: "LLMClient",
    settings: "Settings",
) -> None:
    from quillan.io import atomic_write

    ledger_path = paths.continuity_ledger(world, canon, series, story)
    paths.ensure(ledger_path)

    current = ledger_path.read_text(encoding="utf-8") if ledger_path.exists() else ""
    # Use last 2000 chars of ledger as context
    ledger_tail = current[-2000:] if len(current) > 2000 else current

    if llm.settings.has_api_keys and prose_excerpt:
        user_prompt = get_prompt("continuity_ledger_user").format(
            ledger_tail=ledger_tail,
            beat_id=beat_id,
            prose_excerpt=prose_excerpt,
            max_chars=settings.continuity_ledger_max_chars,
        )
        updated = await llm.call("planning", get_prompt("continuity_ledger_system"), user_prompt)
    else:
        entry = f"\n\n### {beat_id}\n\n- Beat processed (offline mode)\n"
        updated = current + entry

    atomic_write(ledger_path, updated)


async def _maybe_distill_summary(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    llm: "LLMClient",
    settings: "Settings",
) -> None:
    """Distill summary if it's ≥70% of the character cap."""
    from quillan.io import atomic_write

    summary_path = paths.continuity_summary(world, canon, series, story)
    if not summary_path.exists():
        return

    text = summary_path.read_text(encoding="utf-8")
    threshold = int(settings.continuity_summary_max_chars * 0.70)

    if len(text) < threshold:
        return

    if not llm.settings.has_api_keys:
        return

    user_prompt = get_prompt("continuity_distill_user").format(
        max_chars=settings.continuity_summary_max_chars // 2,
        summary=text,
    )
    distilled = await llm.call("planning", get_prompt("continuity_distill_system"), user_prompt)
    atomic_write(summary_path, distilled)
