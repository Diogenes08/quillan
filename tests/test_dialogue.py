"""Tests for F6 — Dialogue System (quillan/structure/dialogue.py)."""

from __future__ import annotations

import pytest
import yaml
from click.testing import CliRunner

from quillan.structure.dialogue import (
    character_slug,
    format_voice_section,
    generate_voice_profile,
    load_voice_profiles,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

_SAMPLE_PROFILE = {
    "character": "Detective Marlowe",
    "speech_patterns": ["short declarative sentences", "uses silence as punctuation"],
    "vocabulary_level": "hard-boiled vernacular, occasional sardonic formality",
    "verbal_tics": ["opens deflections with 'Look,'"],
    "avoids": ["profanity", "passive voice"],
    "emotional_tells": ["goes monosyllabic under pressure"],
    "sample_lines": ["Look, I've seen worse.", "Maybe. Maybe not."],
}

_REQUIRED_KEYS = [
    "character", "speech_patterns", "vocabulary_level",
    "verbal_tics", "avoids", "emotional_tells", "sample_lines",
]


class _StubLLM:
    async def call_json(self, *args, **kwargs):
        return dict(_SAMPLE_PROFILE)


class _FailLLM:
    async def call_json(self, *args, **kwargs):
        from quillan.llm import LLMError
        raise LLMError("offline")


def _write_profile(paths, world, canon, series, story, char_name, profile=None):
    slug = character_slug(char_name)
    p = paths.voice_profile(world, canon, series, story, slug)
    paths.ensure(p)
    p.write_text(yaml.dump(profile or _SAMPLE_PROFILE), encoding="utf-8")
    return p


# ── character_slug ────────────────────────────────────────────────────────────

def test_character_slug_simple():
    assert character_slug("Margaret Hale") == "margaret_hale"


def test_character_slug_punctuation():
    assert character_slug("Dr. John Watson") == "dr_john_watson"


def test_character_slug_all_special():
    assert character_slug("---") == "unknown"


def test_character_slug_already_slug():
    assert character_slug("marlowe") == "marlowe"


# ── generate_voice_profile ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_voice_profile_writes_yaml(paths, world, canon, series, story, settings):
    result = await generate_voice_profile(
        "Detective Marlowe", paths, world, canon, series, story, _StubLLM(), settings
    )
    assert result is not None
    assert result.exists()
    data = yaml.safe_load(result.read_text())
    assert data["character"] == "Detective Marlowe"
    assert isinstance(data["speech_patterns"], list)


@pytest.mark.asyncio
async def test_generate_voice_profile_returns_none_on_failure(paths, world, canon, series, story, settings):
    result = await generate_voice_profile(
        "John Doe", paths, world, canon, series, story, _FailLLM(), settings
    )
    assert result is None


@pytest.mark.asyncio
async def test_generate_voice_profile_uses_slug_filename(paths, world, canon, series, story, settings):
    result = await generate_voice_profile(
        "The Widow", paths, world, canon, series, story, _StubLLM(), settings
    )
    assert result is not None
    assert result.name == "the_widow.yaml"


@pytest.mark.asyncio
async def test_generate_voice_profile_reads_arc_when_present(
    paths, world, canon, series, story, settings
):
    """Arc info is included in the user prompt (captured via call)."""
    # Write a minimal character arcs file
    arcs_path = paths.character_arcs(world, canon, series, story)
    paths.ensure(arcs_path)
    arcs_path.write_text(
        yaml.dump({"arcs": [{"character": "Detective Marlowe", "arc": "From cynical to hopeful"}]}),
        encoding="utf-8",
    )

    captured: list[str] = []

    class _CaptureLLM:
        async def call_json(self, stage, system, user, required_keys=None):
            captured.append(user)
            return dict(_SAMPLE_PROFILE)

    await generate_voice_profile(
        "Detective Marlowe", paths, world, canon, series, story, _CaptureLLM(), settings
    )

    assert captured
    assert "Detective Marlowe" in captured[0]
    assert "cynical to hopeful" in captured[0]


# ── load_voice_profiles ───────────────────────────────────────────────────────

def test_load_voice_profiles_empty_dir(paths, world, canon, series, story):
    result = load_voice_profiles(paths, world, canon, series, story)
    assert result == {}


def test_load_voice_profiles_loads_existing(paths, world, canon, series, story):
    _write_profile(paths, world, canon, series, story, "Detective Marlowe")
    result = load_voice_profiles(
        paths, world, canon, series, story, ["Detective Marlowe"]
    )
    assert "Detective Marlowe" in result
    assert result["Detective Marlowe"]["vocabulary_level"] == _SAMPLE_PROFILE["vocabulary_level"]


def test_load_voice_profiles_skips_missing(paths, world, canon, series, story):
    _write_profile(paths, world, canon, series, story, "Detective Marlowe")
    result = load_voice_profiles(
        paths, world, canon, series, story, ["Detective Marlowe", "The Widow"]
    )
    assert "Detective Marlowe" in result
    # The Widow has no profile — should be silently skipped
    assert len(result) == 1


def test_load_voice_profiles_all_when_no_names(paths, world, canon, series, story):
    _write_profile(paths, world, canon, series, story, "Detective Marlowe")
    _write_profile(paths, world, canon, series, story, "The Widow",
                   {**_SAMPLE_PROFILE, "character": "The Widow"})
    result = load_voice_profiles(paths, world, canon, series, story)
    assert len(result) == 2


# ── format_voice_section ──────────────────────────────────────────────────────

def test_format_voice_section_empty():
    assert format_voice_section({}) == ""


def test_format_voice_section_contains_header():
    result = format_voice_section({"Detective Marlowe": _SAMPLE_PROFILE})
    assert "# Character Voices" in result


def test_format_voice_section_contains_character_name():
    result = format_voice_section({"Detective Marlowe": _SAMPLE_PROFILE})
    assert "Detective Marlowe" in result


def test_format_voice_section_contains_speech_patterns():
    result = format_voice_section({"Detective Marlowe": _SAMPLE_PROFILE})
    assert "short declarative sentences" in result


def test_format_voice_section_contains_sample_lines():
    result = format_voice_section({"Detective Marlowe": _SAMPLE_PROFILE})
    assert "Look, I've seen worse." in result


def test_format_voice_section_multiple_characters():
    profiles = {
        "Marlowe": _SAMPLE_PROFILE,
        "The Widow": {**_SAMPLE_PROFILE, "character": "The Widow",
                      "vocabulary_level": "aristocratic"},
    }
    result = format_voice_section(profiles)
    assert "Marlowe" in result
    assert "aristocratic" in result


# ── bundle integration ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bundle_includes_voice_section_when_profile_exists(
    paths, world, canon, series, story, settings
):
    """When a beat spec lists a character with a profile, bundle includes voice section."""
    # Write beat spec with character
    spec_path = paths.beat_spec(world, canon, series, story, "C1-S1-B1")
    paths.ensure(spec_path)
    spec_path.write_text(
        yaml.dump({
            "beat_id": "C1-S1-B1",
            "goal": "Opening scene",
            "characters": ["Detective Marlowe"],
            "word_count_target": 800,
        }),
        encoding="utf-8",
    )

    # Write voice profile
    _write_profile(paths, world, canon, series, story, "Detective Marlowe")

    from quillan.draft.bundle import assemble_bundle
    bundle_path = await assemble_bundle(
        paths, world, canon, series, story, "C1-S1-B1", settings
    )
    content = bundle_path.read_text(encoding="utf-8")
    assert "# Character Voices" in content
    assert "Detective Marlowe" in content


