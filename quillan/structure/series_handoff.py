"""Series handoff: register story order and surface prior-story continuity.

No LLM calls — pure filesystem I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from quillan.paths import Paths

_STATE_CAP = 2000
_SUMMARY_CAP = 3000
_THREADS_CAP = 1500


def register_and_get_prior_story(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
) -> str | None:
    """Register *story* in Series_Order.yaml and return the name of its predecessor.

    - Reads Series_Order.yaml (creates an empty list if the file is missing).
    - Appends *story* if not already present; atomic-writes back.
    - Returns the entry immediately before *story*, or None if *story* is first.
    """
    from quillan.io import atomic_write
    from quillan.lock import sync_file_lock

    order_path = paths.series_order(world, canon, series)
    paths.ensure(order_path)

    with sync_file_lock(order_path.with_suffix(".lock")):
        # Load existing order list
        stories: list[str] = []
        if order_path.exists():
            raw = order_path.read_text(encoding="utf-8")
            data = yaml.safe_load(raw) or {}
            stories = list(data.get("stories", []))

        # Append if new (idempotent)
        if story not in stories:
            stories.append(story)
            atomic_write(order_path, yaml.dump({"stories": stories}, default_flow_style=False))

    idx = stories.index(story)
    return stories[idx - 1] if idx > 0 else None


def build_prior_story_section(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    prior_story: str,
) -> str:
    """Build a markdown section summarising *prior_story*'s final continuity state.

    Loads up to three artefacts (each silently skipped if missing):
    - state/current_state.yaml   capped at _STATE_CAP chars
    - continuity/Summary.md      capped at _SUMMARY_CAP chars
    - continuity/Open_Threads.md capped at _THREADS_CAP chars

    Returns "" if all three artefacts are missing (story was never drafted).
    """
    state_path = paths.state_current(world, canon, series, prior_story)
    summary_path = paths.continuity_summary(world, canon, series, prior_story)
    threads_path = paths.continuity_threads(world, canon, series, prior_story)

    state_text = ""
    if state_path.exists():
        raw = yaml.safe_load(state_path.read_text(encoding="utf-8")) or {}
        # Strip internal metadata keys; keep only characters + world_state
        filtered: dict = {
            k: v for k, v in raw.items() if not k.startswith("_")
        }
        if filtered:
            state_text = yaml.dump(filtered, default_flow_style=False, allow_unicode=True)
            state_text = state_text[:_STATE_CAP]

    summary_text = ""
    if summary_path.exists():
        summary_text = summary_path.read_text(encoding="utf-8")[:_SUMMARY_CAP]

    threads_text = ""
    if threads_path.exists():
        threads_text = threads_path.read_text(encoding="utf-8")[:_THREADS_CAP]

    if not state_text and not summary_text and not threads_text:
        return ""

    parts: list[str] = [f"## Prior Story: {prior_story}\n"]

    if state_text:
        parts.append("### Final State Snapshot\n```yaml\n" + state_text.rstrip() + "\n```")

    if summary_text:
        parts.append("### Narrative Summary\n" + summary_text.rstrip())

    if threads_text:
        parts.append("### Open Threads Carried Forward\n" + threads_text.rstrip())

    return "\n\n".join(parts) + "\n"
