"""Tests for F4 — Continuity Drift Detection (quillan/continuity/drift.py)."""

from __future__ import annotations

import pytest

from quillan.continuity.drift import (
    DriftReport,
    _check_duplicate_sentences,
    _check_open_threads,
    _load_beat_drafts,
    check_drift,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_draft(paths, world, canon, series, story, beat_id: str, text: str) -> None:
    draft_path = paths.beat_draft(world, canon, series, story, beat_id)
    paths.ensure(draft_path)
    draft_path.write_text(text, encoding="utf-8")


def _write_threads(paths, world, canon, series, story, text: str) -> None:
    t = paths.continuity_threads(world, canon, series, story)
    paths.ensure(t)
    t.write_text(text, encoding="utf-8")


# ── _load_beat_drafts ─────────────────────────────────────────────────────────

def test_load_beat_drafts_empty(paths, world, canon, series, story):
    """Returns empty dict when no beats directory exists."""
    result = _load_beat_drafts(paths, world, canon, series, story)
    assert result == {}


def test_load_beat_drafts_returns_all_drafts(paths, world, canon, series, story):
    _write_draft(paths, world, canon, series, story, "C1-S1-B1", "First beat prose.")
    _write_draft(paths, world, canon, series, story, "C1-S1-B2", "Second beat prose.")
    result = _load_beat_drafts(paths, world, canon, series, story)
    assert set(result.keys()) == {"C1-S1-B1", "C1-S1-B2"}


def test_load_beat_drafts_ignores_missing_draft_file(paths, world, canon, series, story):
    """Beat directories without Beat_Draft.md are skipped."""
    beat_dir = paths.story_beats(world, canon, series, story) / "C1-S1-B1"
    beat_dir.mkdir(parents=True, exist_ok=True)
    # No Beat_Draft.md written
    result = _load_beat_drafts(paths, world, canon, series, story)
    assert result == {}


# ── _check_duplicate_sentences ────────────────────────────────────────────────

def test_no_duplicates_produces_no_issues():
    drafts = {
        "C1-S1-B1": "The rain fell hard on the cobblestones tonight.",
        "C1-S1-B2": "She pulled her coat tight and stepped into the alley.",
    }
    report = DriftReport(story="s")
    _check_duplicate_sentences(drafts, report)
    assert report.issues == []


def test_duplicate_sentence_flagged():
    shared = "The old clock on the mantelpiece struck midnight with a hollow tone."
    drafts = {
        "C1-S1-B1": f"She listened carefully. {shared} Something moved upstairs.",
        "C2-S1-B1": f"He returned to the parlour. {shared} The fire had gone out.",
    }
    report = DriftReport(story="s")
    _check_duplicate_sentences(drafts, report)
    assert len(report.issues) == 1
    assert report.issues[0].kind == "duplicate_sentence"
    assert "C1-S1-B1" in report.issues[0].beat_id or "C2-S1-B1" in report.issues[0].description


def test_duplicate_within_same_beat_not_flagged():
    """A sentence repeated within the same beat is not a cross-beat duplicate."""
    text = (
        "She waited. She waited. "
        "The long sentence here makes it long enough for the regex to match it properly."
    )
    drafts = {"C1-S1-B1": text}
    report = DriftReport(story="s")
    _check_duplicate_sentences(drafts, report)
    assert report.issues == []


def test_short_sentences_not_flagged():
    """Sentences shorter than the regex minimum are not flagged."""
    drafts = {
        "C1-S1-B1": "Yes. No. She smiled.",
        "C1-S1-B2": "Yes. No. She frowned.",
    }
    report = DriftReport(story="s")
    _check_duplicate_sentences(drafts, report)
    assert report.issues == []


def test_multiple_duplicate_pairs_each_flagged_once():
    s1 = "The harbour lights flickered and went dark one by one across the bay."
    s2 = "Rain hammered the iron roof with a sound like someone throwing gravel."
    drafts = {
        "C1-S1-B1": f"{s1} Unrelated sentence one.",
        "C1-S1-B2": f"{s1} Unrelated sentence two.",
        "C2-S1-B1": f"{s2} Unrelated sentence three.",
        "C2-S1-B2": f"{s2} Unrelated sentence four.",
    }
    report = DriftReport(story="s")
    _check_duplicate_sentences(drafts, report)
    # Each duplicate pair flagged once
    dup_issues = [i for i in report.issues if i.kind == "duplicate_sentence"]
    assert len(dup_issues) == 2


# ── _check_open_threads ───────────────────────────────────────────────────────

def test_no_threads_file_produces_no_issues(paths, world, canon, series, story):
    drafts = {"C1-S1-B1": "Some prose here."}
    report = DriftReport(story="s")
    _check_open_threads(paths, world, canon, series, story, drafts, report)
    assert report.issues == []


def test_thread_referenced_in_draft_not_flagged(paths, world, canon, series, story):
    _write_threads(paths, world, canon, series, story,
                   "## Stolen Artifact\nThe artifact was taken in chapter two.")
    drafts = {"C1-S1-B1": "She found the stolen artifact hidden beneath the floorboards."}
    report = DriftReport(story="s")
    _check_open_threads(paths, world, canon, series, story, drafts, report)
    thread_issues = [i for i in report.issues if i.kind == "open_thread"]
    assert thread_issues == []


def test_unreferenced_thread_flagged(paths, world, canon, series, story):
    _write_threads(paths, world, canon, series, story,
                   "## Missing Heirloom\nThe grandmother's locket was never found.")
    drafts = {"C1-S1-B1": "He walked down the street feeling nothing in particular."}
    report = DriftReport(story="s")
    _check_open_threads(paths, world, canon, series, story, drafts, report)
    thread_issues = [i for i in report.issues if i.kind == "open_thread"]
    assert len(thread_issues) == 1
    assert thread_issues[0].severity == "info"
    assert "Missing Heirloom" in thread_issues[0].description


def test_multiple_threads_partial_match(paths, world, canon, series, story):
    _write_threads(paths, world, canon, series, story,
                   "## The Conspiracy\nSomething dark is coming.\n\n## Vanished Detective\nWhere is he?")
    # Only one thread's keyword appears
    drafts = {"C1-S1-B1": "The conspiracy was finally revealed in a midnight meeting."}
    report = DriftReport(story="s")
    _check_open_threads(paths, world, canon, series, story, drafts, report)
    thread_issues = [i for i in report.issues if i.kind == "open_thread"]
    assert len(thread_issues) == 1
    assert "Vanished Detective" in thread_issues[0].description


# ── check_drift (integration) ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_drift_no_beats_returns_empty(paths, world, canon, series, story, settings):
    report = await check_drift(paths, world, canon, series, story, settings)
    assert report.checked_beats == 0
    assert report.issues == []


@pytest.mark.asyncio
async def test_check_drift_counts_beats(paths, world, canon, series, story, settings):
    _write_draft(paths, world, canon, series, story, "C1-S1-B1", "Beat one prose here.")
    _write_draft(paths, world, canon, series, story, "C1-S1-B2", "Beat two prose here.")
    report = await check_drift(paths, world, canon, series, story, settings)
    assert report.checked_beats == 2


@pytest.mark.asyncio
async def test_check_drift_detects_duplicate(paths, world, canon, series, story, settings):
    shared = "The fog rolled in from the harbour as the last ferry departed at dusk."
    _write_draft(paths, world, canon, series, story, "C1-S1-B1",
                 f"Opening scene. {shared} She watched it go.")
    _write_draft(paths, world, canon, series, story, "C2-S1-B1",
                 f"Later that night. {shared} Nothing had changed.")
    report = await check_drift(paths, world, canon, series, story, settings)
    kinds = [i.kind for i in report.issues]
    assert "duplicate_sentence" in kinds


@pytest.mark.asyncio
async def test_check_drift_llm_phase_adds_issues(paths, world, canon, series, story, settings):
    """LLM phase appends issues from the stub response."""
    _write_draft(paths, world, canon, series, story, "C1-S1-B1", "Some prose beat.")

    class _StubLLM:
        async def call_json(self, *args, **kwargs):
            return {
                "issues": [
                    {
                        "beat_id": "C1-S1-B1",
                        "description": "Character hair colour changed from red to blonde.",
                        "severity": "warn",
                    }
                ]
            }

    report = await check_drift(
        paths, world, canon, series, story, settings, llm=_StubLLM()
    )
    llm_issues = [i for i in report.issues if i.kind == "llm_flag"]
    assert len(llm_issues) == 1
    assert "hair colour" in llm_issues[0].description
    assert report.llm_checked is True


@pytest.mark.asyncio
async def test_check_drift_llm_error_adds_info_issue(paths, world, canon, series, story, settings):
    """LLM errors are recorded as info items, not crashes."""
    from quillan.llm import LLMError

    _write_draft(paths, world, canon, series, story, "C1-S1-B1", "Some prose beat.")

    class _FailLLM:
        async def call_json(self, *args, **kwargs):
            raise LLMError("network timeout")

    report = await check_drift(
        paths, world, canon, series, story, settings, llm=_FailLLM()
    )
    error_issues = [i for i in report.issues if i.kind == "llm_error"]
    assert len(error_issues) == 1
    assert error_issues[0].severity == "info"


# ── DriftReport helpers ───────────────────────────────────────────────────────

def test_drift_report_warn_count():
    r = DriftReport(story="s")
    r.add("b1", "duplicate_sentence", "dup", severity="warn")
    r.add("", "open_thread", "thread", severity="info")
    assert r.warn_count == 1
    assert r.info_count == 1


# ── CLI: continuity-check ─────────────────────────────────────────────────────

def _make_story(paths, world, canon, series, story):
    paths.story(world, canon, series, story).mkdir(parents=True, exist_ok=True)


def test_cli_continuity_check_no_story_exits_1(tmp_path):
    from click.testing import CliRunner
    from quillan.cli import main

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--data-dir", str(tmp_path), "--world", "w", "--canon", "c",
         "--series", "s", "continuity-check", "nonexistent"],
    )
    assert result.exit_code == 1


