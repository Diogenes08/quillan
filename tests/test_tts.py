"""Tests for quillan.tts — pure functions + provider abstraction (no API calls)."""

from __future__ import annotations

import pytest

from quillan.tts import (
    _ElevenLabsTTS,
    _OpenAITTS,
    get_tts_provider,
    split_into_tts_chunks,
)

_MAX = 4096


def test_empty_input():
    assert split_into_tts_chunks("") == []


def test_whitespace_only():
    assert split_into_tts_chunks("   \n\t  ") == []


def test_short_text_returned_as_single_chunk():
    text = "Hello world."
    result = split_into_tts_chunks(text)
    assert result == ["Hello world."]


def test_text_exactly_at_limit():
    text = "A" * _MAX
    result = split_into_tts_chunks(text)
    assert result == [text]


def test_text_one_over_limit_splits():
    # Two sentences, each under _MAX, combined just over
    sentence_a = "A" * (_MAX - 10) + "."
    sentence_b = "B" * 20 + "."
    combined = sentence_a + "  " + sentence_b
    result = split_into_tts_chunks(combined, max_chars=_MAX)
    assert len(result) == 2
    assert sentence_a in result[0]
    assert "B" in result[1]


def test_sentence_boundary_splitting():
    sentence = "The quick brown fox. "
    # Repeat until we exceed _MAX
    text = sentence * 300
    result = split_into_tts_chunks(text, max_chars=_MAX)
    assert len(result) > 1
    for chunk in result:
        assert len(chunk) <= _MAX


def test_long_sentence_fallback_word_boundary():
    # A single sentence that exceeds max_chars — must fall back to word splitting
    words = ["word"] * 2000
    long_sentence = " ".join(words)
    assert len(long_sentence) > _MAX
    result = split_into_tts_chunks(long_sentence, max_chars=_MAX)
    assert len(result) > 1
    for chunk in result:
        assert len(chunk) <= _MAX


def test_chunks_cover_all_content():
    sentences = [f"Sentence number {i} ends here." for i in range(200)]
    text = " ".join(sentences)
    result = split_into_tts_chunks(text, max_chars=200)
    reassembled = " ".join(result)
    # All content should be present (whitespace may be normalised)
    for i in range(200):
        assert f"number {i}" in reassembled


def test_custom_max_chars():
    text = "Hello world. Goodbye world."
    result = split_into_tts_chunks(text, max_chars=15)
    for chunk in result:
        assert len(chunk) <= 15


# ── Provider factory ──────────────────────────────────────────────────────────

def _mock_settings(**kwargs):
    """Return a minimal Settings-like namespace for provider tests."""
    from types import SimpleNamespace
    defaults = {
        "tts_provider": "openai",
        "tts_model": "tts-1",
        "tts_voice": "alloy",
        "openai_api_key": "",
        "elevenlabs_api_key": "",
        "elevenlabs_voice_id": "21m00Tcm4TlvDq8ikWAM",
        "elevenlabs_model": "eleven_monolingual_v1",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_get_tts_provider_default_is_openai():
    s = _mock_settings()
    p = get_tts_provider(s)
    assert isinstance(p, _OpenAITTS)


def test_get_tts_provider_elevenlabs():
    s = _mock_settings(tts_provider="elevenlabs")
    p = get_tts_provider(s)
    assert isinstance(p, _ElevenLabsTTS)


def test_get_tts_provider_case_insensitive():
    s = _mock_settings(tts_provider="ElevenLabs")
    p = get_tts_provider(s)
    assert isinstance(p, _ElevenLabsTTS)


def test_openai_check_credentials_raises_without_key():
    s = _mock_settings(openai_api_key="")
    p = _OpenAITTS(s)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        p.check_credentials()


def test_openai_check_credentials_passes_with_key():
    s = _mock_settings(openai_api_key="sk-test")
    p = _OpenAITTS(s)
    p.check_credentials()  # should not raise


def test_elevenlabs_check_credentials_raises_without_key():
    s = _mock_settings(elevenlabs_api_key="")
    p = _ElevenLabsTTS(s)
    with pytest.raises(RuntimeError, match="QUILLAN_ELEVENLABS_API_KEY"):
        p.check_credentials()


def test_elevenlabs_check_credentials_passes_with_key():
    s = _mock_settings(elevenlabs_api_key="el-test-key")
    p = _ElevenLabsTTS(s)
    p.check_credentials()  # should not raise


def test_synthesize_chapter_uses_provided_provider(tmp_path):
    """synthesize_chapter calls provider.synthesize_chunk, not the default."""
    import asyncio

    calls = []

    class _FakeProvider:
        async def synthesize_chunk(self, text):
            calls.append(text)
            return b"\xff\xfb\x90\x00"  # minimal valid MP3 header bytes

    from quillan.tts import synthesize_chapter

    chapter_text = "Short sentence."
    asyncio.run(
        synthesize_chapter(1, "Ch 1", chapter_text, tmp_path / "chunks",
                           _mock_settings(), provider=_FakeProvider())
    )
    assert len(calls) == 1
    assert calls[0] == chapter_text
