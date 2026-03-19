"""Async pipeline orchestration: Phase1 parallel + Phase2 serial."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger("quillan.pipeline.runner")

from quillan.validate import parse_beats_mode as _parse_beats_mode  # noqa: E402

if TYPE_CHECKING:
    from quillan.config import Settings
    from quillan.llm import LLMClient
    from quillan.paths import Paths
    from quillan.telemetry import Telemetry

# Rate-limit adaptive throttle window (seconds)
_THROTTLE_WINDOW = 60.0


@dataclass
class DraftResult:
    """Outcome of a draft_story() call."""
    completed: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)  # beat_id → error message

    @property
    def has_failures(self) -> bool:
        return bool(self.failed)


async def draft_story(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    beats_mode: str | int,
    settings: "Settings",
    llm: "LLMClient",
    telemetry: "Telemetry",
    force: bool = False,
    verbose: bool = False,
    stream_path: "Path | None" = None,
    explicit_beats: "list[str] | None" = None,
    on_progress: "Callable[[str], None] | None" = None,
    on_chunk: "Callable[[str, str], None] | None" = None,
    on_beat_complete: "Callable[[str], object] | None" = None,
) -> DraftResult:
    """Two-phase pipeline over all beats in dependency order.

    Phase 1 (per batch): asyncio.gather with semaphore(max_parallel)
                         — draft + audit; adaptive throttle on 429
    Phase 2 (per batch): sequential — apply state + enqueue continuity

    *beats_mode*: "all" | int (number of beats) | "N" (string int)
    *force*: if False (default), beats with an existing Beat_Draft.md are skipped.
             If True, all selected beats are re-drafted unconditionally.
    *verbose*: if True, print one progress line per beat as it completes.
    *explicit_beats*: if set, only draft beats whose IDs are in this list.
                      Topological ordering from the full dep graph is preserved.
                      Takes precedence over beats_mode when set.

    Returns a DraftResult with completed and failed beat IDs.
    """
    from quillan.pipeline.dag import compute_batches
    from quillan.validate import validate_dependency_map

    # Load dependency map
    dep_path = paths.dependency_map(world, canon, series, story)
    if not dep_path.exists():
        raise FileNotFoundError(f"dependency_map.json not found: {dep_path}")

    dep_map = validate_dependency_map(dep_path)
    batches = compute_batches(dep_map)

    if not batches:
        return DraftResult()

    # Pre-flight: validate state file before burning LLM credits
    import yaml as _yaml
    state_path = paths.state_current(world, canon, series, story)
    if state_path.exists():
        try:
            _yaml.safe_load(state_path.read_text(encoding="utf-8"))
        except _yaml.YAMLError as exc:
            raise RuntimeError(
                f"Continuity state file is corrupt and cannot be parsed ({state_path}): {exc}\n"
                "Use 'quillan restore-state <story>' to recover from a checkpoint, "
                "or delete the file to reset state entirely."
            ) from exc

    # Filter to explicit beat set if provided (preserves topological order)
    if explicit_beats is not None:
        explicit_set = set(explicit_beats)
        batches = [
            [bid for bid in batch if bid in explicit_set]
            for batch in batches
        ]
        batches = [b for b in batches if b]
        if not batches:
            return DraftResult()

    # Determine beat limit
    beat_limit = _parse_beats_mode(beats_mode)
    beats_done = 0

    # Total beat count for progress display
    total_beats = sum(len(b) for b in batches)
    if beat_limit is not None:
        total_beats = min(total_beats, beat_limit)

    # Adaptive throttle state
    throttled_until: float = 0.0

    result = DraftResult()
    _batch_idx = 0
    _total_batches = len(batches)

    for batch in batches:
        if beat_limit is not None and beats_done >= beat_limit:
            break

        # Trim batch if approaching limit
        if beat_limit is not None:
            remaining = beat_limit - beats_done
            batch = batch[:remaining]

        _batch_idx += 1
        if on_progress:
            on_progress(f"Drafting batch {_batch_idx}/{_total_batches} ({len(batch)} beats)")

        # Phase 1: parallel draft + audit — errors isolated per beat
        batch_start = time.monotonic()
        phase1_errors = await _run_phase1_batch(
            paths, world, canon, series, story,
            batch, settings, llm, telemetry,
            throttled_until_ref=[throttled_until],
            force=force,
            verbose=verbose,
            beats_done_ref=[beats_done],
            total_beats=total_beats,
            stream_path=stream_path,
            on_chunk=on_chunk,
        )
        telemetry.record_phase_time("phase1_batch", batch_start, time.monotonic())

        # Separate successful beats from failed ones.
        # Locked beats are excluded: they were skipped in Phase 1 and have no
        # draft to process in Phase 2, so they should not appear in completed.
        failed_in_batch = set(phase1_errors.keys())
        successful_batch = [
            bid for bid in batch
            if bid not in failed_in_batch
            and not paths.beat_lock(world, canon, series, story, bid).exists()
        ]
        result.failed.update(phase1_errors)

        # Final batch-level stream update (captures any stragglers)
        if stream_path is not None:
            _update_stream_file(
                paths, world, canon, series, story,
                stream_path,
                beats_done=beats_done + len(batch),
                total_beats=total_beats,
            )

        # Phase 2: serial state + continuity (only for beats that passed Phase 1)
        phase2_start = time.monotonic()
        for beat_id in successful_batch:
            try:
                await _run_phase2_beat(
                    paths, world, canon, series, story,
                    beat_id, settings, llm, telemetry,
                )
                result.completed.append(beat_id)
                if on_beat_complete is not None:
                    try:
                        coro = on_beat_complete(beat_id)
                        if asyncio.iscoroutine(coro):
                            await coro
                    except Exception as exc:
                        logger.warning("on_beat_complete raised: %s", exc)
            except Exception as exc:
                result.failed[beat_id] = f"Phase2: {exc}"
        telemetry.record_phase_time("phase2_batch", phase2_start, time.monotonic())

        beats_done += len(batch)

    # Final continuity aggregation
    from quillan.continuity.aggregator import run_aggregator
    await run_aggregator(paths, world, canon, series, story, llm, settings)

    # Update cross-story character registry with final state
    from quillan.structure.character_registry import update_registry
    update_registry(paths, world, canon, series, story)

    if on_progress:
        on_progress("Done")
    return result


async def _run_phase1_batch(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    batch: list[str],
    settings: "Settings",
    llm: "LLMClient",
    telemetry: "Telemetry",
    throttled_until_ref: list[float],
    force: bool = False,
    verbose: bool = False,
    beats_done_ref: list[int] | None = None,
    total_beats: int = 0,
    stream_path: "Path | None" = None,
    on_chunk: "Callable[[str, str], None] | None" = None,
) -> dict[str, str]:
    """Run Phase 1 (draft + audit) for all beats in the batch in parallel.

    Returns a dict mapping beat_id -> error message for any beats that failed.
    Successful beats are not included in the returned dict.
    """
    max_p = _effective_maxp(settings.max_parallel, throttled_until_ref[0])
    sem = asyncio.Semaphore(max_p)
    # Shared counter for verbose progress (protected by the GIL for int increments)
    _counter: list[int] = [beats_done_ref[0] if beats_done_ref else 0]

    async def do_beat(beat_id: str) -> None:
        async with sem:
            await _draft_and_audit_beat(
                paths, world, canon, series, story,
                beat_id, settings, llm, telemetry,
                throttled_until_ref,
                force=force,
                verbose=verbose,
                beat_counter_ref=_counter,
                total_beats=total_beats,
                stream_path=stream_path,
                on_chunk=on_chunk,
            )

    results = await asyncio.gather(*[do_beat(bid) for bid in batch], return_exceptions=True)

    errors: dict[str, str] = {}
    for beat_id, res in zip(batch, results):
        if isinstance(res, BaseException):
            errors[beat_id] = str(res)
    return errors


async def _draft_and_audit_beat(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    beat_id: str,
    settings: "Settings",
    llm: "LLMClient",
    telemetry: "Telemetry",
    throttled_until_ref: list[float],
    force: bool = False,
    verbose: bool = False,
    beat_counter_ref: list[int] | None = None,
    total_beats: int = 0,
    stream_path: "Path | None" = None,
    on_chunk: "Callable[[str, str], None] | None" = None,
) -> None:
    """Draft one beat, audit it, retry once if audit fails.

    Skips the beat if Beat_Draft.md already exists and *force* is False.
    """
    # Locked beats are always skipped, even when force=True
    if paths.beat_lock(world, canon, series, story, beat_id).exists():
        logger.info("beat %s skipped (locked)", beat_id)
        if verbose:
            beat_counter_ref = beat_counter_ref or [0]
            beat_counter_ref[0] += 1
            _print_beat_progress(beat_counter_ref[0], total_beats, beat_id, skipped=True)
        return

    skipped = not force and paths.beat_draft(world, canon, series, story, beat_id).exists()

    if skipped:
        if verbose:
            beat_counter_ref = beat_counter_ref or [0]
            beat_counter_ref[0] += 1
            _print_beat_progress(beat_counter_ref[0], total_beats, beat_id, skipped=True)
        return

    from quillan.draft.draft import draft_beat
    from quillan.draft.audit import mega_audit
    from quillan.llm import _RateLimitError, LLMError

    drafted_tokens = 0
    max_attempts = settings.draft_audit_retries + 1
    for attempt in range(max_attempts):
        try:
            ok = await draft_beat(
                paths, world, canon, series, story, beat_id, attempt, llm, settings,
                on_chunk=on_chunk,
            )
            if not ok:
                raise LLMError(f"LLM call failed for beat {beat_id} (attempt {attempt + 1})")

            # Capture token count for progress display
            if verbose:
                from quillan.token_tool import estimate_tokens
                draft_path = paths.beat_draft(world, canon, series, story, beat_id)
                if draft_path.exists():
                    drafted_tokens = estimate_tokens(draft_path.read_text(encoding="utf-8"))

            audit_result = await mega_audit(
                paths, world, canon, series, story, beat_id, llm
            )

            if audit_result.get("overall_pass", True):
                break

            # Audit failed — retry with fix_list injected into bundle (attempt+1)
            if verbose and attempt < max_attempts - 1:
                fix_count = len(audit_result.get("fix_list", []))
                print(
                    f"  [audit] {beat_id} failed ({fix_count} fixes) — retrying "
                    f"(attempt {attempt + 2}/{max_attempts})",
                    flush=True,
                )

        except _RateLimitError:
            # Signal adaptive throttle
            throttled_until_ref[0] = time.monotonic() + _THROTTLE_WINDOW
            raise
        except Exception as exc:
            logger.warning("Beat %s failed (attempt %d): %s", beat_id, attempt + 1, exc)
            raise

    if verbose:
        beat_counter_ref = beat_counter_ref or [0]
        beat_counter_ref[0] += 1
        _print_beat_progress(beat_counter_ref[0], total_beats, beat_id, tokens=drafted_tokens)

    # Per-beat stream update (more granular than per-batch)
    if stream_path is not None:
        _update_stream_file(paths, world, canon, series, story, stream_path,
                            beats_done=0, total_beats=total_beats)


async def _run_phase2_beat(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    beat_id: str,
    settings: "Settings",
    llm: "LLMClient",
    telemetry: "Telemetry",
) -> None:
    """Phase 2: extract state patch, apply it, enqueue continuity delta."""
    import aiofiles
    from quillan.continuity.state import extract_state_patch, apply_state_patch
    from quillan.continuity.queue import enqueue_delta
    from quillan.io import atomic_write
    import yaml

    # Extract state patch
    patch = await extract_state_patch(
        paths, world, canon, series, story, beat_id, llm
    )

    # Load current state
    state_path = paths.state_current(world, canon, series, story)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    current_state: dict = {}
    if state_path.exists():
        try:
            async with aiofiles.open(state_path, encoding="utf-8") as _f:
                _state_text = await _f.read()
        except OSError:
            _state_text = ""
        if _state_text:
            try:
                current_state = yaml.safe_load(_state_text) or {}
            except yaml.YAMLError as exc:
                raise RuntimeError(
                    f"Continuity state file corrupted ({state_path}): {exc}\n"
                    "Use 'quillan restore-state <story>' to recover from a checkpoint, "
                    "or delete the file to reset state entirely."
                ) from exc

    if not current_state:
        # New story: initialise with schema version so future migrations have a baseline
        current_state = {
            "_meta": {"schema_version": 1},
            "characters": {},
            "world_state": {},
            "events": [],
        }

    # Checkpoint: save the pre-write state before overwriting current_state.yaml
    if state_path.exists():
        import datetime
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        ckpt_path = paths.state_checkpoint(world, canon, series, story, beat_id, ts)
        ckpt_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(ckpt_path, state_path.read_text(encoding="utf-8"))

    # Apply patch and save
    new_state = apply_state_patch(current_state, patch)
    atomic_write(state_path, yaml.dump(new_state, default_flow_style=False, allow_unicode=True))

    # Save beat-specific state snapshot
    beat_state_path = paths.state_bundle(world, canon, series, story, beat_id)
    atomic_write(beat_state_path, yaml.dump(new_state, default_flow_style=False, allow_unicode=True))

    # Enqueue continuity delta
    beat_dir = paths.beat(world, canon, series, story, beat_id)
    enqueue_delta(paths, world, canon, series, story, beat_id, beat_dir)


def _effective_maxp(max_parallel: int, throttled_until: float) -> int:
    """Return max_parallel // 2 if within throttle window, else max_parallel."""
    if time.monotonic() < throttled_until:
        return max(1, max_parallel // 2)
    return max(1, max_parallel)


def _print_beat_progress(
    n: int, total: int, beat_id: str, tokens: int = 0, skipped: bool = False
) -> None:
    """Print a one-line progress update for one beat."""
    counter = f"[{n}/{total}]" if total > 0 else f"[{n}]"
    if skipped:
        print(f"  {counter} {beat_id} skipped (already drafted)", flush=True)
    elif tokens > 0:
        print(f"  {counter} {beat_id} drafted (~{tokens} tokens)", flush=True)
    else:
        print(f"  {counter} {beat_id} drafted", flush=True)


def _update_stream_file(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    stream_path: Path,
    beats_done: int,
    total_beats: int,
) -> None:
    """Overwrite stream_path with a coherent Markdown draft of all beats written so far.

    Reads Outline.yaml for narrative order so chapters appear front-to-back
    regardless of the dependency-sorted drafting order.  Uses atomic_write so
    the file is never partially written when a reader opens it.
    """
    import yaml as _yaml
    from quillan.io import atomic_write

    outline_path = paths.outline(world, canon, series, story)
    if not outline_path.exists():
        return
    outline_data = _yaml.safe_load(outline_path.read_text(encoding="utf-8")) or {}
    chapters = outline_data.get("chapters")
    if not chapters:
        return

    title = outline_data.get("title", story.replace("_", " ").title())
    fm_data = {"title": title, "status": f"draft-in-progress ({beats_done}/{total_beats} beats)"}
    front_matter = "---\n" + _yaml.dump(fm_data, default_flow_style=False) + "---\n\n"
    doc_parts = [front_matter, f"# {title}\n\n"]

    chapter_sections: dict[int, list[str]] = {}
    chapter_titles: dict[int, str] = {}
    for chapter in chapters:
        ch_num = chapter.get("chapter", 0)
        chapter_titles[ch_num] = chapter.get("title", f"Chapter {ch_num}")
        chapter_sections[ch_num] = []
        for beat in chapter.get("beats", []):
            beat_id = beat.get("beat_id")
            if not beat_id:
                continue
            draft_path = paths.beat_draft(world, canon, series, story, beat_id)
            if draft_path.exists():
                prose = draft_path.read_text(encoding="utf-8", errors="replace").strip()
                if prose:
                    chapter_sections[ch_num].append(prose)

    for ch_num in sorted(chapter_sections.keys()):
        doc_parts.append(f"## {chapter_titles.get(ch_num, f'Chapter {ch_num}')}\n\n")
        for prose in chapter_sections[ch_num]:
            doc_parts.append(prose + "\n\n")

    stream_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(stream_path, "".join(doc_parts))
