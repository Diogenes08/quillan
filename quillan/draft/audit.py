"""Mega-audit: single LLM forensic call to validate a beat draft."""

from __future__ import annotations

import logging
from quillan.templates import get_prompt
from typing import TYPE_CHECKING

logger = logging.getLogger("quillan.draft.audit")

if TYPE_CHECKING:
    from quillan.llm import LLMClient
    from quillan.paths import Paths



_EMPTY_AUDIT: dict = {
    "overall_pass": True,
    "spec_validity": {"pass": True, "notes": "offline"},
    "scope_contract": {"pass": True, "missing_items": [], "notes": "offline"},
    "rule_compliance": {"pass": True, "violations": [], "notes": "offline"},
    "continuity": {"pass": True, "issues": [], "notes": "offline"},
    "tone_drift": {"pass": True, "notes": "offline"},
    "voice_compliance": {"pass": True, "notes": "offline"},
    "pov_consistency": {"pass": True, "notes": "offline"},
    "actual_word_count": 0,
    "fix_list": [],
    "prose_issues": [],
}


async def mega_audit(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    beat_id: str,
    llm: "LLMClient",
) -> dict:
    """Single LLM call (forensic stage, json mode) → normalised audit result dict.

    All fields are guaranteed present with correct types.
    Writes mega_audit.json + fix_list.txt to beats/{beat_id}/forensic/.
    """
    from quillan.io import atomic_write
    import json

    forensic_dir = paths.beat_forensic_dir(world, canon, series, story, beat_id)
    forensic_dir.mkdir(parents=True, exist_ok=True)

    audit_path = paths.beat_mega_audit(world, canon, series, story, beat_id)
    fix_path = paths.beat_fix_list(world, canon, series, story, beat_id)

    if not llm.settings.has_api_keys:
        atomic_write(audit_path, json.dumps(_EMPTY_AUDIT, indent=2))
        atomic_write(fix_path, "")
        return dict(_EMPTY_AUDIT)

    # Read spec
    spec_path = paths.beat_spec(world, canon, series, story, beat_id)
    spec_text = spec_path.read_text(encoding="utf-8") if spec_path.exists() else ""

    # Read draft
    draft_path = paths.beat_draft(world, canon, series, story, beat_id)
    if not draft_path.exists():
        return dict(_EMPTY_AUDIT)
    draft_text = draft_path.read_text(encoding="utf-8", errors="replace")

    # Read continuity context
    summary_path = paths.continuity_summary(world, canon, series, story)
    threads_path = paths.continuity_threads(world, canon, series, story)
    continuity_parts = []
    if summary_path.exists():
        continuity_parts.append(summary_path.read_text(encoding="utf-8", errors="replace")[:2000])
    if threads_path.exists():
        continuity_parts.append(threads_path.read_text(encoding="utf-8", errors="replace")[:1000])
    continuity_text = "\n\n".join(continuity_parts)

    from quillan.draft.prose_analyzer import analyse_prose, format_report
    prior_drafts = _read_prior_drafts(paths, world, canon, series, story, beat_id)

    def _int_setting(name: str) -> "int | None":
        v = getattr(llm.settings, name, None)
        return v if isinstance(v, int) else None

    def _float_setting(name: str) -> "float | None":
        v = getattr(llm.settings, name, None)
        return v if isinstance(v, float) else None

    scanner = analyse_prose(
        draft_text,
        prior_drafts,
        word_overuse_min=_int_setting("prose_word_overuse_min"),
        phrase_overuse_min=_int_setting("prose_phrase_overuse_min"),
        opener_dominant_pct=_float_setting("prose_opener_dominant_pct"),
        adverb_density_warn=_float_setting("prose_adverb_density_warn"),
        story_overuse_beats=_int_setting("prose_story_overuse_beats"),
    )
    prose_analysis_text = format_report(scanner)

    user_prompt = get_prompt("audit_user", story_dir=paths.story(world, canon, series, story), world_dir=paths.world(world)).format(
        spec=spec_text[:2000],
        draft=draft_text[:4000],
        continuity=continuity_text,
        prose_analysis=prose_analysis_text,
    )

    required_keys = [
        "overall_pass", "spec_validity", "scope_contract",
        "rule_compliance", "continuity", "tone_drift",
        "voice_compliance", "pov_consistency", "actual_word_count", "fix_list",
    ]

    try:
        result = await llm.call_json("forensic", get_prompt("audit_system", story_dir=paths.story(world, canon, series, story), world_dir=paths.world(world)), user_prompt, required_keys)
        result = _normalise_audit(result)
    except Exception as exc:
        logger.warning("mega_audit failed for beat %s — using empty pass result: %s", beat_id, exc)
        result = dict(_EMPTY_AUDIT)

    result["prose_issues"] = scanner["issues"]

    # Write audit artifacts
    atomic_write(audit_path, json.dumps(result, indent=2))

    fix_items = result.get("fix_list", [])
    fix_text = "\n".join(f"- {item}" for item in fix_items if isinstance(item, str))
    atomic_write(fix_path, fix_text)

    return result


def _read_prior_drafts(
    paths: "Paths", world: str, canon: str, series: str, story: str, beat_id: str
) -> list[str]:
    """Return text of Beat_Draft.md for all beats other than beat_id."""
    beats_dir = paths.story_beats(world, canon, series, story)
    if not beats_dir.exists():
        return []
    out = []
    for d in beats_dir.iterdir():
        if d.is_dir() and d.name != beat_id:
            draft = d / "Beat_Draft.md"
            if draft.exists():
                out.append(draft.read_text(encoding="utf-8", errors="replace"))
    return out


def _normalise_audit(raw: dict) -> dict:
    """Ensure all expected fields are present with correct types."""
    result = dict(_EMPTY_AUDIT)

    result["overall_pass"] = bool(raw.get("overall_pass", True))
    result["fix_list"] = [str(x) for x in raw.get("fix_list", []) if x]
    result["actual_word_count"] = int(raw.get("actual_word_count", 0))
    result["prose_issues"] = [str(x) for x in raw.get("prose_issues", []) if x]

    for field in (
        "spec_validity", "scope_contract", "rule_compliance",
        "continuity", "tone_drift", "voice_compliance", "pov_consistency",
    ):
        if field in raw and isinstance(raw[field], dict):
            merged = dict(result[field])
            merged.update(raw[field])
            result[field] = merged

    return result
