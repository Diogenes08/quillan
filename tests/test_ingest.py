"""Tests for quillan.ingest — parse, cluster, and full ingest (no API calls)."""

from __future__ import annotations

import asyncio
import json

import pytest
import yaml

from quillan.ingest import (
    parse_markdown,
    cluster_into_beats,
    _build_ingest_outline,
    _build_dep_map,
    _build_style_samples,
    ingest_manuscript,
    _STYLE_SAMPLE_CHAPTERS,
    _STYLE_SAMPLE_MAX_CHARS,
)
from quillan.validate import sanitize_story_name as _sanitize_story_name


# ── _sanitize_story_name ──────────────────────────────────────────────────────

def test_sanitize_simple():
    assert _sanitize_story_name("My Novel") == "my_novel"

def test_sanitize_special_chars():
    # Hyphens are allowed; apostrophe and ! are removed
    assert _sanitize_story_name("The Time-Traveller's Wife!") == "the_time-travellers_wife"

def test_sanitize_already_clean():
    assert _sanitize_story_name("my_story") == "my_story"

def test_sanitize_empty_falls_back():
    assert _sanitize_story_name("!!!", fallback="imported_story") == "imported_story"

def test_sanitize_strips_leading_trailing_underscores():
    assert _sanitize_story_name("  hello world  ") == "hello_world"


# ── parse_markdown ────────────────────────────────────────────────────────────

def test_parse_markdown_empty():
    assert parse_markdown("") == []

def test_parse_markdown_whitespace_only():
    assert parse_markdown("   \n\n   ") == []

def test_parse_markdown_no_headings_single_chapter():
    result = parse_markdown("Just some text.\nMore text.")
    assert len(result) == 1
    assert result[0]["title"] == "Chapter 1"
    assert "Just some text" in result[0]["text"]

def test_parse_markdown_h1_splits():
    text = "# Chapter One\nFirst chapter text.\n# Chapter Two\nSecond chapter text."
    result = parse_markdown(text)
    assert len(result) == 2
    assert result[0]["title"] == "Chapter One"
    assert result[1]["title"] == "Chapter Two"

def test_parse_markdown_h2_splits():
    text = "## Intro\nIntro text.\n## Rising Action\nAction text."
    result = parse_markdown(text)
    assert len(result) == 2
    assert result[0]["title"] == "Intro"

def test_parse_markdown_preface_before_first_heading():
    text = "This is a preface.\n\n# Chapter One\nChapter text."
    result = parse_markdown(text)
    assert len(result) == 2
    assert result[0]["title"] == "Preface"
    assert "preface" in result[0]["text"].lower()

def test_parse_markdown_skips_empty_chapters():
    text = "# Chapter One\n\n# Chapter Two\nActual content here."
    result = parse_markdown(text)
    # Chapter One has no body — should be skipped
    assert len(result) == 1
    assert result[0]["title"] == "Chapter Two"

def test_parse_markdown_mixed_h1_h2():
    text = "# Part I\nPart text.\n## Section A\nSection text."
    result = parse_markdown(text)
    assert len(result) == 2

def test_parse_markdown_heading_text_preserved():
    text = "# The Long Road Home\nSome content."
    result = parse_markdown(text)
    assert result[0]["title"] == "The Long Road Home"
    assert result[0]["text"] == "Some content."


# ── cluster_into_beats ────────────────────────────────────────────────────────

def test_cluster_empty():
    assert cluster_into_beats("") == []

def test_cluster_short_text_single_beat():
    text = "This is a short paragraph."
    result = cluster_into_beats(text, target_words=1500)
    assert result == [text]

def test_cluster_respects_target():
    # 300 words per paragraph, target=500 → should produce ~1 beat per pair
    para = " ".join(["word"] * 300)
    text = "\n\n".join([para] * 6)  # 1800 words total
    result = cluster_into_beats(text, target_words=500)
    assert len(result) > 1
    for beat in result:
        # Each beat should be reasonably close to target (never wildly over)
        words = len(beat.split())
        assert words <= 700  # at most one paragraph over target

def test_cluster_never_splits_paragraph():
    # Single 2000-word paragraph — must not be split
    para = " ".join(["word"] * 2000)
    result = cluster_into_beats(para, target_words=500)
    assert len(result) == 1  # can't split within paragraph

