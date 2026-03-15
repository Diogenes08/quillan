"""Cover image generation for Quillan2 stories."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

logger = logging.getLogger("quillan.structure.cover")

if TYPE_CHECKING:
    from quillan.llm import LLMClient
    from quillan.paths import Paths


def _build_cover_prompt(
    outline_data: dict,
    brief_data: dict | None,
    style: str = "cinematic, photorealistic, dramatic lighting, high contrast",
) -> str:
    """Build a deterministic DALL-E prompt from story metadata."""
    title = outline_data.get("title", "Untitled")
    genre = outline_data.get("genre", "fiction")
    theme = outline_data.get("theme", "")

    tone_parts: list[str] = []
    motifs: list[str] = []

    if brief_data:
        tone_palette = brief_data.get("tone_palette", [])
        if isinstance(tone_palette, list):
            tone_parts = [str(t) for t in tone_palette[:2]]
        motif_list = brief_data.get("motifs", [])
        if isinstance(motif_list, list):
            motifs = [str(m) for m in motif_list]

    parts = [
        f'Book cover illustration for "{title}", a {genre} novel.',
    ]
    if tone_parts:
        parts.append(f"Mood: {', '.join(tone_parts)}.")
    if motifs:
        parts.append(f"Visual motifs: {', '.join(motifs)}.")
    if theme:
        parts.append(f"Theme: {theme}.")
    parts += [
        f"Style: {style}.",
        "No text, words, or lettering of any kind in the image.",
        "Portrait orientation, suitable for a book cover.",
    ]
    return " ".join(parts)


async def generate_cover(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    llm: "LLMClient",
    *,
    image_path: Path | None = None,
    force: bool = False,
) -> Path:
    """Generate or copy a cover image. Returns path to <story>_cover.png.

    If image_path is given, copies it to the export dir (no API call).
    If cover already exists and force=False, returns existing path immediately.
    Raises LLMError if no API keys and no image_path supplied.
    Raises FileNotFoundError if image_path is given but does not exist.
    """
    from quillan.llm import LLMError  # local import to avoid circular

    cover_path = paths.cover_image(world, canon, series, story)

    # If user supplied a file, validate and copy it
    if image_path is not None:
        if not Path(image_path).exists():
            raise FileNotFoundError(f"Supplied image file not found: {image_path}")
        paths.ensure(cover_path)
        shutil.copy2(str(image_path), str(cover_path))
        return cover_path

    # Return immediately if cover already exists and not forced
    if cover_path.exists() and not force:
        return cover_path

    # Read outline
    outline_path = paths.outline(world, canon, series, story)
    if not outline_path.exists():
        raise FileNotFoundError(f"Outline.yaml not found: {outline_path}")
    outline_data = yaml.safe_load(outline_path.read_text(encoding="utf-8")) or {}

    # Read creative brief (optional)
    brief_data: dict | None = None
    brief_path = paths.creative_brief(world, canon, series, story)
    if brief_path.exists():
        try:
            brief_data = yaml.safe_load(brief_path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            logger.warning("Could not load creative brief for cover generation: %s", exc)
            brief_data = None

    # Check API keys before calling
    if not llm.settings.has_api_keys:
        raise LLMError(
            "Image generation requires API keys. "
            "Set OPENAI_API_KEY or use --image to supply a file."
        )

    style = getattr(llm.settings, "cover_style", "cinematic, photorealistic, dramatic lighting, high contrast")
    prompt = _build_cover_prompt(outline_data, brief_data, style=style)
    image_bytes = await llm.generate_image(prompt)

    paths.ensure(cover_path)
    cover_path.write_bytes(image_bytes)
    return cover_path
