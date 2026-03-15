"""Tests for F2 — Style Reference System (Phase 1 + Phase 2).

Covers:
  - quillan/draft/bundle.py:_build_style_reference()
  - quillan/cli.py add-sample command
  - quillan/structure/style.py:extract_style_profile()
  - add-sample --extract-profile flag
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner


# ── _build_style_reference ────────────────────────────────────────────────────

def test_no_samples_file_returns_empty(paths, world, canon, series, story):
    """When samples.md doesn't exist, returns empty string."""
    from quillan.draft.bundle import _build_style_reference

    result = _build_style_reference(paths, world, canon, series, story)
    assert result == ""


def test_empty_samples_file_returns_empty(paths, world, canon, series, story):
    """When samples.md exists but is empty, returns empty string."""
    from quillan.draft.bundle import _build_style_reference

    samples = paths.style_samples(world, canon, series, story)
    paths.ensure(samples)
    samples.write_text("", encoding="utf-8")

    result = _build_style_reference(paths, world, canon, series, story)
    assert result == ""


def test_whitespace_only_samples_returns_empty(paths, world, canon, series, story):
    """Whitespace-only samples.md is treated as empty."""
    from quillan.draft.bundle import _build_style_reference

    samples = paths.style_samples(world, canon, series, story)
    paths.ensure(samples)
    samples.write_text("   \n\n  ", encoding="utf-8")

    result = _build_style_reference(paths, world, canon, series, story)
    assert result == ""


def test_samples_file_returns_section_header(paths, world, canon, series, story):
    """Non-empty samples.md returns a section with the expected header."""
    from quillan.draft.bundle import _build_style_reference

    samples = paths.style_samples(world, canon, series, story)
    paths.ensure(samples)
    samples.write_text("The rain fell in grey curtains.", encoding="utf-8")

    result = _build_style_reference(paths, world, canon, series, story)
    assert result.startswith("# Style Reference")


def test_samples_content_included(paths, world, canon, series, story):
    """Sample text is included in the section."""
    from quillan.draft.bundle import _build_style_reference

    prose = "She walked through fog, heels tapping cobblestones."
    samples = paths.style_samples(world, canon, series, story)
    paths.ensure(samples)
    samples.write_text(prose, encoding="utf-8")

    result = _build_style_reference(paths, world, canon, series, story)
    assert prose in result


def test_samples_truncated_when_too_long(paths, world, canon, series, story):
    """Samples exceeding _STYLE_REF_MAX_CHARS are truncated."""
    from quillan.draft.bundle import _build_style_reference, _STYLE_REF_MAX_CHARS

    long_text = "A" * (_STYLE_REF_MAX_CHARS + 500)
    samples = paths.style_samples(world, canon, series, story)
    paths.ensure(samples)
    samples.write_text(long_text, encoding="utf-8")

    result = _build_style_reference(paths, world, canon, series, story)
    assert "...(truncated)" in result
    # Whole section should not balloon far past the cap
    assert len(result) < _STYLE_REF_MAX_CHARS + 300


def test_short_samples_not_truncated(paths, world, canon, series, story):
    """Short samples are returned without truncation marker."""
    from quillan.draft.bundle import _build_style_reference

    samples = paths.style_samples(world, canon, series, story)
    paths.ensure(samples)
    samples.write_text("Short sample.", encoding="utf-8")

    result = _build_style_reference(paths, world, canon, series, story)
    assert "...(truncated)" not in result


# ── add-sample CLI command ────────────────────────────────────────────────────

def _make_story(paths, world, canon, series, story):
    """Helper: create a minimal story directory."""
    story_dir = paths.story(world, canon, series, story)
    story_dir.mkdir(parents=True, exist_ok=True)
    return story_dir


def test_add_sample_inline_text(tmp_path):
    """add-sample with literal text writes to samples.md."""
    from quillan.cli import main
    from quillan.paths import Paths

    p = Paths(tmp_path)
    _make_story(p, "w", "c", "s", "mystory")

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--data-dir", str(tmp_path), "--world", "w", "--canon", "c",
         "--series", "s", "add-sample", "mystory", "The fog was thick."],
    )

    assert result.exit_code == 0, result.output
    samples = p.style_samples("w", "c", "s", "mystory")
    assert samples.exists()
    assert "The fog was thick." in samples.read_text()


def test_add_sample_from_file(tmp_path):
    """add-sample with a file path reads from disk."""
    from quillan.cli import main
    from quillan.paths import Paths

    p = Paths(tmp_path)
    _make_story(p, "w", "c", "s", "mystory")

    sample_file = tmp_path / "sample.txt"
    sample_file.write_text("Prose from a file.", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--data-dir", str(tmp_path), "--world", "w", "--canon", "c",
         "--series", "s", "add-sample", "mystory", str(sample_file)],
    )

    assert result.exit_code == 0, result.output
    samples = p.style_samples("w", "c", "s", "mystory")
    assert "Prose from a file." in samples.read_text()