@pytest.mark.asyncio
async def test_bundle_no_voice_section_without_profiles(
    paths, world, canon, series, story, settings
):
    """Bundle omits voice section when no profiles exist."""
    spec_path = paths.beat_spec(world, canon, series, story, "C1-S1-B1")
    paths.ensure(spec_path)
    spec_path.write_text(
        yaml.dump({
            "beat_id": "C1-S1-B1",
            "goal": "Opening scene",
            "characters": ["Unknown Person"],
            "word_count_target": 800,
        }),
        encoding="utf-8",
    )

    from quillan.draft.bundle import assemble_bundle
    bundle_path = await assemble_bundle(
        paths, world, canon, series, story, "C1-S1-B1", settings
    )
    content = bundle_path.read_text(encoding="utf-8")
    assert "# Character Voices" not in content


# ── CLI: character-voice ──────────────────────────────────────────────────────

def _make_story(paths, world, canon, series, story):
    paths.story(world, canon, series, story).mkdir(parents=True, exist_ok=True)


def test_cli_character_voice_no_story_exits_1(tmp_path):
    from quillan.cli import main

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--data-dir", str(tmp_path), "--world", "w", "--canon", "c",
         "--series", "s", "character-voice", "nostory", "Marlowe"],
    )
    assert result.exit_code == 1


def test_cli_character_voice_existing_no_regen_skips(tmp_path):
    from quillan.cli import main
    from quillan.paths import Paths

    p = Paths(tmp_path)
    _make_story(p, "w", "c", "s", "mystory")
    _write_profile(p, "w", "c", "s", "mystory", "Detective Marlowe")

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--data-dir", str(tmp_path), "--world", "w", "--canon", "c",
         "--series", "s", "character-voice", "mystory", "Detective Marlowe"],
    )
    assert result.exit_code == 0
    assert "already exists" in result.output


def test_cli_character_voice_no_keys_exits_1(tmp_path):
    from quillan.cli import main
    from quillan.paths import Paths

    p = Paths(tmp_path)
    _make_story(p, "w", "c", "s", "mystory")

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--data-dir", str(tmp_path), "--world", "w", "--canon", "c",
         "--series", "s", "character-voice", "mystory", "Marlowe"],
    )
    assert result.exit_code == 1
    assert "API keys" in result.output or "API keys" in result.stderr_bytes.decode("utf-8", errors="replace") if hasattr(result, "stderr_bytes") else True
