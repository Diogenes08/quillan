"""Tests for F3 — Interactive Outline Editor (quillan/structure/outline_editor.py)."""

from __future__ import annotations

import json

import pytest
import yaml
from click.testing import CliRunner

from quillan.structure.outline_editor import (
    add_beat_to_outline,
    format_outline,
    rebuild_dep_map_linear,
    validate_outline,
    write_stub_beat_spec,
)


# ── Fixtures / helpers ────────────────────────────────────────────────────────

def _minimal_outline(n_chapters=2, beats_per_chapter=2) -> dict:
    chapters = []
    for ch in range(1, n_chapters + 1):
        beats = []
        for b in range(1, beats_per_chapter + 1):
            beats.append({
                "beat_id": f"C{ch}-S1-B{b}",
                "title": f"Beat {b}",
                "goal": f"Chapter {ch} beat {b} goal.",
                "word_count_target": 1000,
            })
        chapters.append({"chapter": ch, "title": f"Chapter {ch}", "beats": beats})
    return {"title": "Test Story", "genre": "noir", "chapters": chapters}


def _make_outline_file(paths, world, canon, series, story, outline_data=None):
    data = outline_data or _minimal_outline()
    outline_path = paths.outline(world, canon, series, story)
    paths.ensure(outline_path)
    outline_path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    return outline_path


# ── validate_outline ──────────────────────────────────────────────────────────

def test_validate_outline_valid():
    assert validate_outline(_minimal_outline()) == []


def test_validate_outline_not_dict():
    errors = validate_outline(["not", "a", "dict"])
    assert any("mapping" in e for e in errors)


def test_validate_outline_missing_title():
    data = _minimal_outline()
    del data["title"]
    errors = validate_outline(data)
    assert any("title" in e for e in errors)


def test_validate_outline_missing_chapters():
    errors = validate_outline({"title": "Story"})
    assert any("chapters" in e for e in errors)


def test_validate_outline_empty_chapters():
    errors = validate_outline({"title": "Story", "chapters": []})
    assert any("non-empty" in e for e in errors)


def test_validate_outline_beat_missing_goal():
    data = _minimal_outline(n_chapters=1, beats_per_chapter=1)
    del data["chapters"][0]["beats"][0]["goal"]
    errors = validate_outline(data)
    assert any("goal" in e for e in errors)


def test_validate_outline_beat_missing_id():
    data = _minimal_outline(n_chapters=1, beats_per_chapter=1)
    del data["chapters"][0]["beats"][0]["beat_id"]
    errors = validate_outline(data)
    assert any("beat_id" in e for e in errors)


def test_validate_outline_duplicate_beat_id():
    data = _minimal_outline(n_chapters=1, beats_per_chapter=2)
    data["chapters"][0]["beats"][1]["beat_id"] = data["chapters"][0]["beats"][0]["beat_id"]
    errors = validate_outline(data)
    assert any("Duplicate" in e for e in errors)


# ── rebuild_dep_map_linear ────────────────────────────────────────────────────

def test_rebuild_dep_map_linear_structure():
    data = _minimal_outline(n_chapters=2, beats_per_chapter=2)
    dep_map = rebuild_dep_map_linear(data)
    assert "dependencies" in dep_map
    deps = dep_map["dependencies"]
    assert deps["C1-S1-B1"] == []
    assert deps["C1-S1-B2"] == ["C1-S1-B1"]
    assert deps["C2-S1-B1"] == ["C1-S1-B2"]
    assert deps["C2-S1-B2"] == ["C2-S1-B1"]


def test_rebuild_dep_map_linear_single_beat():
    data = _minimal_outline(n_chapters=1, beats_per_chapter=1)
    deps = rebuild_dep_map_linear(data)["dependencies"]
    assert deps["C1-S1-B1"] == []


