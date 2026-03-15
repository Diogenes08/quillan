"""Tests for quillan.structure.creative_brief."""

from __future__ import annotations

import pytest
import yaml
from pathlib import Path


class _FakeLLM:
    """Minimal LLM stub — forces offline/stub code paths."""
    class settings:
        has_api_keys = False


def _make_dirs(paths, world, canon, series, story):
    """Create the story directory tree required by all brief functions."""
    for d in [
        paths.story_input(world, canon, series, story),
        paths.story_planning(world, canon, series, story),
        paths.story_structure(world, canon, series, story),
    ]:
        d.mkdir(parents=True, exist_ok=True)


# ── classify_specificity ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_classify_short_idea_needs_interview():
    """A short vague idea (<40 words) should need an interview."""
    from quillan.structure.creative_brief import classify_specificity
    result = await classify_specificity("A story about loss", _FakeLLM())
    assert result["needs_interview"] is True
    assert result["specificity_score"] < 0.5


@pytest.mark.asyncio
async def test_classify_long_idea_skips_interview():
    """A detailed 80+ word idea should skip the interview."""
    from quillan.structure.creative_brief import classify_specificity
    long_idea = (
        "A taciturn lighthouse keeper named Maren, haunted by a wreck she believes she caused, "
        "discovers that the light's encrypted signal has been directing smugglers for a decade. "
        "The story is melancholic and precise, told in close third person. "
        "Central theme: guilt as self-punishment vs. guilt as fuel for action. "
        "Maren's arc: from paralysis to decisive moral choice, at personal cost."
    )
    result = await classify_specificity(long_idea, _FakeLLM())
    assert result["needs_interview"] is False
    assert result["specificity_score"] >= 0.5


@pytest.mark.asyncio
async def test_classify_returns_required_keys():
    """classify_specificity always returns the required schema keys."""
    from quillan.structure.creative_brief import classify_specificity
    result = await classify_specificity("A detective story.", _FakeLLM())
    assert "specificity_score" in result
    assert "needs_interview" in result
    assert "detected_signals" in result
    assert isinstance(result["specificity_score"], float)
    assert isinstance(result["needs_interview"], bool)


# ── generate_creative_brief_interview ────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_interview_creates_file(paths, world, canon, series, story):
    """generate_creative_brief_interview writes Creative_Brief_Interview.md."""
    from quillan.structure.creative_brief import generate_creative_brief_interview
    _make_dirs(paths, world, canon, series, story)
    out = await generate_creative_brief_interview(
        paths, world, canon, series, story, "A story about loss", _FakeLLM()
    )
    assert out.exists()
    assert out.name == "Creative_Brief_Interview.md"


@pytest.mark.asyncio
async def test_generate_interview_contains_questions(paths, world, canon, series, story):
    """The generated interview contains numbered questions and Answer fields."""
    from quillan.structure.creative_brief import generate_creative_brief_interview
    _make_dirs(paths, world, canon, series, story)
    out = await generate_creative_brief_interview(
        paths, world, canon, series, story, "A detective uncovers a conspiracy", _FakeLLM()
    )
    text = out.read_text()
    assert "**Answer:**" in text
    assert "1." in text


@pytest.mark.asyncio
async def test_generate_interview_returns_path_under_planning(paths, world, canon, series, story):
    """The interview file is placed in story_planning/."""
    from quillan.structure.creative_brief import generate_creative_brief_interview
    _make_dirs(paths, world, canon, series, story)
    out = await generate_creative_brief_interview(
        paths, world, canon, series, story, "Short idea", _FakeLLM()
    )
    assert out.parent == paths.story_planning(world, canon, series, story)


# ── generate_creative_brief ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_brief_creates_valid_yaml(paths, world, canon, series, story):
    """generate_creative_brief writes valid YAML with required keys."""
    from quillan.structure.creative_brief import generate_creative_brief
    _make_dirs(paths, world, canon, series, story)
    await generate_creative_brief(
        paths, world, canon, series, story, "A detective story", _FakeLLM()
    )
    brief_path = paths.creative_brief(world, canon, series, story)
    assert brief_path.exists()
    data = yaml.safe_load(brief_path.read_text())
    assert "voice" in data
    assert "themes" in data
    assert "arc_intent" in data


@pytest.mark.asyncio
async def test_generate_brief_voice_has_subkeys(paths, world, canon, series, story):
    """The voice section has prose_style, pov, and avoid keys."""
    from quillan.structure.creative_brief import generate_creative_brief
    _make_dirs(paths, world, canon, series, story)
    await generate_creative_brief(
        paths, world, canon, series, story, "A ghost story", _FakeLLM()
    )
    data = yaml.safe_load(paths.creative_brief(world, canon, series, story).read_text())
    voice = data["voice"]
    assert "prose_style" in voice
    assert "pov" in voice
    assert "avoid" in voice


@pytest.mark.asyncio
async def test_generate_brief_arc_intent_contains_idea_snippet(paths, world, canon, series, story):
    """arc_intent includes a snippet of the idea text."""
    from quillan.structure.creative_brief import generate_creative_brief
    _make_dirs(paths, world, canon, series, story)
    idea = "A lighthouse keeper discovers a hidden signal"
    await generate_creative_brief(paths, world, canon, series, story, idea, _FakeLLM())
    data = yaml.safe_load(paths.creative_brief(world, canon, series, story).read_text())
    assert "lighthouse" in data["arc_intent"].lower()


@pytest.mark.asyncio
async def test_generate_brief_loads_interview_answers(paths, world, canon, series, story):
    """If Creative_Brief_Interview.md exists, brief generation reads it."""
    from quillan.structure.creative_brief import generate_creative_brief
    _make_dirs(paths, world, canon, series, story)
    # Pre-write an interview file
    interview_path = paths.creative_brief_interview(world, canon, series, story)
    interview_path.write_text("# Interview\n\n1. Protagonist?\n\n**Answer:** Alice\n")
    # Brief is generated without error even with interview present
    await generate_creative_brief(
        paths, world, canon, series, story, "A story", _FakeLLM()
    )
    assert paths.creative_brief(world, canon, series, story).exists()


# ── NeedsInterviewError ───────────────────────────────────────────────────────

def test_needs_interview_error_attributes():
    """NeedsInterviewError carries story name and interview path."""
    from quillan.structure.creative_brief import NeedsInterviewError
    p = Path("/tmp/interview.md")
    exc = NeedsInterviewError("mystory", p)
    assert exc.story == "mystory"
    assert exc.interview_path == p
    assert "mystory" in str(exc) or "interview.md" in str(exc)


def test_needs_interview_error_is_exception():
    """NeedsInterviewError is a proper Exception subclass."""
    from quillan.structure.creative_brief import NeedsInterviewError
    exc = NeedsInterviewError("s", Path("/tmp/x"))
    assert isinstance(exc, Exception)
