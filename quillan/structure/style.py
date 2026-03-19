"""Style fingerprint extraction for Quillan.

Reads samples.md, calls the LLM to extract a structured style profile,
and writes style_profile.yaml to the story's style_reference directory.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import yaml

from quillan.templates import get_prompt

if TYPE_CHECKING:
    from quillan.llm import LLMClient
    from quillan.paths import Paths
    from quillan.config import Settings

logger = logging.getLogger("quillan.structure.style")

# Keys the LLM must include in its response
_REQUIRED_KEYS = ["pov", "tense", "sentence_rhythm", "voice", "distinctive_features", "avoid"]

# Cap samples fed to the analysis call so we stay within prompt budget
_ANALYSIS_MAX_CHARS = 6000


async def extract_style_profile(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    llm: "LLMClient",
    settings: "Settings",
) -> "Paths | None":
    """Analyse samples.md and write style_profile.yaml.

    Returns the profile path on success, or None if samples.md is missing
    or the LLM call fails.
    """
    from quillan.llm import LLMError
    from quillan.io import atomic_write

    samples_path = paths.style_samples(world, canon, series, story)
    if not samples_path.exists():
        logger.debug("No samples.md found; skipping style profile extraction.")
        return None

    try:
        samples_text = samples_path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError as exc:
        logger.warning("Could not read samples.md: %s", exc)
        return None

    if not samples_text:
        logger.debug("samples.md is empty; skipping style profile extraction.")
        return None

    if len(samples_text) > _ANALYSIS_MAX_CHARS:
        samples_text = samples_text[:_ANALYSIS_MAX_CHARS]
        logger.debug("Samples truncated to %d chars for style analysis.", _ANALYSIS_MAX_CHARS)

    _story_dir = paths.story(world, canon, series, story)
    _world_dir = paths.world(world)
    system = get_prompt("style_analysis_system", story_dir=_story_dir, world_dir=_world_dir)
    user = get_prompt("style_analysis_user", story_dir=_story_dir, world_dir=_world_dir).format(
        samples=samples_text
    )

    try:
        profile_data = await llm.call_json("planning", system, user, required_keys=_REQUIRED_KEYS)
    except LLMError as exc:
        logger.warning("Style profile extraction failed: %s", exc)
        return None

    profile_path = paths.style_profile(world, canon, series, story)
    paths.ensure(profile_path)
    atomic_write(profile_path, yaml.dump(profile_data, allow_unicode=True, sort_keys=False))
    logger.info("Style profile written to %s", profile_path)
    return profile_path
