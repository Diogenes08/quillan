"""Tests for quillan.validate — YAML/JSON validators."""

from __future__ import annotations

import pytest
import yaml

from quillan.validate import (
    validate_json,
    validate_yaml,
    validate_keys,
    validate_beat_spec,
    validate_local_state,
    validate_dependency_map,
    validate_beat_id,
    py_extract_json,
)


# ── validate_json ─────────────────────────────────────────────────────────────

def test_validate_json_valid(tmp_path):
    p = tmp_path / "data.json"
    p.write_text('{"key": "value", "n": 42}')
    result = validate_json(p)
    assert result == {"key": "value", "n": 42}


def test_validate_json_invalid(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not valid json}")
    with pytest.raises(ValueError, match="Invalid JSON"):
        validate_json(p)


def test_validate_json_not_object(tmp_path):
    p = tmp_path / "arr.json"
    p.write_text("[1, 2, 3]")
    with pytest.raises(ValueError, match="Expected JSON object"):
        validate_json(p)


def test_validate_json_missing_file(tmp_path):
    with pytest.raises(ValueError, match="Cannot read"):
        validate_json(tmp_path / "missing.json")


# ── validate_yaml ─────────────────────────────────────────────────────────────

def test_validate_yaml_valid(tmp_path):
    p = tmp_path / "data.yaml"
    p.write_text("key: value\nn: 42\n")
    result = validate_yaml(p)
    assert result == {"key": "value", "n": 42}


def test_validate_yaml_invalid(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("key: [\nunot closed")
    with pytest.raises(ValueError, match="Invalid YAML"):
        validate_yaml(p)


def test_validate_yaml_empty(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("")
    result = validate_yaml(p)
    assert result == {}


# ── validate_keys ─────────────────────────────────────────────────────────────

def test_validate_keys_ok():
    validate_keys({"a": 1, "b": 2}, "a", "b")  # no raise


def test_validate_keys_missing():
    with pytest.raises(ValueError, match="Missing required keys"):
        validate_keys({"a": 1}, "a", "b", "c")


# ── validate_beat_spec ────────────────────────────────────────────────────────

def test_validate_beat_spec_valid(tmp_path):
    p = tmp_path / "spec.yaml"
    p.write_text("beat_id: C1-S1-B1\ngoal: Do something\n")
    result = validate_beat_spec(p)
    assert result["beat_id"] == "C1-S1-B1"


def test_validate_beat_spec_missing_goal(tmp_path):
    p = tmp_path / "spec.yaml"
    p.write_text("beat_id: C1-S1-B1\n")
    with pytest.raises(ValueError, match="Missing required keys"):
        validate_beat_spec(p)


# ── validate_local_state ──────────────────────────────────────────────────────

def test_validate_local_state_valid(tmp_path):
    p = tmp_path / "state.yaml"
    p.write_text("characters:\n  Alice:\n    location: home\n")
    result = validate_local_state(p)
    assert "characters" in result


def test_validate_local_state_missing_characters(tmp_path):
    p = tmp_path / "state.yaml"
    p.write_text("events: []\n")
    with pytest.raises(ValueError, match="Missing required keys"):
        validate_local_state(p)


# ── validate_dependency_map ───────────────────────────────────────────────────

def test_validate_dependency_map_valid(tmp_path):
    p = tmp_path / "deps.json"
    p.write_text('{"dependencies": {"C1-S1-B1": []}}')
    result = validate_dependency_map(p)
    assert "dependencies" in result


def test_validate_dependency_map_missing_key(tmp_path):
    p = tmp_path / "deps.json"
    p.write_text('{"other": {}}')
    with pytest.raises(ValueError, match="Missing required keys"):
        validate_dependency_map(p)


# ── validate_beat_id ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("beat_id,expected", [
    ("C1-S1-B1", True),
    ("C10-S2-B100", True),
    ("C0-S0-B0", True),
    ("bad", False),
    ("C1-S1", False),
    ("1-1-1", False),
    ("C1-S1-B", False),
    ("", False),
])
def test_validate_beat_id(beat_id, expected):
    assert validate_beat_id(beat_id) == expected


