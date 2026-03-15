"""Tests for quillan.structure.lulu."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
import yaml

from quillan.structure.lulu import (
    MIN_SPINE_WIDTH,
    SPINE_PER_PAGE_BW,
    estimate_page_count,
    spine_width_inches,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_story_skeleton(paths, world, canon, series, story, num_beats: int = 2) -> Path:
    """Create minimal outline + interior PDF in export dir."""
    outline_data = {
        "title": "Test Book",
        "genre": "fiction",
        "theme": "perseverance",
        "chapters": [
            {
                "chapter": 1,
                "title": "Chapter One",
                "beats": [{"beat_id": f"C1-S1-B{i+1}"} for i in range(num_beats)],
            }
        ],
    }
    outline_path = paths.outline(world, canon, series, story)
    outline_path.parent.mkdir(parents=True, exist_ok=True)
    outline_path.write_text(yaml.dump(outline_data), encoding="utf-8")

    # Interior PDF (stub — just needs to exist)
    export_dir = paths.story_export(world, canon, series, story)
    export_dir.mkdir(parents=True, exist_ok=True)
    interior_pdf = export_dir / f"{story}_print.pdf"
    interior_pdf.write_bytes(b"%PDF-1.4 stub")
    return export_dir


def _write_beat_draft(paths, world, canon, series, story, beat_id: str, words: int) -> None:
    draft_path = paths.beat_draft(world, canon, series, story, beat_id)
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(" ".join(["word"] * words), encoding="utf-8")


# ── Unit tests ─────────────────────────────────────────────────────────────────

def test_spine_width_bw_200_pages():
    """200 BW pages → spine width ≈ 0.45 inches."""
    width = spine_width_inches(200, color=False)
    expected = 200 * SPINE_PER_PAGE_BW  # 0.4504
    assert abs(width - expected) < 0.001
    assert width > MIN_SPINE_WIDTH


def test_spine_width_enforces_minimum():
    """Very few pages → minimum spine width of 0.25 inches is enforced."""
    assert spine_width_inches(10) == MIN_SPINE_WIDTH
    assert spine_width_inches(1) == MIN_SPINE_WIDTH
    assert spine_width_inches(0) == MIN_SPINE_WIDTH


def test_estimate_page_count_basic(paths, world, canon, series, story):
    """500 words across drafts → round(500/250) = 2 pages."""
    beats_dir = paths.story_beats(world, canon, series, story)
    _write_beat_draft(paths, world, canon, series, story, "C1-S1-B1", 300)
    _write_beat_draft(paths, world, canon, series, story, "C1-S1-B2", 200)

    count = estimate_page_count(beats_dir)
    assert count == 2


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed",
)
def test_build_lulu_bundle_creates_zip(paths, world, canon, series, story):
    """build_lulu_bundle() produces a zip with exactly 3 entries."""
    from quillan.structure.lulu import build_lulu_bundle

    _make_story_skeleton(paths, world, canon, series, story)

    bundle_path = build_lulu_bundle(paths, world, canon, series, story)

    assert bundle_path.exists()
    with zipfile.ZipFile(str(bundle_path)) as zf:
        names = zf.namelist()
    assert len(names) == 3
    assert any("interior" in n for n in names)
    assert any("cover" in n for n in names)
    assert any("README" in n or "readme" in n.lower() for n in names)


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed",
)
def test_build_lulu_bundle_readme_has_spine_info(paths, world, canon, series, story):
    """README.txt in the zip mentions spine width."""
    from quillan.structure.lulu import build_lulu_bundle

    _make_story_skeleton(paths, world, canon, series, story)

    bundle_path = build_lulu_bundle(paths, world, canon, series, story)

    with zipfile.ZipFile(str(bundle_path)) as zf:
        readme_name = next(n for n in zf.namelist() if "README" in n or "readme" in n.lower())
        readme_text = zf.read(readme_name).decode("utf-8")

    assert "Spine width" in readme_text
    assert "inches" in readme_text


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed",
)
def test_build_lulu_bundle_no_cover_uses_solid_fill(paths, world, canon, series, story):
    """Bundle builds successfully without a cover image (solid-color front panel)."""
    from quillan.structure.lulu import build_lulu_bundle

    _make_story_skeleton(paths, world, canon, series, story)
    # Explicitly ensure NO cover image exists
    cover_path = paths.cover_image(world, canon, series, story)
    assert not cover_path.exists()

    # Should not raise
    bundle_path = build_lulu_bundle(paths, world, canon, series, story)
    assert bundle_path.exists()
