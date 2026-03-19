"""Tests for per-world / per-story quillan.yaml settings overrides."""

from __future__ import annotations

from pathlib import Path


from quillan.config import Settings, load_story_settings
from quillan.paths import Paths


# ── Helpers ───────────────────────────────────────────────────────────────────


def _paths(tmp_path: Path) -> Paths:
    return Paths(tmp_path)


def _base(tmp_path: Path) -> Settings:
    return Settings(_env_file=(), data_dir=tmp_path, llm_cache=False, telemetry=False)


# ── No override files — returns base unchanged ────────────────────────────────


def test_no_override_files_returns_base(tmp_path):
    paths = _paths(tmp_path)
    base = _base(tmp_path)
    result = load_story_settings(paths, "w", "c", "s", "st", base=base)
    assert result is base, "Should return the same object when no override files exist"


# ── World-level override ───────────────────────────────────────────────────────


def test_world_override_applied(tmp_path):
    paths = _paths(tmp_path)
    base = _base(tmp_path)
    assert base.max_parallel == 3  # default

    world_yaml = paths.world_settings("w")
    world_yaml.parent.mkdir(parents=True, exist_ok=True)
    world_yaml.write_text("max_parallel: 7\n", encoding="utf-8")

    result = load_story_settings(paths, "w", "c", "s", "st", base=base)
    assert result.max_parallel == 7


# ── Story-level override wins over world-level ────────────────────────────────


def test_story_override_wins_over_world(tmp_path):
    paths = _paths(tmp_path)
    base = _base(tmp_path)

    world_yaml = paths.world_settings("w")
    world_yaml.parent.mkdir(parents=True, exist_ok=True)
    world_yaml.write_text("max_parallel: 7\n", encoding="utf-8")

    story_yaml = paths.story_settings("w", "c", "s", "st")
    story_yaml.parent.mkdir(parents=True, exist_ok=True)
    story_yaml.write_text("max_parallel: 2\n", encoding="utf-8")

    result = load_story_settings(paths, "w", "c", "s", "st", base=base)
    assert result.max_parallel == 2


# ── Multiple fields in one file ───────────────────────────────────────────────


def test_multiple_fields_overridden(tmp_path):
    paths = _paths(tmp_path)
    base = _base(tmp_path)

    story_yaml = paths.story_settings("w", "c", "s", "st")
    story_yaml.parent.mkdir(parents=True, exist_ok=True)
    story_yaml.write_text(
        "max_parallel: 1\n"
        "draft_audit_retries: 3\n"
        "prose_word_overuse_min: 8\n",
        encoding="utf-8",
    )

    result = load_story_settings(paths, "w", "c", "s", "st", base=base)
    assert result.max_parallel == 1
    assert result.draft_audit_retries == 3
    assert result.prose_word_overuse_min == 8


# ── API keys cannot be overridden ────────────────────────────────────────────


def test_api_keys_cannot_be_overridden(tmp_path):
    paths = _paths(tmp_path)
    base = _base(tmp_path)
    original_key = base.openai_api_key  # likely "" in test env

    story_yaml = paths.story_settings("w", "c", "s", "st")
    story_yaml.parent.mkdir(parents=True, exist_ok=True)
    story_yaml.write_text(
        "openai_api_key: STOLEN_KEY\n"
        "xai_api_key: STOLEN_XAI\n"
        "gemini_api_key: STOLEN_GEMINI\n"
        "max_parallel: 5\n",
        encoding="utf-8",
    )

    result = load_story_settings(paths, "w", "c", "s", "st", base=base)
    # Override for a non-blocked field was applied
    assert result.max_parallel == 5
    # API keys were NOT changed
    assert result.openai_api_key == original_key
    assert result.xai_api_key == base.xai_api_key
    assert result.gemini_api_key == base.gemini_api_key


# ── Malformed YAML is silently skipped ───────────────────────────────────────


def test_malformed_world_yaml_skipped(tmp_path):
    paths = _paths(tmp_path)
    base = _base(tmp_path)

    world_yaml = paths.world_settings("w")
    world_yaml.parent.mkdir(parents=True, exist_ok=True)
    world_yaml.write_text(": invalid: yaml: {{{\n", encoding="utf-8")

    # Should not raise; returns base unchanged
    result = load_story_settings(paths, "w", "c", "s", "st", base=base)
    assert result.max_parallel == base.max_parallel


def test_malformed_story_yaml_skipped(tmp_path):
    paths = _paths(tmp_path)
    base = _base(tmp_path)

    # Valid world override — should still apply
    world_yaml = paths.world_settings("w")
    world_yaml.parent.mkdir(parents=True, exist_ok=True)
    world_yaml.write_text("max_parallel: 9\n", encoding="utf-8")

    story_yaml = paths.story_settings("w", "c", "s", "st")
    story_yaml.parent.mkdir(parents=True, exist_ok=True)
    story_yaml.write_text(": not valid yaml\n", encoding="utf-8")

    result = load_story_settings(paths, "w", "c", "s", "st", base=base)
    # Malformed story yaml skipped, world override still applies
    assert result.max_parallel == 9


# ── Non-dict YAML root is rejected gracefully ─────────────────────────────────


def test_non_dict_yaml_root_skipped(tmp_path):
    paths = _paths(tmp_path)
    base = _base(tmp_path)

    world_yaml = paths.world_settings("w")
    world_yaml.parent.mkdir(parents=True, exist_ok=True)
    world_yaml.write_text("- item1\n- item2\n", encoding="utf-8")  # a YAML list, not a dict

    result = load_story_settings(paths, "w", "c", "s", "st", base=base)
    assert result is base


# ── Empty story name skips story-level file ───────────────────────────────────


def test_empty_story_skips_story_file(tmp_path):
    paths = _paths(tmp_path)
    base = _base(tmp_path)

    # Put a world override
    world_yaml = paths.world_settings("myworld")
    world_yaml.parent.mkdir(parents=True, exist_ok=True)
    world_yaml.write_text("max_parallel: 6\n", encoding="utf-8")

    # story="" → only world override loaded
    result = load_story_settings(paths, "myworld", "c", "s", story="", base=base)
    assert result.max_parallel == 6


# ── default base is created when not passed ──────────────────────────────────


def test_default_base_created_when_none(tmp_path):
    paths = _paths(tmp_path)
    # No override files — should return a fresh Settings() without error
    result = load_story_settings(paths, "w", "c", "s", "st")
    assert isinstance(result, Settings)


# ── Paths methods return expected paths ──────────────────────────────────────


def test_paths_world_settings(tmp_path):
    paths = _paths(tmp_path)
    p = paths.world_settings("myworld")
    assert p == tmp_path / "worlds" / "myworld" / "quillan.yaml"


def test_paths_story_settings(tmp_path):
    paths = _paths(tmp_path)
    p = paths.story_settings("w", "c", "s", "st")
    assert p == tmp_path / "worlds" / "w" / "canons" / "c" / "series" / "s" / "stories" / "st" / "quillan.yaml"
