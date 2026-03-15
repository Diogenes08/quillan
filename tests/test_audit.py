"""Tests for quillan.draft.audit — mega_audit orchestration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock



# ── Helpers ────────────────────────────────────────────────────────────────────


def _beat_setup(paths, world, canon, series, story, beat_id, spec_text="", draft_text="draft prose"):
    """Create minimal beat directory with optional spec and draft files."""
    from quillan.io import atomic_write

    beat_dir = paths.beat(world, canon, series, story, beat_id)
    beat_dir.mkdir(parents=True, exist_ok=True)

    if spec_text:
        atomic_write(paths.beat_spec(world, canon, series, story, beat_id), spec_text)
    if draft_text:
        atomic_write(paths.beat_draft(world, canon, series, story, beat_id), draft_text)

    return beat_dir


def _offline_llm():
    """LLM mock that reports no API keys (offline mode)."""
    llm = MagicMock()
    llm.settings = MagicMock()
    llm.settings.has_api_keys = False
    return llm


def _online_llm(return_value: dict):
    """LLM mock that returns *return_value* from call_json."""
    llm = MagicMock()
    llm.settings = MagicMock()
    llm.settings.has_api_keys = True
    llm.call_json = AsyncMock(return_value=return_value)
    return llm


# ── Offline mode ───────────────────────────────────────────────────────────────


async def test_mega_audit_offline_returns_pass(tmp_path, paths, world, canon, series, story):
    """Without API keys, mega_audit returns the empty PASS audit dict."""
    from quillan.draft.audit import mega_audit

    beat_id = "C1-S1-B1"
    _beat_setup(paths, world, canon, series, story, beat_id)

    result = await mega_audit(paths, world, canon, series, story, beat_id, _offline_llm())

    assert result["overall_pass"] is True
    assert result["fix_list"] == []


async def test_mega_audit_offline_writes_json(tmp_path, paths, world, canon, series, story):
    """Offline mode still writes mega_audit.json and fix_list.txt to disk."""
    from quillan.draft.audit import mega_audit
    import json

    beat_id = "C1-S1-B2"
    _beat_setup(paths, world, canon, series, story, beat_id)

    await mega_audit(paths, world, canon, series, story, beat_id, _offline_llm())

    audit_path = paths.beat_mega_audit(world, canon, series, story, beat_id)
    assert audit_path.exists()
    data = json.loads(audit_path.read_text())
    assert data["overall_pass"] is True


# ── Online mode — pass result ──────────────────────────────────────────────────


async def test_mega_audit_online_pass(paths, world, canon, series, story):
    """LLM returning overall_pass=True propagates correctly."""
    from quillan.draft.audit import mega_audit

    beat_id = "C1-S1-B3"
    _beat_setup(paths, world, canon, series, story, beat_id,
                draft_text="Good prose here.")

    llm_result = {
        "overall_pass": True,
        "spec_validity": {"pass": True, "notes": "ok"},
        "scope_contract": {"pass": True, "missing_items": [], "notes": "ok"},
        "rule_compliance": {"pass": True, "violations": [], "notes": "ok"},
        "continuity": {"pass": True, "issues": [], "notes": "ok"},
        "tone_drift": {"pass": True, "notes": "ok"},
        "voice_compliance": {"pass": True, "notes": "ok"},
        "pov_consistency": {"pass": True, "notes": "ok"},
        "actual_word_count": 3,
        "fix_list": [],
    }
    result = await mega_audit(paths, world, canon, series, story, beat_id, _online_llm(llm_result))

    assert result["overall_pass"] is True
    assert result["fix_list"] == []


# ── Online mode — fail result ──────────────────────────────────────────────────


async def test_mega_audit_online_fail_with_fixes(paths, world, canon, series, story):
    """LLM returning overall_pass=False and fix_list propagates correctly."""
    from quillan.draft.audit import mega_audit

    beat_id = "C1-S1-B4"
    _beat_setup(paths, world, canon, series, story, beat_id, draft_text="Weak prose.")

    llm_result = {
        "overall_pass": False,
        "spec_validity": {"pass": False, "notes": "missing goal"},
        "scope_contract": {"pass": True, "missing_items": [], "notes": "ok"},
        "rule_compliance": {"pass": True, "violations": [], "notes": "ok"},
        "continuity": {"pass": True, "issues": [], "notes": "ok"},
        "tone_drift": {"pass": True, "notes": "ok"},
        "voice_compliance": {"pass": True, "notes": "ok"},
        "pov_consistency": {"pass": True, "notes": "ok"},
        "actual_word_count": 2,
        "fix_list": ["Expand the scene", "Show don't tell"],
    }
    result = await mega_audit(paths, world, canon, series, story, beat_id, _online_llm(llm_result))

    assert result["overall_pass"] is False
    assert "Expand the scene" in result["fix_list"]
    assert "Show don't tell" in result["fix_list"]


# ── LLM failure fallback ───────────────────────────────────────────────────────


async def test_mega_audit_llm_failure_returns_pass(paths, world, canon, series, story):
    """If the LLM call raises, mega_audit falls back to empty PASS result."""
    from quillan.draft.audit import mega_audit

    beat_id = "C1-S1-B5"
    _beat_setup(paths, world, canon, series, story, beat_id, draft_text="some prose")

    llm = MagicMock()
    llm.settings = MagicMock()
    llm.settings.has_api_keys = True
    llm.call_json = AsyncMock(side_effect=RuntimeError("network error"))

    result = await mega_audit(paths, world, canon, series, story, beat_id, llm)

    # Falls back gracefully — does not raise
    assert result["overall_pass"] is True
    assert result["fix_list"] == []


# ── Missing draft ──────────────────────────────────────────────────────────────


async def test_mega_audit_missing_draft_returns_pass(paths, world, canon, series, story):
    """mega_audit returns PASS dict when no Beat_Draft.md exists yet."""
    from quillan.draft.audit import mega_audit

    beat_id = "C1-S1-B6"
    # Create beat dir but no draft file
    paths.beat(world, canon, series, story, beat_id).mkdir(parents=True, exist_ok=True)

    llm = MagicMock()
    llm.settings = MagicMock()
    llm.settings.has_api_keys = True

    result = await mega_audit(paths, world, canon, series, story, beat_id, llm)

    assert result["overall_pass"] is True