# ── py_extract_json ───────────────────────────────────────────────────────────

def test_py_extract_json_plain():
    result = py_extract_json('{"a": 1}')
    assert result == {"a": 1}


def test_py_extract_json_with_fences():
    result = py_extract_json('```json\n{"a": 1}\n```')
    assert result == {"a": 1}


def test_py_extract_json_yaml_fallback():
    result = py_extract_json("a: 1\nb: two")
    assert result["a"] == 1
    assert result["b"] == "two"


def test_py_extract_json_required_keys_ok():
    result = py_extract_json('{"a": 1, "b": 2}', required_keys=["a", "b"])
    assert result["b"] == 2


def test_py_extract_json_required_keys_missing():
    with pytest.raises(ValueError, match="Missing required keys"):
        py_extract_json('{"a": 1}', required_keys=["a", "b"])


def test_py_extract_json_invalid():
    with pytest.raises(ValueError):
        py_extract_json("not json and not yaml either {{{ }")


# ── validate_creative_brief ───────────────────────────────────────────────────

def test_validate_creative_brief_valid(tmp_path):
    from quillan.validate import validate_creative_brief
    p = tmp_path / "brief.yaml"
    p.write_text(yaml.dump({"voice": {"pov": "third"}, "arc_intent": "A to B"}))
    data = validate_creative_brief(p)
    assert "voice" in data
    assert "arc_intent" in data


def test_validate_creative_brief_missing_arc_intent(tmp_path):
    from quillan.validate import validate_creative_brief
    p = tmp_path / "brief.yaml"
    p.write_text(yaml.dump({"voice": {"pov": "third"}}))
    with pytest.raises(ValueError, match="Missing required keys"):
        validate_creative_brief(p)


def test_validate_creative_brief_missing_voice(tmp_path):
    from quillan.validate import validate_creative_brief
    p = tmp_path / "brief.yaml"
    p.write_text(yaml.dump({"arc_intent": "A to B"}))
    with pytest.raises(ValueError, match="Missing required keys"):
        validate_creative_brief(p)


# ── validate_story_spine ──────────────────────────────────────────────────────

def test_validate_story_spine_valid(tmp_path):
    from quillan.validate import validate_story_spine
    p = tmp_path / "spine.yaml"
    p.write_text(yaml.dump({
        "structure": "three_act",
        "acts": [{"act": 1, "label": "Setup", "beats": []}],
        "beat_tension": {"C1-S1-B1": 3},
    }))
    data = validate_story_spine(p)
    assert data["structure"] == "three_act"


def test_validate_story_spine_missing_beat_tension(tmp_path):
    from quillan.validate import validate_story_spine
    p = tmp_path / "spine.yaml"
    p.write_text(yaml.dump({"structure": "three_act", "acts": []}))
    with pytest.raises(ValueError, match="Missing required keys"):
        validate_story_spine(p)


# ── validate_character_arcs ───────────────────────────────────────────────────

def test_validate_character_arcs_valid(tmp_path):
    from quillan.validate import validate_character_arcs
    p = tmp_path / "arcs.yaml"
    p.write_text(yaml.dump({"characters": [{"name": "Alice"}]}))
    data = validate_character_arcs(p)
    assert "characters" in data


def test_validate_character_arcs_missing_characters(tmp_path):
    from quillan.validate import validate_character_arcs
    p = tmp_path / "arcs.yaml"
    p.write_text(yaml.dump({"other": "data"}))
    with pytest.raises(ValueError, match="Missing required keys"):
        validate_character_arcs(p)


# ── validate_subplot_register ─────────────────────────────────────────────────

def test_validate_subplot_register_valid(tmp_path):
    from quillan.validate import validate_subplot_register
    p = tmp_path / "sub.yaml"
    p.write_text(yaml.dump({"subplots": []}))
    data = validate_subplot_register(p)
    assert data["subplots"] == []


def test_validate_subplot_register_missing_subplots(tmp_path):
    from quillan.validate import validate_subplot_register
    p = tmp_path / "sub.yaml"
    p.write_text(yaml.dump({"other": "data"}))
    with pytest.raises(ValueError, match="Missing required keys"):
        validate_subplot_register(p)