def test_cluster_content_preserved():
    para_a = "Alpha paragraph. " * 50
    para_b = "Beta paragraph. " * 50
    text = para_a.strip() + "\n\n" + para_b.strip()
    result = cluster_into_beats(text, target_words=100)
    combined = " ".join(result)
    assert "Alpha paragraph" in combined
    assert "Beta paragraph" in combined

def test_cluster_multiple_small_paragraphs_merge():
    # Each paragraph is 10 words; target is 50 — should merge ~5 per beat
    para = " ".join(["x"] * 10)
    text = "\n\n".join([para] * 20)
    result = cluster_into_beats(text, target_words=50)
    assert 3 <= len(result) <= 7  # ~4 beats


# ── _build_ingest_outline ─────────────────────────────────────────────────────

def test_build_outline_structure():
    chapters = [
        {"title": "Chapter One", "beats": ["Beat text A", "Beat text B"]},
        {"title": "Chapter Two", "beats": ["Beat text C"]},
    ]
    outline = _build_ingest_outline(chapters, "My Story")
    assert outline["title"] == "My Story"
    assert len(outline["chapters"]) == 2
    assert outline["chapters"][0]["chapter"] == 1
    assert outline["chapters"][1]["chapter"] == 2

def test_build_outline_beat_ids():
    chapters = [{"title": "Ch", "beats": ["a", "b", "c"]}]
    outline = _build_ingest_outline(chapters, "T")
    beat_ids = [b["beat_id"] for b in outline["chapters"][0]["beats"]]
    assert beat_ids == ["C1-S1-B1", "C1-S1-B2", "C1-S1-B3"]

def test_build_outline_source_flag():
    outline = _build_ingest_outline([{"title": "C", "beats": ["x"]}], "T")
    assert outline.get("source") == "imported"


# ── _build_dep_map ────────────────────────────────────────────────────────────

def test_dep_map_linear():
    chapters = [
        {"title": "C1", "beats": ["a", "b"]},
        {"title": "C2", "beats": ["c"]},
    ]
    dep_map = _build_dep_map(chapters)["dependencies"]
    assert dep_map["C1-S1-B1"] == []
    assert dep_map["C1-S1-B2"] == ["C1-S1-B1"]
    assert dep_map["C2-S1-B1"] == ["C1-S1-B2"]

def test_dep_map_single_beat_no_dep():
    chapters = [{"title": "Only", "beats": ["text"]}]
    dep_map = _build_dep_map(chapters)["dependencies"]
    assert dep_map["C1-S1-B1"] == []


# ── ingest_manuscript (integration, no API calls) ────────────────────────────

_SAMPLE_MD = """\
# Chapter One

The beginning of the story. Here is a long paragraph with lots of content.
More content in this paragraph to pad out the word count.
Even more content here to ensure we have enough text to work with.

Another paragraph in chapter one, continuing the narrative forward.
This paragraph also adds some words to make the chapter longer.

# Chapter Two

The middle of the story. Events unfold rapidly in this chapter.
We have more text here to ensure proper clustering works correctly.

A second paragraph in chapter two, adding more narrative content.
This brings the total word count of chapter two to a reasonable level.
"""


def test_ingest_creates_beat_drafts(tmp_path, paths, world, canon, series):
    src = tmp_path / "novel.md"
    src.write_text(_SAMPLE_MD, encoding="utf-8")
    story = "my_novel"

    asyncio.run(
        ingest_manuscript(src, paths, world, canon, series, story, target_words_per_beat=30)
    )

    # Should have created at least 2 beats
    beats_dir = paths.story_beats(world, canon, series, story)
    beat_dirs = list(beats_dir.iterdir())
    assert len(beat_dirs) >= 2


def test_ingest_writes_outline_yaml(tmp_path, paths, world, canon, series):
    src = tmp_path / "novel.md"
    src.write_text(_SAMPLE_MD, encoding="utf-8")
    story = "my_novel"

    asyncio.run(
        ingest_manuscript(src, paths, world, canon, series, story)
    )

    outline_path = paths.outline(world, canon, series, story)
    assert outline_path.exists()
    data = yaml.safe_load(outline_path.read_text(encoding="utf-8"))
    assert "chapters" in data
    assert len(data["chapters"]) == 2
    assert data["chapters"][0]["title"] == "Chapter One"


