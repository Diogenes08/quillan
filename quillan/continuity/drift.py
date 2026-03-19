"""Continuity drift detection for Quillan stories.

Two-phase analysis:
  Phase 1 (pure Python, always runs):
    - Duplicate sentences across beat drafts
    - Open threads with no keyword match in any draft

  Phase 2 (LLM, optional):
    - Semantic drift against current story state and open threads
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quillan.llm import LLMClient
    from quillan.paths import Paths
    from quillan.config import Settings

# Matches sentence-ending punctuation; requires at least 30 chars to avoid
# flagging fragments like "Yes." or "She nodded."
_SENTENCE_RE = re.compile(r"[^.!?]{20,}[.!?]")

# Markdown headings (any level) for extracting thread titles
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)

_STOPWORDS = frozenset({
    "about", "after", "also", "been", "each", "even", "from", "have",
    "into", "like", "more", "only", "over", "some", "such", "than",
    "that", "their", "them", "then", "there", "they", "this", "time",
    "very", "what", "when", "which", "with", "your",
})

# Cap on state/threads/drafts fed to the LLM drift check
_STATE_MAX_CHARS = 2000
_THREADS_MAX_CHARS = 1500
_DRAFT_EXCERPT_CHARS = 900   # per beat
_MAX_BEATS_FOR_LLM = 6


@dataclass
class DriftIssue:
    beat_id: str       # empty string means story-level
    kind: str          # "duplicate_sentence" | "open_thread" | "llm_flag" | "llm_error"
    description: str
    severity: str = "warn"  # "warn" | "info"


@dataclass
class DriftReport:
    story: str
    issues: list[DriftIssue] = field(default_factory=list)
    checked_beats: int = 0
    llm_checked: bool = False

    def add(
        self,
        beat_id: str,
        kind: str,
        description: str,
        severity: str = "warn",
    ) -> None:
        self.issues.append(DriftIssue(beat_id, kind, description, severity))

    @property
    def warn_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warn")

    @property
    def info_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "info")


# ── Data loading ──────────────────────────────────────────────────────────────


def _load_beat_drafts(
    paths: "Paths", world: str, canon: str, series: str, story: str
) -> dict[str, str]:
    """Return ``{beat_id: text}`` for every beat that has a Beat_Draft.md, sorted by ID."""
    beats_dir = paths.story_beats(world, canon, series, story)
    if not beats_dir.exists():
        return {}
    result: dict[str, str] = {}
    for beat_dir in sorted(beats_dir.iterdir()):
        if not beat_dir.is_dir():
            continue
        draft = beat_dir / "Beat_Draft.md"
        if draft.exists():
            try:
                result[beat_dir.name] = draft.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
    return result


# ── Phase 1: pure-Python checks ───────────────────────────────────────────────


def _extract_sentences(text: str) -> list[str]:
    return [m.group(0).strip() for m in _SENTENCE_RE.finditer(text)]


def _check_duplicate_sentences(
    drafts: dict[str, str], report: DriftReport
) -> None:
    """Flag sentences that appear verbatim in two or more different beats."""
    # Map normalised sentence → list of beat IDs that contain it
    sentence_beats: dict[str, list[str]] = defaultdict(list)
    for beat_id, text in drafts.items():
        seen_in_beat: set[str] = set()
        for sentence in _extract_sentences(text):
            norm = " ".join(sentence.lower().split())
            if norm not in seen_in_beat:
                sentence_beats[norm].append(beat_id)
                seen_in_beat.add(norm)

    reported: set[frozenset[str]] = set()
    for norm_sentence, beat_ids in sentence_beats.items():
        unique = list(dict.fromkeys(beat_ids))
        if len(unique) < 2:
            continue
        key = frozenset(unique[:2])
        if key in reported:
            continue
        reported.add(key)
        beats_str = ", ".join(unique[:3]) + ("…" if len(unique) > 3 else "")
        preview = norm_sentence[:80] + ("…" if len(norm_sentence) > 80 else "")
        report.add(
            unique[0],
            "duplicate_sentence",
            f'Sentence appears verbatim in beats {beats_str}: "{preview}"',
        )


def _check_open_threads(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    drafts: dict[str, str],
    report: DriftReport,
) -> None:
    """Flag open threads whose keywords never appear in any beat draft."""
    threads_path = paths.continuity_threads(world, canon, series, story)
    if not threads_path.exists():
        return
    try:
        threads_text = threads_path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return
    if not threads_text:
        return

    all_drafts_lower = " ".join(drafts.values()).lower()
    headings = _HEADING_RE.findall(threads_text)

    for heading in headings:
        heading = heading.strip()
        keywords = [
            w for w in heading.lower().split()
            if len(w) > 3 and w not in _STOPWORDS
        ]
        if not keywords:
            continue
        if not any(kw in all_drafts_lower for kw in keywords):
            report.add(
                "",
                "open_thread",
                f'Open thread "{heading}" — no keyword match in any beat draft.',
                severity="info",
            )


# ── Phase 2: LLM semantic check ───────────────────────────────────────────────


async def _check_llm(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    drafts: dict[str, str],
    llm: "LLMClient",
    settings: "Settings",
    report: DriftReport,
) -> None:
    """Feed state + threads + recent drafts to the LLM for semantic drift."""
    from quillan.llm import LLMError
    from quillan.templates import get_prompt

    _story_dir = paths.story(world, canon, series, story)
    _world_dir = paths.world(world)

    # Current state
    state_text = "(no state file)"
    state_path = paths.state_current(world, canon, series, story)
    if state_path.exists():
        try:
            state_text = state_path.read_text(encoding="utf-8", errors="replace")
            state_text = state_text[:_STATE_MAX_CHARS]
        except OSError:
            pass

    # Open threads
    threads_text = "(no open threads)"
    threads_path = paths.continuity_threads(world, canon, series, story)
    if threads_path.exists():
        try:
            t = threads_path.read_text(encoding="utf-8", errors="replace").strip()
            threads_text = t[:_THREADS_MAX_CHARS] if t else threads_text
        except OSError:
            pass

    # Most recent beats
    recent = list(drafts.items())[-_MAX_BEATS_FOR_LLM:]
    beats_summary = "\n\n---\n\n".join(
        f"[{bid}]\n{text[:_DRAFT_EXCERPT_CHARS]}" for bid, text in recent
    )

    system = get_prompt("continuity_drift_system", story_dir=_story_dir, world_dir=_world_dir)
    user = get_prompt("continuity_drift_user", story_dir=_story_dir, world_dir=_world_dir).format(
        state=state_text,
        threads=threads_text,
        drafts=beats_summary or "(no beat drafts)",
    )

    try:
        result = await llm.call_json("planning", system, user, required_keys=["issues"])
    except LLMError as exc:
        report.add("", "llm_error", f"LLM drift check failed: {exc}", severity="info")
        return

    for issue in result.get("issues", []):
        if not isinstance(issue, dict):
            continue
        report.add(
            issue.get("beat_id", ""),
            "llm_flag",
            issue.get("description", str(issue)),
            severity=issue.get("severity", "warn"),
        )

    report.llm_checked = True


# ── Public API ────────────────────────────────────────────────────────────────


async def check_drift(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    settings: "Settings",
    *,
    llm: "LLMClient | None" = None,
) -> DriftReport:
    """Run continuity drift checks on all beat drafts for *story*.

    Phase 1 (pure Python, always): duplicate sentences, orphaned open threads.
    Phase 2 (LLM, only when *llm* is provided): semantic contradictions.

    Returns a :class:`DriftReport` with all found issues.
    """
    report = DriftReport(story=story)
    drafts = _load_beat_drafts(paths, world, canon, series, story)
    report.checked_beats = len(drafts)

    if not drafts:
        return report

    _check_duplicate_sentences(drafts, report)
    _check_open_threads(paths, world, canon, series, story, drafts, report)

    if llm is not None:
        await _check_llm(paths, world, canon, series, story, drafts, llm, settings, report)

    return report