def test_cli_continuity_check_clean_story_exits_0(tmp_path):
    from click.testing import CliRunner
    from quillan.cli import main
    from quillan.paths import Paths

    p = Paths(tmp_path)
    _make_story(p, "w", "c", "s", "mystory")

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--data-dir", str(tmp_path), "--world", "w", "--canon", "c",
         "--series", "s", "continuity-check", "mystory"],
    )
    assert result.exit_code == 0
    assert "No issues found" in result.output


def test_cli_continuity_check_with_duplicate_exits_1(tmp_path):
    from click.testing import CliRunner
    from quillan.cli import main
    from quillan.paths import Paths

    p = Paths(tmp_path)
    _make_story(p, "w", "c", "s", "mystory")
    shared = "The candle guttered in the draught and threw wild shadows across the ceiling."
    _write_draft(p, "w", "c", "s", "mystory", "C1-S1-B1",
                 f"She entered the room. {shared} Nothing had changed.")
    _write_draft(p, "w", "c", "s", "mystory", "C1-S1-B2",
                 f"He stepped inside. {shared} Everything felt different.")

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--data-dir", str(tmp_path), "--world", "w", "--canon", "c",
         "--series", "s", "continuity-check", "mystory"],
    )
    assert result.exit_code == 1
    assert "duplicate" in result.output.lower()


def test_cli_continuity_check_output_file(tmp_path):
    from click.testing import CliRunner
    from quillan.cli import main
    from quillan.paths import Paths

    p = Paths(tmp_path)
    _make_story(p, "w", "c", "s", "mystory")
    out_file = tmp_path / "drift_report.md"

    runner = CliRunner()
    runner.invoke(
        main,
        ["--data-dir", str(tmp_path), "--world", "w", "--canon", "c",
         "--series", "s", "continuity-check", "mystory",
         "--output", str(out_file)],
    )
    assert out_file.exists()
    assert "Continuity Check" in out_file.read_text()