def test_ingest_writes_dependency_map(tmp_path, paths, world, canon, series):
    src = tmp_path / "novel.md"
    src.write_text(_SAMPLE_MD, encoding="utf-8")
    story = "my_novel"

    asyncio.run(
        ingest_manuscript(src, paths, world, canon, series, story)
    )

    dep_path = paths.dependency_map(world, canon, series, story)
    assert dep_path.exists()
    data = json.loads(dep_path.read_text(encoding="utf-8"))
    assert "dependencies" in data


def test_ingest_writes_beat_specs(tmp_path, paths, world, canon, series):
    src = tmp_path / "novel.md"
    src.write_text(_SAMPLE_MD, encoding="utf-8")
    story = "my_novel"

    asyncio.run(
        ingest_manuscript(src, paths, world, canon, series, story)
    )

    # Check that at least one beat spec exists
    beats_dir = paths.story_beats(world, canon, series, story)
    specs = list(beats_dir.rglob("beat_spec.yaml"))
    assert len(specs) >= 1


def test_ingest_copies_source_to_input(tmp_path, paths, world, canon, series):
    src = tmp_path / "original.md"
    src.write_text(_SAMPLE_MD, encoding="utf-8")
    story = "my_novel"

    asyncio.run(
        ingest_manuscript(src, paths, world, canon, series, story)
    )

    input_dir = paths.story_input(world, canon, series, story)
    assert (input_dir / "original.md").exists()


def test_ingest_unsupported_format_raises(tmp_path, paths, world, canon, series):
    src = tmp_path / "book.pdf"
    src.write_bytes(b"%PDF fake")

    with pytest.raises(ValueError, match="Unsupported file type"):
        asyncio.run(
            ingest_manuscript(src, paths, world, canon, series, "bad_story")
        )


def test_ingest_empty_file_raises(tmp_path, paths, world, canon, series):
    src = tmp_path / "empty.md"
    src.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="No readable content"):
        asyncio.run(
            ingest_manuscript(src, paths, world, canon, series, "empty_story")
        )


def test_ingest_on_progress_called(tmp_path, paths, world, canon, series):
    src = tmp_path / "novel.md"
    src.write_text(_SAMPLE_MD, encoding="utf-8")
    story = "my_novel"

    messages: list[str] = []
    asyncio.run(
        ingest_manuscript(
            src, paths, world, canon, series, story,
            on_progress=messages.append,
        )
    )
    assert any("Parsing" in m for m in messages)
    assert any("Ingest complete" in m for m in messages)


def test_ingest_returns_story_name(tmp_path, paths, world, canon, series):
    src = tmp_path / "novel.md"
    src.write_text(_SAMPLE_MD, encoding="utf-8")

    result = asyncio.run(
        ingest_manuscript(src, paths, world, canon, series, "my_story")
    )
    assert result == "my_story"


def test_ingest_plain_text_no_headings(tmp_path, paths, world, canon, series):
    """A plain .txt file with no headings should work as a single chapter."""
    content = "This is prose.\n\nMore prose here.\n\n" * 10
    src = tmp_path / "draft.txt"
    src.write_text(content, encoding="utf-8")

    asyncio.run(
        ingest_manuscript(src, paths, world, canon, series, "plain_story")
    )

    outline_path = paths.outline(world, canon, series, "plain_story")
    data = yaml.safe_load(outline_path.read_text())
    assert len(data["chapters"]) == 1
    assert data["chapters"][0]["title"] == "Chapter 1"


# ── F2 Phase 3: _build_style_samples ─────────────────────────────────────────

def _make_chapters(n: int, words_per_chapter: int = 50) -> list[dict]:
    """Helper: fabricate n chapters each containing a single beat of prose."""
    filler = ("word " * words_per_chapter).strip()
    return [
        {"title": f"Chapter {i}", "beats": [filler]}
        for i in range(1, n + 1)
    ]


def test_build_style_samples_empty_chapters():
    assert _build_style_samples([]) == ""


