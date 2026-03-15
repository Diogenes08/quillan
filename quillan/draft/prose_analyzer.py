"""Pure-Python prose frequency analyser — zero LLM calls, stdlib only.

Used by audit.py to inject factual repetition data into the forensic prompt,
giving the LLM concrete numbers rather than asking it to detect patterns itself.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Optional

# ── Thresholds (module-level defaults; overridable per-call or via Settings) ──

WORD_OVERUSE_MIN    = 5     # occurrences per beat → flag
PHRASE_OVERUSE_MIN  = 3     # 2-gram occurrences per beat → flag
OPENER_DOMINANT_PCT = 0.30  # fraction of sentences sharing first word → flag
ADVERB_DENSITY_WARN = 0.03  # fraction of words ending -ly (≥5 chars) → flag
STORY_OVERUSE_BEATS = 3     # word appears in this many prior beat drafts → flag

# ── Stopwords (~80 common English function words) ─────────────────────────────

_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "and", "but", "or", "nor", "so", "yet", "for", "of",
    "in", "on", "at", "to", "by", "up", "as", "is", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "will", "would", "shall", "should", "may", "might", "must", "can",
    "could", "not", "no", "nor", "it", "its", "i", "me", "my", "we",
    "our", "you", "your", "he", "him", "his", "she", "her", "they",
    "them", "their", "this", "that", "these", "those", "what", "which",
    "who", "whom", "when", "where", "why", "how", "all", "each", "every",
    "both", "few", "more", "most", "other", "some", "such", "than",
    "too", "very", "just", "also", "then", "than", "into", "onto",
    "upon", "from", "with", "about", "above", "below", "between", "through",
    "during", "before", "after", "if", "although", "because", "since",
    "while", "even", "still", "back", "here", "there", "now", "like",
    "get", "got", "said", "says", "went", "came", "come", "know",
    "one", "two", "out", "up", "down", "over", "any", "same",
})


# ── Internal helpers ──────────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    """Lowercase alphabetic tokens only."""
    return re.findall(r"[a-z]+", text.lower())


def _sentences(text: str) -> list[str]:
    """Split text into sentences on .!? boundaries."""
    # Split on sentence-ending punctuation followed by whitespace or end
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p.strip()]


def _ngrams(tokens: list[str], n: int) -> list[tuple[str, ...]]:
    """Generate n-grams from a token list."""
    return [tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]


def _first_word(sentence: str) -> Optional[str]:
    """Return the first alphabetic word of a sentence, title-cased comparison."""
    m = re.match(r"([A-Za-z]+)", sentence.strip())
    return m.group(1) if m else None


# ── Public API ────────────────────────────────────────────────────────────────

def analyse_prose(
    draft_text: str,
    prior_drafts: list[str] = [],
    *,
    word_overuse_min: int | None = None,
    phrase_overuse_min: int | None = None,
    opener_dominant_pct: float | None = None,
    adverb_density_warn: float | None = None,
    story_overuse_beats: int | None = None,
) -> dict:
    """Analyse prose for repetition, adverb density, and opener monotony.

    Threshold keyword arguments override the module-level defaults when provided.
    Pass values from ``Settings.prose_*`` fields to make thresholds configurable.

    Returns dict with keys:
        overused_words   – list of (word, count) for content words ≥ word_overuse_min
        overused_phrases – list of (phrase_str, count) for 2-grams ≥ phrase_overuse_min
        dominant_opener  – (word, fraction) or None
        adverb_density   – float 0.0–1.0
        top_adverbs      – list of up to 3 example -ly words
        story_overused   – list of (word, beat_count) where beat_count ≥ story_overuse_beats
        issues           – list of human-readable issue strings
    """
    _word_min    = word_overuse_min    if word_overuse_min    is not None else WORD_OVERUSE_MIN
    _phrase_min  = phrase_overuse_min  if phrase_overuse_min  is not None else PHRASE_OVERUSE_MIN
    _opener_pct  = opener_dominant_pct if opener_dominant_pct is not None else OPENER_DOMINANT_PCT
    _adverb_warn = adverb_density_warn if adverb_density_warn is not None else ADVERB_DENSITY_WARN
    _story_beats = story_overuse_beats if story_overuse_beats is not None else STORY_OVERUSE_BEATS

    tokens = _tokenize(draft_text)
    total_words = len(tokens)

    # Overused words (content words only)
    content_tokens = [t for t in tokens if t not in _STOPWORDS and len(t) >= 3]
    word_counts = Counter(content_tokens)
    overused_words: list[tuple[str, int]] = [
        (w, c) for w, c in word_counts.most_common()
        if c >= _word_min
    ]

    # Overused 2-gram phrases (from all tokens, skip stopword-only grams)
    bigrams = _ngrams(tokens, 2)
    phrase_counts: Counter[tuple[str, ...]] = Counter(bigrams)
    overused_phrases: list[tuple[str, int]] = []
    for gram, count in phrase_counts.most_common():
        if count < _phrase_min:
            break
        if all(w in _STOPWORDS for w in gram):
            continue
        overused_phrases.append((" ".join(gram), count))

    # Sentence opener dominance
    sentences = _sentences(draft_text)
    openers: list[str] = [w for s in sentences for w in (_first_word(s),) if w is not None]
    dominant_opener: Optional[tuple[str, float]] = None
    if openers:
        opener_counts: Counter[str] = Counter(openers)
        top_opener, top_count = opener_counts.most_common(1)[0]
        fraction = top_count / len(openers)
        if fraction >= _opener_pct:
            dominant_opener = (top_opener, round(fraction, 2))

    # Adverb density (-ly words ≥ 5 chars)
    adverbs = [t for t in tokens if t.endswith("ly") and len(t) >= 5]
    adverb_density = len(adverbs) / max(total_words, 1)
    adverb_counts: Counter[str] = Counter(adverbs)
    top_adverbs = [w for w, _ in adverb_counts.most_common(3)]

    # Story-wide overuse (word appears in ≥ _story_beats prior beats)
    story_overused: list[tuple[str, int]] = []
    if prior_drafts:
        prior_sets = [set(_tokenize(d)) - _STOPWORDS for d in prior_drafts]
        current_content = set(content_tokens)
        for word in sorted(current_content):
            beat_count = sum(1 for s in prior_sets if word in s)
            if beat_count >= _story_beats:
                story_overused.append((word, beat_count))
        story_overused.sort(key=lambda x: (-x[1], x[0]))

    # Build issues list
    issues: list[str] = []

    story_overused_words = {w for w, _ in story_overused}
    for word, beats in story_overused:
        per_beat = word_counts.get(word, 0)
        if per_beat >= _word_min:
            issues.append(
                f"'{word}' used {per_beat}\u00d7 in this beat, "
                f"story-wide across {beats} beats"
            )
        else:
            issues.append(f"'{word}' appears story-wide across {beats} beats")

    for word, count in overused_words:
        if word not in story_overused_words:
            issues.append(f"'{word}' used {count}\u00d7 in this beat")

    for phrase, count in overused_phrases:
        issues.append(f"phrase '{phrase}' repeated {count}\u00d7 in this beat")

    if dominant_opener is not None:
        opener_word, frac = dominant_opener
        pct = int(frac * 100)
        issues.append(f"{pct}% of sentences begin with '{opener_word}'")

    if adverb_density >= _adverb_warn and top_adverbs:
        pct_str = f"{adverb_density * 100:.1f}%"
        examples = ", ".join(top_adverbs)
        issues.append(f"Adverb density: {pct_str} — examples: {examples}")

    return {
        "overused_words":   overused_words,
        "overused_phrases": overused_phrases,
        "dominant_opener":  dominant_opener,
        "adverb_density":   adverb_density,
        "top_adverbs":      top_adverbs,
        "story_overused":   story_overused,
        "issues":           issues,
    }


def format_report(result: dict) -> str:
    """Format the issues list as a prompt section.

    Returns "" if result["issues"] is empty — the LLM sees no blank section.
    """
    issues: list[str] = result.get("issues", [])
    if not issues:
        return ""
    bullets = "\n".join(f"- {issue}" for issue in issues)
    return (
        "Local prose analysis (tool-detected — use to inform fix_list):\n"
        + bullets
    )
