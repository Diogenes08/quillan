"""Tests for quillan.structure.cover."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_outline(paths, world, canon, series, story, title="The Dark Tower", genre="fantasy"):
    outline_data = {
        "title": title,
        "genre": genre,
        "theme": "fate and free will",
        "chapters": [{"chapter": 1, "title": "Ch1", "beats": [{"beat_id": "C1-S1-B1"}]}],
    }
    p = paths.outline(world, canon, series, story)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.dump(outline_data), encoding="utf-8")
    return outline_data


def _make_brief(paths, world, canon, series, story):
    brief_data = {
        "tone_palette": ["gritty", "melancholic"],
        "motifs": ["ravens", "broken clocks", "winter roads"],
        "arc_intent": "A lone wanderer seeks an impossible goal.",
    }
    p = paths.creative_brief(world, canon, series, story)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.dump(brief_data), encoding="utf-8")
    return brief_data


def _make_fake_llm(has_keys: bool = True) -> MagicMock:
    llm = MagicMock()
    llm.settings.has_api_keys = has_keys
    # Return a tiny valid PNG (8-byte signature + minimal IHDR)
    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    llm.generate_image = AsyncMock(return_value=fake_png)
    return llm


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_cover_image_path(paths, world, canon, series, story):
    """cover_image() returns the expected path under export/."""
    p = paths.cover_image(world, canon, series, story)
    assert p.name == f"{story}_cover.png"
    assert "export" in str(p)


async def test_generate_cover_builds_prompt(paths, world, canon, series, story):
    """Prompt contains title, motifs, and genre from outline + brief."""
    from quillan.structure.cover import _build_cover_prompt

    outline_data = _make_outline(paths, world, canon, series, story).__class__  # not used
    outline_data = {
        "title": "Midnight Echo",
        "genre": "thriller",
        "theme": "paranoia",
    }
    brief_data = {
        "tone_palette": ["tense", "shadowy"],
        "motifs": ["mirrors", "static noise"],
    }

    prompt = _build_cover_prompt(outline_data, brief_data)

    assert "Midnight Echo" in prompt
    assert "thriller" in prompt
    assert "mirrors" in prompt
    assert "static noise" in prompt
    assert "tense" in prompt
    assert "No text" in prompt


async def test_generate_cover_missing_brief_graceful(paths, world, canon, series, story):
    """generate_cover() works fine when Creative_Brief.yaml is absent."""
    from quillan.structure.cover import generate_cover

    _make_outline(paths, world, canon, series, story)
    # No brief file created
    llm = _make_fake_llm(has_keys=True)

    result = await generate_cover(paths, world, canon, series, story, llm)

    assert result.exists()
    assert result.name.endswith("_cover.png")
    llm.generate_image.assert_called_once()


async def test_generate_cover_user_image_copies_file(paths, world, canon, series, story, tmp_path):
    """When image_path is supplied, file is copied and no LLM call is made."""
    from quillan.structure.cover import generate_cover

    _make_outline(paths, world, canon, series, story)
    src = tmp_path / "myimage.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

    llm = _make_fake_llm(has_keys=True)
    result = await generate_cover(paths, world, canon, series, story, llm, image_path=src)

    assert result.exists()
    assert result.read_bytes() == src.read_bytes()
    llm.generate_image.assert_not_called()


async def test_generate_cover_skips_existing_no_force(paths, world, canon, series, story):
    """If cover exists and force=False, returns immediately without API call."""
    from quillan.structure.cover import generate_cover

    _make_outline(paths, world, canon, series, story)
    llm = _make_fake_llm(has_keys=True)

    # Pre-populate cover
    cover_path = paths.cover_image(world, canon, series, story)
    cover_path.parent.mkdir(parents=True, exist_ok=True)
    cover_path.write_bytes(b"existing content")

    result = await generate_cover(paths, world, canon, series, story, llm, force=False)

    assert result == cover_path
    llm.generate_image.assert_not_called()


async def test_generate_cover_regen_overwrites(paths, world, canon, series, story):
    """force=True regenerates even if cover already exists."""
    from quillan.structure.cover import generate_cover

    _make_outline(paths, world, canon, series, story)
    llm = _make_fake_llm(has_keys=True)

    # Pre-populate cover with old content
    cover_path = paths.cover_image(world, canon, series, story)
    cover_path.parent.mkdir(parents=True, exist_ok=True)
    cover_path.write_bytes(b"old content")

    await generate_cover(paths, world, canon, series, story, llm, force=True)

    llm.generate_image.assert_called_once()
    assert cover_path.read_bytes() != b"old content"


async def test_generate_cover_no_api_keys_no_image_raises(paths, world, canon, series, story):
    """Raises LLMError when no API keys and no image_path supplied."""
    from quillan.structure.cover import generate_cover
    from quillan.llm import LLMError

    _make_outline(paths, world, canon, series, story)
    llm = _make_fake_llm(has_keys=False)

    with pytest.raises(LLMError, match="API keys"):
        await generate_cover(paths, world, canon, series, story, llm)


async def test_generate_cover_invalid_image_raises(paths, world, canon, series, story, tmp_path):
    """Raises FileNotFoundError when supplied image_path does not exist."""
    from quillan.structure.cover import generate_cover

    _make_outline(paths, world, canon, series, story)
    llm = _make_fake_llm(has_keys=True)
    missing = tmp_path / "does_not_exist.png"

    with pytest.raises(FileNotFoundError, match="not found"):
        await generate_cover(paths, world, canon, series, story, llm, image_path=missing)