def test_build_style_samples_includes_first_chapters():
    chapters = _make_chapters(5)
    result = _build_style_samples(chapters)
    assert "Chapter 1" in result
    assert "Chapter 2" in result
    assert "Chapter 3" in result
    assert f"Chapter {_STYLE_SAMPLE_CHAPTERS + 1}" not in result


def test_build_style_samples_caps_at_max_chars():
    # Create chapters with huge text so we exceed _STYLE_SAMPLE_MAX_CHARS
    big_text = "x " * 5000
    chapters = [{"title": f"Ch{i}", "beats": [big_text]} for i in range(1, 4)]
    result = _build_style_samples(chapters)
    assert len(result) <= _STYLE_SAMPLE_MAX_CHARS + 20  # small slack for truncation marker
    assert "...(truncated)" in result


def test_build_style_samples_separator_between_chapters():
    chapters = _make_chapters(2)
    result = _build_style_samples(chapters)
    assert "---" in result


def test_build_style_samples_single_chapter():
    chapters = _make_chapters(1)
    result = _build_style_samples(chapters)
    assert "Chapter 1" in result
    assert "---" not in result  # no separator when only one chapter


# ── F2 Phase 3: ingest writes samples.md ─────────────────────────────────────

def test_ingest_writes_samples_md(tmp_path, paths, world, canon, series):
    """ingest_manuscript writes samples.md from the first chapters."""
    src = tmp_path / "novel.md"
    src.write_text(_SAMPLE_MD, encoding="utf-8")

    asyncio.run(ingest_manuscript(src, paths, world, canon, series, "my_novel"))

    samples_path = paths.style_samples(world, canon, series, "my_novel")
    assert samples_path.exists()
    content = samples_path.read_text()
    assert "Chapter One" in content


def test_ingest_samples_contains_prose(tmp_path, paths, world, canon, series):
    """samples.md contains actual prose from the manuscript."""
    src = tmp_path / "novel.md"
    src.write_text(_SAMPLE_MD, encoding="utf-8")

    asyncio.run(ingest_manuscript(src, paths, world, canon, series, "my_novel"))

    content = paths.style_samples(world, canon, series, "my_novel").read_text()
    # Both chapters are within the first 3, so both should be included
    assert "beginning of the story" in content
    assert "middle of the story" in content


def test_ingest_no_profile_without_llm(tmp_path, paths, world, canon, series):
    """Without an LLM, ingest does not write style_profile.yaml."""
    src = tmp_path / "novel.md"
    src.write_text(_SAMPLE_MD, encoding="utf-8")

    asyncio.run(ingest_manuscript(src, paths, world, canon, series, "my_novel"))

    assert not paths.style_profile(world, canon, series, "my_novel").exists()


def test_ingest_writes_profile_with_llm(tmp_path, paths, world, canon, series, settings):
    """With a stub LLM, ingest writes style_profile.yaml."""
    import yaml as _yaml

    class _StubLLM:
        async def call_json(self, *args, **kwargs):
            return {
                "pov": "tight third-person limited",
                "tense": "past",
                "sentence_rhythm": "varied",
                "voice": "sardonic",
                "distinctive_features": ["weather imagery"],
                "avoid": ["adverbs"],
            }

    src = tmp_path / "novel.md"
    src.write_text(_SAMPLE_MD, encoding="utf-8")

    llm = _StubLLM()
    asyncio.run(
        ingest_manuscript(src, paths, world, canon, series, "my_novel", llm=llm, settings=settings)
    )

    profile_path = paths.style_profile(world, canon, series, "my_novel")
    assert profile_path.exists()
    data = _yaml.safe_load(profile_path.read_text())
    assert data["pov"] == "tight third-person limited"


def test_ingest_progress_mentions_style(tmp_path, paths, world, canon, series):
    """on_progress receives a message about style samples."""
    src = tmp_path / "novel.md"
    src.write_text(_SAMPLE_MD, encoding="utf-8")

    messages: list[str] = []
    asyncio.run(
        ingest_manuscript(
            src, paths, world, canon, series, "my_novel",
            on_progress=messages.append,
        )
    )

    assert any("Style samples" in m or "style" in m.lower() for m in messages)