def test_rebuild_dep_map_linear_all_beats_present():
    data = _minimal_outline(n_chapters=3, beats_per_chapter=3)
    deps = rebuild_dep_map_linear(data)["dependencies"]
    assert len(deps) == 9


# ── add_beat_to_outline ───────────────────────────────────────────────────────

def test_add_beat_to_outline_assigns_next_id():
    data = _minimal_outline(n_chapters=1, beats_per_chapter=2)
    updated, new_id = add_beat_to_outline(data, 1, "A new goal.")
    assert new_id == "C1-S1-B3"


def test_add_beat_to_outline_appends_to_chapter():
    data = _minimal_outline(n_chapters=2, beats_per_chapter=1)
    updated, new_id = add_beat_to_outline(data, 2, "Chapter 2 extension.")
    chapter_2 = next(c for c in updated["chapters"] if c["chapter"] == 2)
    assert len(chapter_2["beats"]) == 2
    assert chapter_2["beats"][-1]["beat_id"] == new_id


def test_add_beat_to_outline_does_not_mutate_original():
    data = _minimal_outline(n_chapters=1, beats_per_chapter=2)
    original_count = len(data["chapters"][0]["beats"])
    add_beat_to_outline(data, 1, "A goal.")
    assert len(data["chapters"][0]["beats"]) == original_count  # deep copy


def test_add_beat_to_outline_invalid_chapter_raises():
    data = _minimal_outline(n_chapters=1, beats_per_chapter=1)
    with pytest.raises(ValueError, match="Chapter 99"):
        add_beat_to_outline(data, 99, "Goal.")


def test_add_beat_stores_goal_and_word_count():
    data = _minimal_outline(n_chapters=1, beats_per_chapter=1)
    updated, new_id = add_beat_to_outline(data, 1, "Specific goal.", word_count=2000)
    beat = next(
        b for ch in updated["chapters"] for b in ch["beats"] if b["beat_id"] == new_id
    )
    assert beat["goal"] == "Specific goal."
    assert beat["word_count_target"] == 2000


# ── write_stub_beat_spec ──────────────────────────────────────────────────────

def test_write_stub_beat_spec_creates_file(paths, world, canon, series, story):
    spec_path = write_stub_beat_spec(
        paths, world, canon, series, story, "C1-S1-B1", "A goal."
    )
    assert spec_path.exists()
    data = yaml.safe_load(spec_path.read_text())
    assert data["beat_id"] == "C1-S1-B1"
    assert data["goal"] == "A goal."


def test_write_stub_beat_spec_does_not_overwrite(paths, world, canon, series, story):
    spec_path = write_stub_beat_spec(
        paths, world, canon, series, story, "C1-S1-B1", "Original goal."
    )
    write_stub_beat_spec(paths, world, canon, series, story, "C1-S1-B1", "New goal.")
    data = yaml.safe_load(spec_path.read_text())
    assert data["goal"] == "Original goal."


# ── format_outline ────────────────────────────────────────────────────────────

def test_format_outline_contains_title(paths, world, canon, series, story):
    data = _minimal_outline()
    result = format_outline(data, paths, world, canon, series, story)
    assert "Test Story" in result


def test_format_outline_contains_beat_ids(paths, world, canon, series, story):
    data = _minimal_outline(n_chapters=1, beats_per_chapter=3)
    result = format_outline(data, paths, world, canon, series, story)
    assert "C1-S1-B1" in result
    assert "C1-S1-B3" in result


def test_format_outline_shows_pending_for_undrafted(paths, world, canon, series, story):
    data = _minimal_outline(n_chapters=1, beats_per_chapter=1)
    result = format_outline(data, paths, world, canon, series, story)
    assert "[pending]" in result


def test_format_outline_shows_drafted_when_draft_exists(paths, world, canon, series, story):
    data = _minimal_outline(n_chapters=1, beats_per_chapter=1)
    draft = paths.beat_draft(world, canon, series, story, "C1-S1-B1")
    paths.ensure(draft)
    draft.write_text("Draft prose.", encoding="utf-8")
    result = format_outline(data, paths, world, canon, series, story)
    assert "[drafted]" in result