def test_add_sample_appends_with_separator(tmp_path):
    """Calling add-sample twice separates entries with '---'."""
    from quillan.cli import main
    from quillan.paths import Paths

    p = Paths(tmp_path)
    _make_story(p, "w", "c", "s", "mystory")

    runner = CliRunner()
    runner.invoke(
        main,
        ["--data-dir", str(tmp_path), "--world", "w", "--canon", "c",
         "--series", "s", "add-sample", "mystory", "First sample."],
    )
    runner.invoke(
        main,
        ["--data-dir", str(tmp_path), "--world", "w", "--canon", "c",
         "--series", "s", "add-sample", "mystory", "Second sample."],
    )

    content = p.style_samples("w", "c", "s", "mystory").read_text()
    assert "First sample." in content
    assert "Second sample." in content
    assert "---" in content


def test_add_sample_unknown_story_exits_1(tmp_path):
    """add-sample fails with exit code 1 when story directory doesn't exist."""
    from quillan.cli import main

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--data-dir", str(tmp_path), "--world", "w", "--canon", "c",
         "--series", "s", "add-sample", "no_such_story", "Some text."],
    )

    assert result.exit_code == 1


def test_add_sample_empty_text_exits_1(tmp_path):
    """add-sample rejects empty text."""
    from quillan.cli import main
    from quillan.paths import Paths

    p = Paths(tmp_path)
    _make_story(p, "w", "c", "s", "mystory")

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--data-dir", str(tmp_path), "--world", "w", "--canon", "c",
         "--series", "s", "add-sample", "mystory", "   "],
    )

    assert result.exit_code == 1


def test_add_sample_output_shows_word_count(tmp_path):
    """add-sample prints a confirmation with word count."""
    from quillan.cli import main
    from quillan.paths import Paths

    p = Paths(tmp_path)
    _make_story(p, "w", "c", "s", "mystory")

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--data-dir", str(tmp_path), "--world", "w", "--canon", "c",
         "--series", "s", "add-sample", "mystory", "One two three."],
    )

    assert result.exit_code == 0
    assert "3 words" in result.output


# ── Integration: bundle includes style reference ──────────────────────────────

@pytest.mark.asyncio
async def test_bundle_includes_style_reference_section(paths, world, canon, series, story, settings):
    """When samples.md exists, the assembled bundle contains the Style Reference section."""
    import yaml
    from quillan.draft.bundle import assemble_bundle

    # Minimal story structure required by assemble_bundle
    spec_path = paths.beat_spec(world, canon, series, story, "C1-S1-B1")
    paths.ensure(spec_path)
    spec_path.write_text(
        yaml.dump({"beat_id": "C1-S1-B1", "goal": "Open the story",
                   "word_count_target": 800}),
        encoding="utf-8",
    )

    # Add a style sample
    samples = paths.style_samples(world, canon, series, story)
    paths.ensure(samples)
    samples.write_text("Atmospheric noir prose sample.", encoding="utf-8")

    bundle_path = await assemble_bundle(
        paths, world, canon, series, story, "C1-S1-B1", settings
    )
    content = bundle_path.read_text(encoding="utf-8")
    assert "# Style Reference" in content
    assert "Atmospheric noir prose sample." in content


# ── Phase 2: extract_style_profile ───────────────────────────────────────────

class _FakeLLM:
    """Minimal LLM stub: call_json returns a canned style profile dict."""

    def __init__(self, response: dict):
        self._response = response

    async def call_json(self, stage, system, user, required_keys=None):
        return self._response


_SAMPLE_PROFILE = {
    "pov": "tight third-person limited",
    "tense": "past",
    "sentence_rhythm": "short declarative sentences; occasional fragments for emphasis",
    "voice": "sardonic and world-weary",
    "distinctive_features": ["heavy weather imagery", "sparse dialogue"],
    "avoid": ["adverbs ending in -ly", "exclamation marks"],
}


@pytest.mark.asyncio
async def test_extract_style_profile_writes_yaml(paths, world, canon, series, story, settings):
    """extract_style_profile writes style_profile.yaml from LLM response."""
    import yaml
    from quillan.structure.style import extract_style_profile

    samples = paths.style_samples(world, canon, series, story)
    paths.ensure(samples)
    samples.write_text("The rain fell in grey curtains.", encoding="utf-8")

    llm = _FakeLLM(_SAMPLE_PROFILE)
    result = await extract_style_profile(paths, world, canon, series, story, llm, settings)

    assert result is not None
    profile_path = paths.style_profile(world, canon, series, story)
    assert profile_path.exists()
    data = yaml.safe_load(profile_path.read_text())
    assert data["pov"] == "tight third-person limited"
    assert data["tense"] == "past"
    assert isinstance(data["distinctive_features"], list)


