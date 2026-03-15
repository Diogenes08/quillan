"""Outline editing utilities for F3 — Interactive Outline Editor.

Provides validation, dep-map rebuilding, and beat-insertion helpers used by
the show-outline / edit-outline / add-beat CLI commands.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from quillan.paths import Paths

# Pattern for canonical beat IDs: C{n}-S{n}-B{n}
_BEAT_ID_RE = re.compile(r"^C(\d+)-S(\d+)-B(\d+)$")


# ── Validation ────────────────────────────────────────────────────────────────


def validate_outline(data: object) -> list[str]:
    """Return a list of human-readable error strings for *data*.

    An empty list means the outline is valid.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["Outline must be a YAML mapping at the top level."]

    if "title" not in data:
        errors.append("Missing required field: title")
    if "chapters" not in data:
        errors.append("Missing required field: chapters")
        return errors  # nothing else to check without chapters

    chapters = data["chapters"]
    if not isinstance(chapters, list) or not chapters:
        errors.append("'chapters' must be a non-empty list.")
        return errors

    seen_beat_ids: set[str] = set()
    for ch_idx, chapter in enumerate(chapters):
        ch_label = f"Chapter {chapter.get('chapter', ch_idx + 1)}"
        if not isinstance(chapter, dict):
            errors.append(f"{ch_label}: must be a mapping.")
            continue
        beats = chapter.get("beats")
        if not isinstance(beats, list) or not beats:
            errors.append(f"{ch_label}: 'beats' must be a non-empty list.")
            continue
        for b_idx, beat in enumerate(beats):
            b_label = f"{ch_label} beat {b_idx + 1}"
            if not isinstance(beat, dict):
                errors.append(f"{b_label}: must be a mapping.")
                continue
            if not beat.get("beat_id"):
                errors.append(f"{b_label}: missing 'beat_id'.")
            else:
                bid = beat["beat_id"]
                if bid in seen_beat_ids:
                    errors.append(f"Duplicate beat_id: {bid!r}")
                seen_beat_ids.add(bid)
            if not beat.get("goal"):
                errors.append(f"{b_label} ({beat.get('beat_id', '?')}): missing 'goal'.")

    return errors


# ── Dep-map rebuild ───────────────────────────────────────────────────────────


def rebuild_dep_map_linear(outline_data: dict) -> dict:
    """Build a linear dependency chain from outline beat order.

    Each beat depends on the immediately preceding beat across all chapters,
    exactly as ingest does. The result can be written directly to
    dependency_map.json.
    """
    from quillan.validate import extract_beat_ids

    beat_ids = extract_beat_ids(outline_data)
    deps: dict[str, list[str]] = {}
    prev: str | None = None
    for bid in beat_ids:
        deps[bid] = [prev] if prev else []
        prev = bid
    return {"dependencies": deps}


# ── Beat insertion ────────────────────────────────────────────────────────────


def _next_beat_id(outline_data: dict, chapter_num: int) -> str:
    """Return the next sequential beat_id for *chapter_num*.

    Scans existing beats in that chapter and increments the highest B-number.
    Falls back to B1 if the chapter is empty or has no parseable IDs.
    """
    for chapter in outline_data.get("chapters", []):
        if chapter.get("chapter") == chapter_num:
            max_b = 0
            for beat in chapter.get("beats", []):
                m = _BEAT_ID_RE.match(beat.get("beat_id", ""))
                if m and int(m.group(1)) == chapter_num:
                    max_b = max(max_b, int(m.group(3)))
            return f"C{chapter_num}-S1-B{max_b + 1}"
    return f"C{chapter_num}-S1-B1"


