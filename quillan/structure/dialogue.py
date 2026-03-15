"""Character voice profile generation and loading — F6: Dialogue System.

Voice profiles are YAML files stored at structure/dialogue/<slug>.yaml.
They capture speech patterns, vocabulary level, verbal tics, and emotional
tells so the LLM can write consistent, character-specific dialogue.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from quillan.templates import get_prompt

if TYPE_CHECKING:
    from quillan.llm import LLMClient
    from quillan.paths import Paths
    from quillan.config import Settings

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_REQUIRED_KEYS = [
    "character", "speech_patterns", "vocabulary_level",
    "verbal_tics", "avoids", "emotional_tells", "sample_lines",
]

# Cap on character arc text fed to the LLM
_ARC_MAX_CHARS = 3000
_CONTEXT_MAX_CHARS = 1500


def character_slug(name: str) -> str:
    """Convert a character name to a filesystem-safe slug."""
    slug = _SLUG_RE.sub("_", name.lower()).strip("_")
    return slug or "unknown"


async def generate_voice_profile(
    character_name: str,
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    llm: "LLMClient",
    settings: "Settings",
) -> Path | None:
    """Call the LLM to generate a voice profile and write it to disk.

    Pulls context from Character_Arcs.yaml and Creative_Brief.yaml if
    they exist. Returns the profile path on success, None on LLM failure.
    """
    from quillan.llm import LLMError
    from quillan.io import atomic_write

    slug = character_slug(character_name)
    _story_dir = paths.story(world, canon, series, story)
    _world_dir = paths.world(world)

    # ── Gather context ────────────────────────────────────────────────────

    arc_info = _extract_arc_info(paths, world, canon, series, story, character_name)
    story_context = _extract_story_context(paths, world, canon, series, story)

    system = get_prompt("voice_profile_system", story_dir=_story_dir, world_dir=_world_dir)
    user = get_prompt("voice_profile_user", story_dir=_story_dir, world_dir=_world_dir).format(
        character_name=character_name,
        arc_info=arc_info or "(no character arc information available)",
        story_context=story_context or "(no story context available)",
    )

    try:
        profile_data = await llm.call_json(
            "planning", system, user, required_keys=_REQUIRED_KEYS
        )
    except LLMError as exc:
        import logging
        logging.getLogger("quillan.structure.dialogue").warning(
            "Voice profile generation failed for %r: %s", character_name, exc
        )
        return None

    profile_path = paths.voice_profile(world, canon, series, story, slug)
    paths.ensure(profile_path)
    atomic_write(profile_path, yaml.dump(profile_data, allow_unicode=True, sort_keys=False))
    return profile_path


def load_voice_profiles(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    character_names: list[str] | None = None,
) -> dict[str, dict]:
    """Return ``{character_name: profile_dict}`` for available voice profiles.

    If *character_names* is given, only load profiles for those characters.
    Silently skips characters whose profile file doesn't exist.
    """
    dialogue_dir = paths.dialogue_dir(world, canon, series, story)
    if not dialogue_dir.exists():
        return {}

    profiles: dict[str, dict] = {}
    candidates: list[tuple[str, str]] = []

    if character_names is not None:
        for name in character_names:
            candidates.append((name, character_slug(name)))
    else:
        for p in sorted(dialogue_dir.glob("*.yaml")):
            candidates.append((p.stem, p.stem))  # slug as name when loading all

    for name, slug in candidates:
        profile_path = paths.voice_profile(world, canon, series, story, slug)
        if not profile_path.exists():
            continue
        try:
            data = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
            if data:
                profiles[data.get("character", name)] = data
        except (yaml.YAMLError, OSError):
            pass

    return profiles


def format_voice_section(profiles: dict[str, dict]) -> str:
    """Format loaded voice profiles into a context-bundle section string."""
    if not profiles:
        return ""

    parts: list[str] = []
    for char_name, profile in profiles.items():
        lines: list[str] = [f"### {char_name}"]

        vocab = profile.get("vocabulary_level", "")
        if vocab:
            lines.append(f"**Register:** {vocab}")

        patterns = profile.get("speech_patterns", [])
        if patterns:
            lines.append("**Speech patterns:**")
            for p in patterns:
                lines.append(f"- {p}")

        tics = profile.get("verbal_tics", [])
        if tics:
            lines.append("**Verbal tics:**")
            for t in tics:
                lines.append(f"- {t}")

        avoids = profile.get("avoids", [])
        if avoids:
            lines.append(f"**Avoids:** {', '.join(avoids)}")

        tells = profile.get("emotional_tells", [])
        if tells:
            lines.append("**Under pressure:**")
            for t in tells:
                lines.append(f"- {t}")

        samples = profile.get("sample_lines", [])
        if samples:
            lines.append("**Voice samples:**")
            for s in samples:
                lines.append(f'> "{s}"')

        parts.append("\n".join(lines))

    return (
        "# Character Voices\n\n"
        "Write each character's dialogue and interior monologue to match their "
        "voice profile below.\n\n"
        + "\n\n".join(parts)
    )


# ── Private helpers ───────────────────────────────────────────────────────────


def _extract_arc_info(
    paths: "Paths", world: str, canon: str, series: str, story: str, character_name: str
) -> str:
    """Pull this character's arc section from Character_Arcs.yaml."""
    arcs_path = paths.character_arcs(world, canon, series, story)
    if not arcs_path.exists():
        return ""
    try:
        data = yaml.safe_load(arcs_path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return ""

    name_lower = character_name.lower()
    arcs = data.get("arcs", data.get("character_arcs", []))
    if not isinstance(arcs, list):
        return ""

    for arc in arcs:
        if not isinstance(arc, dict):
            continue
        arc_name = str(arc.get("character", arc.get("name", ""))).lower()
        if arc_name == name_lower or name_lower in arc_name:
            text = yaml.dump(arc, allow_unicode=True, sort_keys=False)
            return text[:_ARC_MAX_CHARS]

    # Character not found in arcs — return whole file truncated
    raw = arcs_path.read_text(encoding="utf-8", errors="replace")
    return raw[:_ARC_MAX_CHARS]


def _extract_story_context(
    paths: "Paths", world: str, canon: str, series: str, story: str
) -> str:
    """Pull title, genre, and theme from Creative_Brief or Outline."""
    parts: list[str] = []

    outline_path = paths.outline(world, canon, series, story)
    if outline_path.exists():
        try:
            data = yaml.safe_load(outline_path.read_text(encoding="utf-8")) or {}
            if data.get("title"):
                parts.append(f"Title: {data['title']}")
            if data.get("genre"):
                parts.append(f"Genre: {data['genre']}")
            if data.get("theme"):
                parts.append(f"Theme: {data['theme']}")
        except (yaml.YAMLError, OSError):
            pass

    brief_path = paths.creative_brief(world, canon, series, story)
    if brief_path.exists():
        try:
            brief_text = brief_path.read_text(encoding="utf-8", errors="replace")
            parts.append(brief_text[:_CONTEXT_MAX_CHARS])
        except OSError:
            pass

    return "\n".join(parts)
