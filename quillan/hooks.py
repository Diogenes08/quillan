"""Plugin/Hook System for Quillan — F9.

Hooks are executable shell scripts that fire at key pipeline events. They are
discovered in three directories, searched in order (all three fire — not
first-wins):

  1. <story>/hooks/<event>[.sh]   — story-level hooks
  2. <world>/hooks/<event>[.sh]   — world-level hooks
  3. <data_dir>/hooks/<event>[.sh] — global hooks

Supported events
----------------
  post_beat              After each beat's Phase 2 (state + continuity) completes.
  post_draft             After a full draft run (all selected beats) completes.
  post_create            After story planning pipeline completes.
  post_revise            After a revise_beat() call completes.
  post_ingest            After ingest_manuscript() completes.
  post_continuity_check  After check_drift() completes.

Environment variables
---------------------
All hooks receive:
  QUILLAN_EVENT          Event name (e.g. "post_beat")
  QUILLAN_STORY          Story slug
  QUILLAN_WORLD          World name
  QUILLAN_CANON          Canon name
  QUILLAN_SERIES         Series name
  QUILLAN_DATA_DIR       Absolute path to the data directory

Additional per-event variables:
  post_beat:             QUILLAN_BEAT_ID, QUILLAN_DRAFT_PATH
  post_draft:            QUILLAN_BEATS_COMPLETED, QUILLAN_BEATS_FAILED
  post_revise:           QUILLAN_BEAT_ID, QUILLAN_DRAFT_PATH
  post_ingest:           QUILLAN_BEAT_COUNT
  post_continuity_check: QUILLAN_ISSUE_COUNT, QUILLAN_WARN_COUNT
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quillan.paths import Paths

logger = logging.getLogger("quillan.hooks")

HOOK_EVENTS: frozenset[str] = frozenset({
    "post_beat",
    "post_draft",
    "post_create",
    "post_revise",
    "post_ingest",
    "post_continuity_check",
})

# Default timeout per hook script (seconds)
_DEFAULT_TIMEOUT = 30.0


def discover_hooks(
    event: str,
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
) -> list[Path]:
    """Return all executable hook scripts for *event*, in fire order.

    Order: story-level → world-level → global. Only one script per
    directory per event (``<event>.sh`` preferred, then ``<event>``).
    All discovered scripts are returned; they all run.
    """
    dirs: list[Path] = [
        paths.story_hooks_dir(world, canon, series, story),
        paths.world_hooks_dir(world),
        paths.global_hooks_dir(),
    ]
    found: list[Path] = []
    for d in dirs:
        if not d.is_dir():
            continue
        for name in (f"{event}.sh", event):
            p = d / name
            if p.is_file() and os.access(p, os.X_OK):
                found.append(p)
                break  # one script per directory per event
    return found


def _build_env(
    event: str,
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    extra_env: dict[str, str] | None,
) -> dict[str, str]:
    """Merge process environment with Quillan context variables."""
    env = {**os.environ}
    env.update({
        "QUILLAN_EVENT": event,
        "QUILLAN_STORY": story,
        "QUILLAN_WORLD": world,
        "QUILLAN_CANON": canon,
        "QUILLAN_SERIES": series,
        "QUILLAN_DATA_DIR": str(paths.data_dir),
    })
    if extra_env:
        env.update(extra_env)
    return env


async def _execute_hook(script: Path, env: dict[str, str], timeout: float) -> None:
    """Run *script* as a subprocess. Logs output and errors; never raises."""
    try:
        proc = await asyncio.create_subprocess_exec(
            str(script),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            logger.warning("Hook %s timed out after %.0fs — killed.", script.name, timeout)
            return

        output = stdout.decode("utf-8", errors="replace").strip()
        if output:
            for line in output.splitlines():
                logger.debug("[hook:%s] %s", script.name, line)

        if proc.returncode != 0:
            logger.warning(
                "Hook %s exited with code %d.", script.name, proc.returncode
            )
    except Exception as exc:
        logger.warning("Hook %s failed to execute: %s", script.name, exc)


async def run_hooks(
    event: str,
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    *,
    extra_env: dict[str, str] | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> None:
    """Discover and run all hooks for *event*. Errors are logged, not raised.

    Hooks are awaited sequentially in discovery order (story → world → global)
    so each hook sees the results of earlier hooks if they modify shared files.
    """
    scripts = discover_hooks(event, paths, world, canon, series, story)
    if not scripts:
        return

    env = _build_env(event, paths, world, canon, series, story, extra_env)
    for script in scripts:
        logger.debug("Running hook: %s (%s)", script.name, event)
        await _execute_hook(script, env, timeout=timeout)