@pytest.mark.asyncio
async def test_extract_style_profile_no_samples_returns_none(paths, world, canon, series, story, settings):
    """extract_style_profile returns None when samples.md does not exist."""
    from quillan.structure.style import extract_style_profile

    llm = _FakeLLM(_SAMPLE_PROFILE)
    result = await extract_style_profile(paths, world, canon, series, story, llm, settings)
    assert result is None


@pytest.mark.asyncio
async def test_extract_style_profile_empty_samples_returns_none(paths, world, canon, series, story, settings):
    """extract_style_profile returns None when samples.md is empty."""
    from quillan.structure.style import extract_style_profile

    samples = paths.style_samples(world, canon, series, story)
    paths.ensure(samples)
    samples.write_text("", encoding="utf-8")

    llm = _FakeLLM(_SAMPLE_PROFILE)
    result = await extract_style_profile(paths, world, canon, series, story, llm, settings)
    assert result is None


@pytest.mark.asyncio
async def test_extract_style_profile_llm_error_returns_none(paths, world, canon, series, story, settings):
    """extract_style_profile returns None when LLM call raises LLMError."""
    from quillan.structure.style import extract_style_profile
    from quillan.llm import LLMError

    class _ErrorLLM:
        async def call_json(self, *args, **kwargs):
            raise LLMError("offline")

    samples = paths.style_samples(world, canon, series, story)
    paths.ensure(samples)
    samples.write_text("Some prose.", encoding="utf-8")

    result = await extract_style_profile(paths, world, canon, series, story, _ErrorLLM(), settings)
    assert result is None


# ── _build_style_reference: profile + samples together ───────────────────────

def test_build_style_reference_shows_fingerprint_section(paths, world, canon, series, story):
    """When style_profile.yaml exists, output contains 'Style Fingerprint'."""
    import yaml
    from quillan.draft.bundle import _build_style_reference

    profile = paths.style_profile(world, canon, series, story)
    paths.ensure(profile)
    profile.write_text(yaml.dump(_SAMPLE_PROFILE), encoding="utf-8")

    result = _build_style_reference(paths, world, canon, series, story)
    assert "## Style Fingerprint" in result
    assert "tight third-person limited" in result


def test_build_style_reference_profile_without_samples(paths, world, canon, series, story):
    """Style Fingerprint alone (no samples.md) still produces a section."""
    import yaml
    from quillan.draft.bundle import _build_style_reference

    profile = paths.style_profile(world, canon, series, story)
    paths.ensure(profile)
    profile.write_text(yaml.dump(_SAMPLE_PROFILE), encoding="utf-8")

    result = _build_style_reference(paths, world, canon, series, story)
    assert "# Style Reference" in result
    assert "## Style Fingerprint" in result
    assert "## Style Samples" not in result


def test_build_style_reference_samples_subsection_label(paths, world, canon, series, story):
    """When both profile and samples exist, 'Style Samples' subsection appears."""
    import yaml
    from quillan.draft.bundle import _build_style_reference

    profile = paths.style_profile(world, canon, series, story)
    paths.ensure(profile)
    profile.write_text(yaml.dump(_SAMPLE_PROFILE), encoding="utf-8")

    samples = paths.style_samples(world, canon, series, story)
    paths.ensure(samples)
    samples.write_text("Raw prose excerpt.", encoding="utf-8")

    result = _build_style_reference(paths, world, canon, series, story)
    assert "## Style Fingerprint" in result
    assert "## Style Samples" in result
    assert "Raw prose excerpt." in result


# ── add-sample --extract-profile CLI flag ─────────────────────────────────────

def test_add_sample_no_extract_profile_by_default(tmp_path):
    """add-sample without --extract-profile does not create style_profile.yaml."""
    from quillan.cli import main
    from quillan.paths import Paths

    p = Paths(tmp_path)
    _make_story(p, "w", "c", "s", "mystory")

    runner = CliRunner()
    runner.invoke(
        main,
        ["--data-dir", str(tmp_path), "--world", "w", "--canon", "c",
         "--series", "s", "add-sample", "mystory", "Some prose."],
    )

    assert not p.style_profile("w", "c", "s", "mystory").exists()


def test_add_sample_extract_profile_no_keys_warns(tmp_path):
    """add-sample --extract-profile without API keys prints a warning."""
    from quillan.cli import main
    from quillan.paths import Paths

    p = Paths(tmp_path)
    _make_story(p, "w", "c", "s", "mystory")

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--data-dir", str(tmp_path), "--world", "w", "--canon", "c",
         "--series", "s", "add-sample", "mystory", "Some prose.", "--extract-profile"],
        catch_exceptions=False,
    )

    # Should succeed (exit 0) but emit a warning about missing keys
    assert result.exit_code == 0
    assert "API keys" in result.output or "doctor" in result.output
