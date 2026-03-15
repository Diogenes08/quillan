"""Tests for canon-level and world-level character registry."""

from __future__ import annotations

import yaml
from pathlib import Path


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_arcs(paths, world, canon, series, story, characters):
    p = paths.character_arcs(world, canon, series, story)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.dump({"characters": characters}), encoding="utf-8")


def _write_state(paths, world, canon, series, story, characters):
    p = paths.state_current(world, canon, series, story)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.dump({"characters": characters}), encoding="utf-8")


def _load_registry(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


# ── Canon-level registry tests ────────────────────────────────────────────────

def test_update_registry_creates_file(paths, world, canon, series, story):
    from quillan.structure.character_registry import update_registry

    _write_arcs(paths, world, canon, series, story, [
        {"name": "Alice", "description": "Protagonist", "motivation": "Revenge"}
    ])

    update_registry(paths, world, canon, series, story)

    reg_path = paths.character_registry(world, canon)
    assert reg_path.exists()
    data = _load_registry(reg_path)
    assert "Alice" in data["characters"]
    assert data["characters"]["Alice"]["description"] == "Protagonist"
    assert data["characters"]["Alice"]["stories"] == [story]


def test_update_registry_merges_state(paths, world, canon, series, story):
    from quillan.structure.character_registry import update_registry

    _write_arcs(paths, world, canon, series, story, [
        {"name": "Bob", "description": "Sidekick"}
    ])
    _write_state(paths, world, canon, series, story, {
        "Bob": {"status": "wounded", "location": "hospital", "alive": True}
    })

    update_registry(paths, world, canon, series, story)

    data = _load_registry(paths.character_registry(world, canon))
    bob = data["characters"]["Bob"]
    assert bob["last_known_status"] == "wounded"
    assert bob["story_states"][story]["location"] == "hospital"
    assert bob["alive"] is True


def test_update_registry_accumulates_across_stories(paths, world, canon, series):
    from quillan.structure.character_registry import update_registry

    story_a, story_b = "story_a", "story_b"

    _write_arcs(paths, world, canon, series, story_a, [
        {"name": "Alice", "description": "Original desc"}
    ])
    update_registry(paths, world, canon, series, story_a)

    _write_arcs(paths, world, canon, series, story_b, [
        {"name": "Alice", "description": "Updated desc"},
        {"name": "Bob", "description": "New char"},
    ])
    update_registry(paths, world, canon, series, story_b)

    data = _load_registry(paths.character_registry(world, canon))
    assert set(data["characters"].keys()) == {"Alice", "Bob"}
    assert data["characters"]["Alice"]["description"] == "Updated desc"
    assert story_a in data["characters"]["Alice"]["stories"]
    assert story_b in data["characters"]["Alice"]["stories"]


def test_update_registry_noop_when_no_source_files(paths, world, canon, series, story):
    from quillan.structure.character_registry import update_registry

    update_registry(paths, world, canon, series, story)  # should not raise
    assert not paths.character_registry(world, canon).exists()


# ── World-level registry tests ────────────────────────────────────────────────

def test_world_registry_path(paths, world):
    p = paths.world_character_registry(world)
    assert str(p).endswith(f"worlds/{world}/Character_Registry.yaml")


def test_update_world_registry_aggregates_canons(paths, world, series):
    from quillan.structure.character_registry import update_registry

    canon_a, canon_b = "canon_a", "canon_b"
    story = "mystory"

    _write_arcs(paths, world, canon_a, series, story, [
        {"name": "Alice", "description": "Hero in A", "motivation": "Freedom"}
    ])
    update_registry(paths, world, canon_a, series, story)

    _write_arcs(paths, world, canon_b, series, story, [
        {"name": "Alice", "description": "Villain in B"},
        {"name": "Carlos", "description": "New character"},
    ])
    update_registry(paths, world, canon_b, series, story)

    world_reg_path = paths.world_character_registry(world)
    assert world_reg_path.exists()
    data = _load_registry(world_reg_path)
    chars = data["characters"]

    assert "Alice" in chars
    assert "Carlos" in chars
    assert set(chars["Alice"]["canons"]) == {canon_a, canon_b}
    assert f"{canon_a}/{story}" in chars["Alice"]["stories"]
    assert f"{canon_b}/{story}" in chars["Alice"]["stories"]
    assert chars["Carlos"]["canons"] == [canon_b]


def test_world_registry_meta_scope(paths, world, series):
    from quillan.structure.character_registry import update_registry

    canon = "main"
    story = "s1"
    _write_arcs(paths, world, canon, series, story, [
        {"name": "Dana", "description": "Explorer"}
    ])
    update_registry(paths, world, canon, series, story)

    data = _load_registry(paths.world_character_registry(world))
    assert data["_meta"]["scope"] == "world"


def test_update_world_registry_noop_when_no_canons(paths, world):
    from quillan.structure.character_registry import update_world_registry

    update_world_registry(paths, world)  # should not raise
    assert not paths.world_character_registry(world).exists()


def test_world_registry_not_created_when_canons_empty(paths, world, series):

    # Canon registry exists but has no characters (no arcs/state files)
    # update_registry is a no-op; world registry should not be created either
    update_world_registry_directly = __import__(
        "quillan.structure.character_registry", fromlist=["update_world_registry"]
    ).update_world_registry
    update_world_registry_directly(paths, world)
    assert not paths.world_character_registry(world).exists()


# ── load_world_registry_section ───────────────────────────────────────────────

def test_load_world_registry_section_empty_when_missing(paths, world):
    from quillan.structure.character_registry import load_world_registry_section

    result = load_world_registry_section(paths, world)
    assert result == ""


def test_load_world_registry_section_returns_markdown(paths, world, series):
    from quillan.structure.character_registry import update_registry, load_world_registry_section

    canon, story = "main", "ep1"
    _write_arcs(paths, world, canon, series, story, [
        {"name": "Eve", "description": "Engineer", "motivation": "Survival"}
    ])
    _write_state(paths, world, canon, series, story, {
        "Eve": {"status": "active"}
    })
    update_registry(paths, world, canon, series, story)

    section = load_world_registry_section(paths, world)
    assert "Eve" in section
    assert "Engineer" in section
    assert "active" in section
    assert "## Established Characters (World Registry" in section


# ── load_registry_section (canon-level) ──────────────────────────────────────

def test_load_registry_section_empty_when_missing(paths, world, canon):
    from quillan.structure.character_registry import load_registry_section

    result = load_registry_section(paths, world, canon)
    assert result == ""


def test_load_registry_section_returns_markdown(paths, world, canon, series, story):
    from quillan.structure.character_registry import update_registry, load_registry_section

    _write_arcs(paths, world, canon, series, story, [
        {"name": "Frank", "description": "Detective", "motivation": "Justice"}
    ])
    update_registry(paths, world, canon, series, story)

    section = load_registry_section(paths, world, canon)
    assert "Frank" in section
    assert "Detective" in section
    assert "## Established Characters (Canon Registry)" in section