def test_format_outline_shows_summary_line(paths, world, canon, series, story):
    data = _minimal_outline(n_chapters=2, beats_per_chapter=2)
    result = format_outline(data, paths, world, canon, series, story)
    assert "4 beats" in result
    assert "words target" in result


# ── CLI: show-outline ─────────────────────────────────────────────────────────

def test_cli_show_outline_no_outline_exits_1(tmp_path):
    from quillan.cli import main
    from quillan.paths import Paths

    p = Paths(tmp_path)
    p.story("w", "c", "s", "nostory").mkdir(parents=True, exist_ok=True)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--data-dir", str(tmp_path), "--world", "w", "--canon", "c",
         "--series", "s", "show-outline", "nostory"],
    )
    assert result.exit_code == 1


def test_cli_show_outline_prints_outline(tmp_path):
    from quillan.cli import main
    from quillan.paths import Paths

    p = Paths(tmp_path)
    _make_outline_file(p, "w", "c", "s", "mystory")

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--data-dir", str(tmp_path), "--world", "w", "--canon", "c",
         "--series", "s", "show-outline", "mystory"],
    )
    assert result.exit_code == 0
    assert "Test Story" in result.output
    assert "C1-S1-B1" in result.output


# ── CLI: add-beat ─────────────────────────────────────────────────────────────

def test_cli_add_beat_appends_to_outline(tmp_path):
    from quillan.cli import main
    from quillan.paths import Paths

    p = Paths(tmp_path)
    _make_outline_file(p, "w", "c", "s", "mystory")

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--data-dir", str(tmp_path), "--world", "w", "--canon", "c",
         "--series", "s", "add-beat", "mystory",
         "--chapter", "1", "--goal", "The detective finds a clue."],
    )
    assert result.exit_code == 0, result.output
    assert "C1-S1-B3" in result.output  # 2 existing + 1 new


def test_cli_add_beat_creates_spec(tmp_path):
    from quillan.cli import main
    from quillan.paths import Paths

    p = Paths(tmp_path)
    _make_outline_file(p, "w", "c", "s", "mystory")

    runner = CliRunner()
    runner.invoke(
        main,
        ["--data-dir", str(tmp_path), "--world", "w", "--canon", "c",
         "--series", "s", "add-beat", "mystory",
         "--chapter", "1", "--goal", "A new scene goal."],
    )
    spec = p.beat_spec("w", "c", "s", "mystory", "C1-S1-B3")
    assert spec.exists()
    data = yaml.safe_load(spec.read_text())
    assert data["goal"] == "A new scene goal."


def test_cli_add_beat_rebuilds_dep_map(tmp_path):
    from quillan.cli import main
    from quillan.paths import Paths

    p = Paths(tmp_path)
    _make_outline_file(p, "w", "c", "s", "mystory")

    runner = CliRunner()
    runner.invoke(
        main,
        ["--data-dir", str(tmp_path), "--world", "w", "--canon", "c",
         "--series", "s", "add-beat", "mystory",
         "--chapter", "2", "--goal", "Another goal."],
    )
    dep_path = p.dependency_map("w", "c", "s", "mystory")
    assert dep_path.exists()
    dep_data = json.loads(dep_path.read_text())
    assert "C2-S1-B3" in dep_data["dependencies"]


def test_cli_add_beat_invalid_chapter_exits_1(tmp_path):
    from quillan.cli import main
    from quillan.paths import Paths

    p = Paths(tmp_path)
    _make_outline_file(p, "w", "c", "s", "mystory")

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--data-dir", str(tmp_path), "--world", "w", "--canon", "c",
         "--series", "s", "add-beat", "mystory",
         "--chapter", "99", "--goal", "Goal."],
    )
    assert result.exit_code == 1
