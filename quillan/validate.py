"""YAML/JSON schema validators for Quillan2 artifacts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml


def validate_json(path: Path) -> dict:
    """Parse JSON from *path* and return as dict. Raises ValueError on failure."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ValueError(f"Cannot read {path}: {e}") from e

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {path}: {e}") from e

    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}, got {type(data).__name__}")
    return data


def validate_yaml(path: Path) -> dict:
    """Parse YAML from *path* and return as dict. Raises ValueError on failure."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ValueError(f"Cannot read {path}: {e}") from e

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in {path}: {e}") from e

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected YAML mapping in {path}, got {type(data).__name__}")
    return data


def validate_keys(data: dict, *keys: str) -> None:
    """Raise ValueError if any required *keys* are missing from *data*."""
    missing = [k for k in keys if k not in data]
    if missing:
        raise ValueError(f"Missing required keys: {missing}")


def validate_beat_spec(path: Path) -> dict:
    """Validate a beat spec YAML file. Required keys: beat_id, goal."""
    data = validate_yaml(path)
    validate_keys(data, "beat_id", "goal")
    return data


def validate_local_state(path: Path) -> dict:
    """Validate a local state YAML file. Required key: characters."""
    data = validate_yaml(path)
    validate_keys(data, "characters")
    return data


def validate_dependency_map(path: Path) -> dict:
    """Validate a dependency map JSON file. Required key: dependencies."""
    data = validate_json(path)
    validate_keys(data, "dependencies")
    return data


def validate_creative_brief(path: Path) -> dict:
    """Validate Creative_Brief.yaml. Required keys: voice, arc_intent."""
    data = validate_yaml(path)
    validate_keys(data, "voice", "arc_intent")
    return data


def validate_story_spine(path: Path) -> dict:
    """Validate Story_Spine.yaml. Required keys: structure, acts, beat_tension."""
    data = validate_yaml(path)
    validate_keys(data, "structure", "acts", "beat_tension")
    return data


def validate_character_arcs(path: Path) -> dict:
    """Validate Character_Arcs.yaml. Required key: characters."""
    data = validate_yaml(path)
    validate_keys(data, "characters")
    return data


def validate_subplot_register(path: Path) -> dict:
    """Validate Subplot_Register.yaml. Required key: subplots."""
    data = validate_yaml(path)
    validate_keys(data, "subplots")
    return data


def validate_conflict_map(path: Path) -> dict:
    """Validate Conflict_Map.yaml. Required keys: protagonist_goal, core_conflict."""
    data = validate_yaml(path)
    validate_keys(data, "protagonist_goal", "core_conflict")
    return data


def extract_beat_ids(outline_data: dict) -> list[str]:
    """Extract all beat_id values from an outline dict in chapter/beat order."""
    ids: list[str] = []
    for chapter in outline_data.get("chapters", []):
        for beat in chapter.get("beats", []):
            bid = beat.get("beat_id")
            if bid:
                ids.append(bid)
    return ids


def parse_beats_mode(beats_mode: str | int) -> int | None:
    """Return int beat limit or None (= no limit / 'all')."""
    if beats_mode == "all":
        return None
    try:
        return int(beats_mode)
    except (ValueError, TypeError):
        return None


_SAFE_SLUG_RE = re.compile(r"[^a-z0-9_-]")


def sanitize_story_name(raw: str, *, fallback: str = "story", max_len: int = 60) -> str:
    """Reduce *raw* to a safe filesystem slug: lowercase [a-z0-9_-], max 60 chars."""
    slug = raw.lower().replace(" ", "_")
    slug = _SAFE_SLUG_RE.sub("", slug).strip("_-")
    return slug[:max_len] or fallback


_BEAT_ID_RE = re.compile(r"^C\d+-S\d+-B\d+$")


def validate_beat_id(beat_id: str) -> bool:
    """Return True if *beat_id* matches the pattern C\\d+-S\\d+-B\\d+."""
    return bool(_BEAT_ID_RE.match(beat_id))


def py_extract_json(text: str, required_keys: list[str] | None = None) -> dict:
    """Extract JSON from LLM output.

    Strategy:
    1. Strip markdown fences (```json ... ```)
    2. Try json.loads
    3. Try yaml.safe_load as fallback
    4. Validate required_keys if provided

    Raises ValueError on all failure modes.
    """
    # Strip markdown fences
    stripped = _strip_fences(text)

    # Try JSON parse
    data: Any = None
    json_err: Exception | None = None
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as e:
        json_err = e

    if data is None:
        # Try YAML fallback
        try:
            data = yaml.safe_load(stripped)
        except yaml.YAMLError as ye:
            raise ValueError(
                f"Failed to parse LLM output as JSON ({json_err}) or YAML ({ye}).\n"
                f"Raw text (first 200 chars): {text[:200]!r}"
            ) from ye

    if not isinstance(data, dict):
        raise ValueError(
            f"Expected JSON object from LLM, got {type(data).__name__}. "
            f"Raw (first 200 chars): {text[:200]!r}"
        )

    if required_keys:
        validate_keys(data, *required_keys)

    return data


def _strip_fences(text: str) -> str:
    """Remove leading/trailing markdown code fences."""
    text = text.strip()
    # Remove ```json or ``` at start
    text = re.sub(r"^```(?:json|yaml|yml)?\s*\n?", "", text)
    # Remove ``` at end
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()
