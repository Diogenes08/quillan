"""Tests for the prompt template loader (quillan/templates.py)."""

from __future__ import annotations

import pytest


# ── Built-in template loading ──────────────────────────────────────────────────

def test_get_prompt_returns_string():
    from quillan.templates import get_prompt
    result = get_prompt("draft_system")
    assert isinstance(result, str)
    assert len(result) > 0


def test_get_prompt_draft_system_content():
    """Built-in draft_system prompt contains expected key phrase."""
    from quillan.templates import get_prompt
    content = get_prompt("draft_system")
    assert "fiction writer" in content


def test_get_prompt_draft_user_has_format_vars():
    """draft_user template contains {context} and {word_count} placeholders."""
    from quillan.templates import get_prompt
    tmpl = get_prompt("draft_user")
    assert "{context}" in tmpl
    assert "{word_count}" in tmpl


def test_get_prompt_audit_user_json_structure():
    """audit_user template contains the expected JSON field names."""
    from quillan.templates import get_prompt
    tmpl = get_prompt("audit_user")
    assert "overall_pass" in tmpl
    assert "fix_list" in tmpl


def test_get_prompt_unknown_name_raises():
    from quillan.templates import get_prompt
    with pytest.raises(FileNotFoundError):
        get_prompt("this_template_does_not_exist")


def test_all_builtin_templates_loadable():
    """Every .txt file in quillan/templates/ can be loaded without error."""
    from quillan.templates import get_prompt, _BUILTIN_DIR
    templates = list(_BUILTIN_DIR.glob("*.txt"))
    assert len(templates) >= 40, "Expected at least 40 built-in templates"
    for t in templates:
        content = get_prompt(t.stem)
        assert isinstance(content, str) and len(content) > 0, f"{t.stem} is empty"


# ── Override chain ─────────────────────────────────────────────────────────────

def test_story_dir_override_takes_priority(tmp_path):
    """A template file in story_dir/templates/ overrides the built-in."""
    from quillan.templates import get_prompt

    story_dir = tmp_path / "story"
    tmpl_dir = story_dir / "templates"
    tmpl_dir.mkdir(parents=True)
    (tmpl_dir / "draft_system.txt").write_text("Custom story-level system prompt")

    result = get_prompt("draft_system", story_dir=story_dir)
    assert result == "Custom story-level system prompt"


def test_world_dir_override_used_when_no_story_override(tmp_path):
    """A world_dir template is used when no story-level override exists."""
    from quillan.templates import get_prompt

    world_dir = tmp_path / "world"
    (world_dir / "templates").mkdir(parents=True)
    (world_dir / "templates" / "draft_user.txt").write_text("World-level draft prompt {context} {word_count}")

    result = get_prompt("draft_user", story_dir=tmp_path / "story", world_dir=world_dir)
    assert result == "World-level draft prompt {context} {word_count}"


def test_story_dir_beats_world_dir(tmp_path):
    """story_dir template wins over world_dir template."""
    from quillan.templates import get_prompt

    story_dir = tmp_path / "story"
    (story_dir / "templates").mkdir(parents=True)
    (story_dir / "templates" / "draft_system.txt").write_text("Story wins")

    world_dir = tmp_path / "world"
    (world_dir / "templates").mkdir(parents=True)
    (world_dir / "templates" / "draft_system.txt").write_text("World wins")

    result = get_prompt("draft_system", story_dir=story_dir, world_dir=world_dir)
    assert result == "Story wins"


def test_builtin_fallback_when_no_overrides(tmp_path):
    """When override dirs exist but have no matching file, built-in is used."""
    from quillan.templates import get_prompt

    story_dir = tmp_path / "story"
    story_dir.mkdir()  # no templates/ subdir

    builtin = get_prompt("draft_system")
    result = get_prompt("draft_system", story_dir=story_dir)
    assert result == builtin


def test_override_template_format_compatible(tmp_path):
    """Override templates support .format() just like built-ins."""
    from quillan.templates import get_prompt

    story_dir = tmp_path / "story"
    (story_dir / "templates").mkdir(parents=True)
    (story_dir / "templates" / "draft_user.txt").write_text(
        "Write {word_count} words about: {context}"
    )

    result = get_prompt("draft_user", story_dir=story_dir).format(
        word_count=500, context="a dragon"
    )
    assert result == "Write 500 words about: a dragon"