def add_beat_to_outline(
    outline_data: dict,
    chapter_num: int,
    goal: str,
    title: str = "",
    word_count: int = 1500,
) -> tuple[dict, str]:
    """Append a new beat to *chapter_num* in *outline_data*.

    Returns ``(updated_outline_data, new_beat_id)``.
    Raises ``ValueError`` if *chapter_num* does not exist in the outline.
    """
    import copy

    data = copy.deepcopy(outline_data)
    beat_id = _next_beat_id(data, chapter_num)

    new_beat = {
        "beat_id": beat_id,
        "title": title or f"Beat {beat_id.split('-B')[-1]}",
        "goal": goal,
        "setting": "(edit as needed)",
        "characters": [],
        "word_count_target": word_count,
    }

    for chapter in data.get("chapters", []):
        if chapter.get("chapter") == chapter_num:
            chapter.setdefault("beats", []).append(new_beat)
            return data, beat_id

    raise ValueError(
        f"Chapter {chapter_num} not found in outline. "
        f"Available: {[c.get('chapter') for c in data.get('chapters', [])]}"
    )


# ── Stub beat spec ────────────────────────────────────────────────────────────


def write_stub_beat_spec(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    beat_id: str,
    goal: str,
    title: str = "",
    word_count: int = 1500,
) -> Path:
    """Create a minimal beat_spec.yaml for a newly added beat.

    Safe to call multiple times — won't overwrite an existing spec.
    """
    from quillan.io import atomic_write

    spec_path = paths.beat_spec(world, canon, series, story, beat_id)
    if spec_path.exists():
        return spec_path

    spec = {
        "beat_id": beat_id,
        "title": title or f"Beat {beat_id.split('-B')[-1]}",
        "goal": goal,
        "setting": "(edit as needed)",
        "characters": [],
        "pov_character": "",
        "tone": "neutral",
        "word_count_target": word_count,
        "emotional_beat": "(edit as needed)",
        "theme_payoff": "(edit as needed)",
        "pacing": "medium",
        "scope": [goal],
        "out_of_scope": [],
        "rules": [],
        "dependencies": [],
        "arc_position": "",
    }

    paths.ensure(spec_path)
    atomic_write(spec_path, yaml.dump(spec, allow_unicode=True, sort_keys=False))
    return spec_path


# ── Outline display ───────────────────────────────────────────────────────────


def format_outline(
    outline_data: dict,
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
) -> str:
    """Return a human-readable outline string for terminal display."""
    title = outline_data.get("title", story)
    genre = outline_data.get("genre", "")
    theme = outline_data.get("theme", "")

    header = f'Outline: {story} — "{title}"'
    if genre:
        header += f" ({genre})"

    lines: list[str] = [header, ""]
    if theme and theme not in ("(imported — edit as needed)",):
        lines.append(f"Theme: {theme}")
        lines.append("")

    total_beats = 0
    total_words = 0
    drafted_count = 0

    for chapter in outline_data.get("chapters", []):
        ch_num = chapter.get("chapter", "?")
        ch_title = chapter.get("title", f"Chapter {ch_num}")
        beats = chapter.get("beats", [])
        lines.append(f"Chapter {ch_num}: {ch_title} ({len(beats)} beat{'s' if len(beats) != 1 else ''})")

        for beat in beats:
            bid = beat.get("beat_id", "?")
            b_title = beat.get("title", "")
            b_goal = beat.get("goal", "")
            wc = beat.get("word_count_target", 0)
            display = b_title if b_title and b_title not in (f"Beat {bid.split('-B')[-1]}", "(imported beat — edit as needed)") else b_goal
            display = display[:48] + "…" if len(display) > 50 else display

            # Draft status
            draft_path = paths.beat_draft(world, canon, series, story, bid)
            status = "[drafted]" if draft_path.exists() else "[pending]"
            if draft_path.exists():
                drafted_count += 1

            lines.append(f"  {bid:<14}  {display:<50}  {wc:>5}w  {status}")
            total_beats += 1
            total_words += wc

        lines.append("")

    pct = f"{drafted_count * 100 // total_beats}%" if total_beats else "0%"
    lines.append(
        f"{total_beats} beat{'s' if total_beats != 1 else ''} · "
        f"{total_words:,} words target · "
        f"{drafted_count} drafted ({pct})"
    )

    return "\n".join(lines)
