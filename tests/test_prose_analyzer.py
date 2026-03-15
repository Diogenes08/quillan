"""Tests for quillan/draft/prose_analyzer.py — all sync, no fixtures, no LLM."""

from __future__ import annotations

from quillan.draft.prose_analyzer import (
    WORD_OVERUSE_MIN,
    PHRASE_OVERUSE_MIN,
    OPENER_DOMINANT_PCT,
    ADVERB_DENSITY_WARN,
    STORY_OVERUSE_BEATS,
    analyse_prose,
    format_report,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _varied_prose() -> str:
    """Return prose with varied vocabulary that should trigger no issues."""
    return (
        "The merchant arrived at the harbour just before dawn. "
        "Mist clung to the water like a second skin. "
        "She counted the crates twice, then signed the manifest. "
        "A gull wheeled overhead, crying once before vanishing. "
        "Nobody else was there to witness her departure. "
        "The ship carried salt, timber, and secrets. "
        "By midday she was already three leagues out to sea. "
        "Rain threatened from the north, but held off until evening. "
    )


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_no_issues_clean_prose():
    result = analyse_prose(_varied_prose())
    assert result["issues"] == [], f"Unexpected issues: {result['issues']}"


def test_overused_word_flagged():
    # Repeat "glanced" WORD_OVERUSE_MIN + 1 times
    count = WORD_OVERUSE_MIN + 1
    sentences = ["He glanced at the door." for _ in range(count)]
    draft = " ".join(sentences) + " Extra text with other words here and there."
    result = analyse_prose(draft)
    assert any("glanced" in issue for issue in result["issues"]), (
        f"Expected 'glanced' flagged; issues: {result['issues']}"
    )
    overused_words_map = dict(result["overused_words"])
    assert overused_words_map.get("glanced", 0) >= WORD_OVERUSE_MIN


def test_stopwords_not_flagged():
    # Repeat common stopwords many times — they must never appear in overused_words
    draft = " ".join(["the the the the the the the and and and and he he he"] * 10)
    result = analyse_prose(draft)
    overused_words = [w for w, _ in result["overused_words"]]
    for stopword in ("the", "and", "he", "a", "is"):
        assert stopword not in overused_words, (
            f"Stopword '{stopword}' should not be flagged as overused"
        )


def test_phrase_repetition_flagged():
    # Repeat "walked toward" PHRASE_OVERUSE_MIN times
    count = PHRASE_OVERUSE_MIN
    sentences = ["She walked toward the window." for _ in range(count)]
    draft = " ".join(sentences) + " Other varied prose follows here."
    result = analyse_prose(draft)
    assert any("walked toward" in issue for issue in result["issues"]), (
        f"Expected 'walked toward' phrase flagged; issues: {result['issues']}"
    )


def test_sentence_opener_dominance():
    # 5 out of 7 sentences start with "She" → ~71%, above the 30% threshold
    sentences = [
        "She entered the room quietly.",
        "She crossed to the window.",
        "She watched the street below.",
        "The rain had started again.",
        "She turned away from the glass.",
        "A candle flickered on the table.",
        "She blew it out and went to bed.",
    ]
    draft = " ".join(sentences)
    result = analyse_prose(draft)
    assert result["dominant_opener"] is not None, "Expected dominant_opener to be set"
    opener_word, frac = result["dominant_opener"]
    assert opener_word == "She"
    assert frac >= OPENER_DOMINANT_PCT
    assert any("She" in issue and "%" in issue for issue in result["issues"])


def test_adverb_density_flagged():
    # Build a passage where >3% of tokens are -ly adverbs of length ≥5
    adverbs = ["quickly", "softly", "slowly", "boldly", "deeply"] * 4
    filler = ["ran", "spoke", "moved", "turned", "walked"] * 4
    tokens = []
    for a, f in zip(adverbs, filler):
        tokens.extend([a, f, "the", "person"])
    draft = " ".join(tokens)
    result = analyse_prose(draft)
    assert result["adverb_density"] >= ADVERB_DENSITY_WARN, (
        f"adverb_density={result['adverb_density']} below threshold {ADVERB_DENSITY_WARN}"
    )
    assert any("Adverb density" in issue for issue in result["issues"])


def test_adverb_density_clean():
    # Only 1 adverb in a 100-word passage — should not trigger
    words = ["walked", "spoke", "sat", "stood", "moved", "turned", "ran", "fell"] * 12
    words.insert(10, "quickly")  # single -ly word
    draft = " ".join(words)
    result = analyse_prose(draft)
    assert result["adverb_density"] < ADVERB_DENSITY_WARN, (
        f"adverb_density={result['adverb_density']} should be below threshold"
    )
    assert not any("Adverb density" in issue for issue in result["issues"])


def test_story_overuse_detected():
    # "darkness" appears in STORY_OVERUSE_BEATS separate prior beat drafts
    current = "The darkness settled over the valley. She feared the darkness."
    prior_drafts = [
        f"Prior beat {i}: darkness filled the room and shadows moved silently."
        for i in range(STORY_OVERUSE_BEATS)
    ]
    result = analyse_prose(current, prior_drafts)
    story_words = [w for w, _ in result["story_overused"]]
    assert "darkness" in story_words, (
        f"Expected 'darkness' in story_overused; got: {result['story_overused']}"
    )
    beat_count = dict(result["story_overused"])["darkness"]
    assert beat_count >= STORY_OVERUSE_BEATS


def test_story_overuse_not_triggered_below_threshold():
    # Word in only STORY_OVERUSE_BEATS - 1 prior drafts → should NOT be flagged
    current = "The darkness settled over the valley."
    prior_drafts = [
        f"Prior beat {i}: darkness filled the room."
        for i in range(STORY_OVERUSE_BEATS - 1)
    ]
    result = analyse_prose(current, prior_drafts)
    story_words = [w for w, _ in result["story_overused"]]
    assert "darkness" not in story_words, (
        f"'darkness' should not be flagged with only {STORY_OVERUSE_BEATS - 1} prior beats"
    )


def test_format_report_empty_when_clean():
    result = analyse_prose(_varied_prose())
    # Ensure clean prose produces empty issues
    result["issues"] = []
    report = format_report(result)
    assert report == "", f"Expected empty string; got: {report!r}"


def test_format_report_has_bullets():
    result = {"issues": ["'glanced' used 9× in this beat", "50% of sentences begin with 'He'"]}
    report = format_report(result)
    assert report.startswith("Local prose analysis"), f"Expected header; got: {report!r}"
    assert "- 'glanced'" in report
    assert "- '50%" in report or "- 50%" in report


# ── Threshold override tests ───────────────────────────────────────────────────


def test_custom_word_overuse_min_stricter():
    """word_overuse_min=2 flags words that the default of 5 would not."""
    draft = "She glanced at him. He glanced back. Both glanced away."
    # Default threshold (5) would NOT flag 'glanced' (appears 3 times)
    result_default = analyse_prose(draft)
    overused_words_default = {w for w, _ in result_default["overused_words"]}
    assert "glanced" not in overused_words_default

    # Custom threshold of 2 WILL flag it
    result_strict = analyse_prose(draft, word_overuse_min=2)
    overused_words_strict = {w for w, _ in result_strict["overused_words"]}
    assert "glanced" in overused_words_strict


def test_custom_phrase_overuse_min_stricter():
    """phrase_overuse_min=2 flags phrases the default of 3 would not."""
    draft = "She walked toward the door. He walked toward the window."
    result_default = analyse_prose(draft)
    phrases_default = {p for p, _ in result_default["overused_phrases"]}
    assert "walked toward" not in phrases_default

    result_strict = analyse_prose(draft, phrase_overuse_min=2)
    phrases_strict = {p for p, _ in result_strict["overused_phrases"]}
    assert "walked toward" in phrases_strict


def test_custom_adverb_density_warn_stricter():
    """adverb_density_warn=0.001 flags even a tiny adverb density."""
    # One adverb in a 50-word passage → well below the default 3% threshold
    filler = "she walked to the market bought bread returned home sat down read the book "
    draft = (filler * 3) + "quickly"
    result_default = analyse_prose(draft)
    assert not any("Adverb density" in i for i in result_default["issues"])

    result_strict = analyse_prose(draft, adverb_density_warn=0.001)
    assert any("Adverb density" in i for i in result_strict["issues"])


def test_custom_story_overuse_beats_stricter():
    """story_overuse_beats=1 flags a word appearing in just one prior beat."""
    current = "The darkness settled over the valley."
    prior = ["darkness filled the room."]  # only 1 prior draft

    result_default = analyse_prose(current, prior)
    story_words_default = {w for w, _ in result_default["story_overused"]}
    assert "darkness" not in story_words_default  # default requires 3 beats

    result_strict = analyse_prose(current, prior, story_overuse_beats=1)
    story_words_strict = {w for w, _ in result_strict["story_overused"]}
    assert "darkness" in story_words_strict


def test_settings_prose_fields_are_accessible():
    """Settings has all five prose_* fields with correct default values."""
    from quillan.config import Settings
    s = Settings()
    assert s.prose_word_overuse_min == WORD_OVERUSE_MIN
    assert s.prose_phrase_overuse_min == PHRASE_OVERUSE_MIN
    assert abs(s.prose_opener_dominant_pct - OPENER_DOMINANT_PCT) < 1e-9
    assert abs(s.prose_adverb_density_warn - ADVERB_DENSITY_WARN) < 1e-9
    assert s.prose_story_overuse_beats == STORY_OVERUSE_BEATS
