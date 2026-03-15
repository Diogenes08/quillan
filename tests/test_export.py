"""Tests for quillan.export — P0 audit fix (previously no dedicated tests)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml

from quillan.export import export_story


# ── Helpers ────────────────────────────────────────────────────────────────────

def _write_outline(paths, world, canon, series, story, chapters=None):
    """Write a minimal valid Outline.yaml."""
    if chapters is None:
        chapters = [
            {
                "chapter": 1,
                "title": "Chapter One",
                "beats": [
                    {"beat_id": "C1-S1-B1", "title": "Opening"},
                    {"beat_id": "C1-S1-B2", "title": "Rising action"},
                ],
            }
        ]
    data = {
        "title": "Test Story",
        "genre": "fantasy",
        "theme": "courage",
        "chapters": chapters,
    }
    outline_path = paths.outline(world, canon, series, story)
    outline_path.parent.mkdir(parents=True, exist_ok=True)
    outline_path.write_text(yaml.dump(data), encoding="utf-8")
    return data


def _write_beat_draft(paths, world, canon, series, story, beat_id: str, text: str) -> None:
    draft_path = paths.beat_draft(world, canon, series, story, beat_id)
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(text, encoding="utf-8")


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_export_markdown_basic(paths, world, canon, series, story):
    """Markdown export assembles outline + beat drafts into a structured doc."""
    _write_outline(paths, world, canon, series, story)
    _write_beat_draft(paths, world, canon, series, story, "C1-S1-B1", "The hero woke up.")
    _write_beat_draft(paths, world, canon, series, story, "C1-S1-B2", "Trouble found him.")

    out = export_story(paths, world, canon, series, story, fmt="markdown")

    assert out.suffix == ".md"
    text = out.read_text(encoding="utf-8")
    assert "Test Story" in text
    assert "The hero woke up." in text
    assert "Trouble found him." in text
    assert "Chapter One" in text


def test_export_missing_outline_raises(paths, world, canon, series, story):
    """FileNotFoundError when Outline.yaml is absent."""
    with pytest.raises(FileNotFoundError, match="Outline.yaml not found"):
        export_story(paths, world, canon, series, story, fmt="markdown")


def test_export_invalid_outline_no_chapters(paths, world, canon, series, story):
    """ValueError when Outline.yaml is missing the 'chapters' key."""
    outline_path = paths.outline(world, canon, series, story)
    outline_path.parent.mkdir(parents=True, exist_ok=True)
    outline_path.write_text(yaml.dump({"title": "No chapters here"}), encoding="utf-8")

    with pytest.raises(ValueError, match="missing 'chapters'"):
        export_story(paths, world, canon, series, story, fmt="markdown")


def test_export_missing_beats_empty_chapter(paths, world, canon, series, story):
    """Chapters present but no drafts → chapter heading exists, no prose."""
    _write_outline(paths, world, canon, series, story)
    # No beat drafts written

    out = export_story(paths, world, canon, series, story, fmt="markdown")
    text = out.read_text(encoding="utf-8")

    assert "Chapter One" in text
    # No prose content after heading
    assert "The hero" not in text


def test_export_epub_with_cover_path(paths, world, canon, series, story, tmp_path):
    """epub format passes --epub-cover-image= when cover_path is supplied."""
    _write_outline(paths, world, canon, series, story)
    _write_beat_draft(paths, world, canon, series, story, "C1-S1-B1", "Prose here.")

    cover_file = tmp_path / "cover.png"
    cover_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)  # minimal PNG header

    captured_args: list = []

    def fake_pandoc(args, *, check, capture_output, timeout):
        captured_args.extend(args)

    with patch("quillan.export._pandoc_available", return_value=True), \
         patch("subprocess.run", side_effect=fake_pandoc):
        export_story(paths, world, canon, series, story, fmt="epub", cover_path=cover_file)

    cover_args = [a for a in captured_args if "--epub-cover-image" in str(a)]
    assert cover_args, "Expected --epub-cover-image= in pandoc args"
    assert str(cover_file) in cover_args[0]


def test_export_epub_without_cover_no_flag(paths, world, canon, series, story):
    """epub format omits --epub-cover-image= when cover_path is None."""
    _write_outline(paths, world, canon, series, story)
    _write_beat_draft(paths, world, canon, series, story, "C1-S1-B1", "Prose here.")

    captured_args: list = []

    def fake_pandoc(args, *, check, capture_output, timeout):
        captured_args.extend(args)

    with patch("quillan.export._pandoc_available", return_value=True), \
         patch("subprocess.run", side_effect=fake_pandoc):
        export_story(paths, world, canon, series, story, fmt="epub", cover_path=None)

    cover_args = [a for a in captured_args if "--epub-cover-image" in str(a)]
    assert not cover_args, "Expected NO --epub-cover-image= when cover_path is None"


def test_export_print_pdf_uses_template(paths, world, canon, series, story):
    """print-pdf format passes --template= to pandoc."""
    _write_outline(paths, world, canon, series, story)
    _write_beat_draft(paths, world, canon, series, story, "C1-S1-B1", "Prose here.")

    captured_args: list = []

    def fake_pandoc(args, *, check, capture_output, timeout):
        captured_args.extend(args)

    with patch("quillan.export._pandoc_available", return_value=True), \
         patch("subprocess.run", side_effect=fake_pandoc):
        out = export_story(paths, world, canon, series, story, fmt="print-pdf")

    assert out.name.endswith("_print.pdf")
    template_args = [a for a in captured_args if "--template=" in str(a)]
    assert template_args, "Expected --template= in pandoc args for print-pdf"
    assert "print_interior.tex" in template_args[0]


def test_export_pandoc_unavailable_degrades(paths, world, canon, series, story):
    """When pandoc is unavailable, non-markdown formats return the .md file."""
    _write_outline(paths, world, canon, series, story)
    _write_beat_draft(paths, world, canon, series, story, "C1-S1-B1", "Prose here.")

    with patch("quillan.export._pandoc_available", return_value=False):
        out = export_story(paths, world, canon, series, story, fmt="epub")

    assert out.suffix == ".md", "Should degrade to markdown when pandoc unavailable"
