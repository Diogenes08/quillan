"""State patch extraction and application for Quillan2 continuity."""

from __future__ import annotations

import copy
import logging
from quillan.templates import get_prompt
from typing import TYPE_CHECKING, Any

logger = logging.getLogger("quillan.continuity.state")

if TYPE_CHECKING:
    from quillan.llm import LLMClient
    from quillan.paths import Paths



# Paths in the state that must never be mutated by patches
_DISALLOWED_MUTATION_PREFIXES: tuple[str, ...] = (
    "_meta",
    "_locked",
)


async def extract_state_patch(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    beat_id: str,
    llm: "LLMClient",
) -> dict:
    """LLM forensic call → {set, append, delete} patch dict.

    Returns empty patch if no API keys are configured.
    """
    empty_patch: dict = {"set": {}, "append": {}, "delete": []}

    if not llm.settings.has_api_keys:
        return empty_patch

    draft_path = paths.beat_draft(world, canon, series, story, beat_id)
    if not draft_path.exists():
        return empty_patch

    prose = draft_path.read_text(encoding="utf-8")

    # Get current state summary for context
    state_path = paths.state_current(world, canon, series, story)
    state_summary = ""
    if state_path.exists():
        import yaml
        try:
            state_data = yaml.safe_load(state_path.read_text(encoding="utf-8")) or {}
            # Include characters and world_state for context
            chars = list(state_data.get("characters", {}).keys())
            world_st = state_data.get("world_state", {})
            state_summary = f"characters: {chars}"
            if world_st:
                state_summary += f"\nworld_state: {dict(list(world_st.items())[:10])}"
        except Exception as exc:
            logger.warning("Could not load state file for summary: %s", exc)

    user_prompt = get_prompt("state_extract_user", story_dir=paths.story(world, canon, series, story), world_dir=paths.world(world)).format(
        prose=prose[:6000],
        state_summary=state_summary,
    )

    try:
        result = await llm.call_json(
            "forensic",
            get_prompt("state_extract_system", story_dir=paths.story(world, canon, series, story), world_dir=paths.world(world)),
            user_prompt,
            required_keys=["set", "append", "delete"],
        )
        return result
    except Exception as exc:
        logger.warning("State patch extraction failed, returning empty patch: %s", exc)
        return empty_patch


def _validate_patch(patch: dict) -> None:
    """Raise ValueError if patch shape is wrong.

    A valid patch must have:
      - 'set'    → dict  (or absent)
      - 'append' → dict  (or absent)
      - 'delete' → list  (or absent)
    """
    if not isinstance(patch.get("set", {}), dict):
        raise ValueError(f"Patch 'set' must be a dict, got {type(patch['set'])!r}")
    if not isinstance(patch.get("append", {}), dict):
        raise ValueError(f"Patch 'append' must be a dict, got {type(patch['append'])!r}")
    if not isinstance(patch.get("delete", []), list):
        raise ValueError(f"Patch 'delete' must be a list, got {type(patch['delete'])!r}")


def apply_state_patch(state: dict, patch: dict) -> dict:
    """Deep merge patch into state dict with disallowed_mutations enforcement.

    Raises ValueError if the patch shape is invalid (e.g. 'set' is not a dict).

    Algorithm:
    1. Validate patch shape
    2. Snapshot disallowed paths
    3. Apply set/append/delete
    4. Restore any disallowed mutations
    5. Return new state dict
    """
    _validate_patch(patch)
    new_state = copy.deepcopy(state)

    # 1. Snapshot disallowed paths
    disallowed_snapshots: dict[str, Any] = {}
    for prefix in _DISALLOWED_MUTATION_PREFIXES:
        parts = prefix.split(".")
        val = _get_nested(new_state, parts)
        if val is not None:
            disallowed_snapshots[prefix] = copy.deepcopy(val)

    # 2a. Apply "set" operations
    for dot_path, value in patch.get("set", {}).items():
        parts = dot_path.split(".")
        _set_nested(new_state, parts, value)

    # 2b. Apply "append" operations
    for dot_path, value in patch.get("append", {}).items():
        parts = dot_path.split(".")
        existing = _get_nested(new_state, parts)
        if isinstance(existing, list):
            existing.append(value)
        elif existing is None:
            _set_nested(new_state, parts, [value])
        # If it's not a list, skip silently (type mismatch)

    # 2c. Apply "delete" operations
    for dot_path in patch.get("delete", []):
        parts = dot_path.split(".")
        _delete_nested(new_state, parts)

    # 3. Restore disallowed mutations
    for prefix, original_val in disallowed_snapshots.items():
        parts = prefix.split(".")
        _set_nested(new_state, parts, original_val)

    return new_state


# ── Nested dict helpers ───────────────────────────────────────────────────────

def _get_nested(d: dict, parts: list[str]) -> Any:
    """Get a value from a nested dict using a list of key parts."""
    cur = d
    for part in parts:
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _set_nested(d: dict, parts: list[str], value: Any) -> None:
    """Set a value in a nested dict, creating intermediate dicts as needed."""
    cur = d
    for part in parts[:-1]:
        if part not in cur or not isinstance(cur[part], dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value


def _delete_nested(d: dict, parts: list[str]) -> None:
    """Delete a key from a nested dict. No-op if path doesn't exist."""
    cur = d
    for part in parts[:-1]:
        if not isinstance(cur, dict) or part not in cur:
            return
        cur = cur[part]
    if isinstance(cur, dict):
        cur.pop(parts[-1], None)
