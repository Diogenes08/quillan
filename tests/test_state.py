"""Tests for quillan.continuity.state — apply_state_patch deep merge."""

from __future__ import annotations



from quillan.continuity.state import apply_state_patch, _get_nested, _set_nested, _delete_nested


# ── Basic set operations ──────────────────────────────────────────────────────

def test_set_top_level():
    state = {"a": 1}
    patch = {"set": {"a": 2}, "append": {}, "delete": []}
    result = apply_state_patch(state, patch)
    assert result["a"] == 2


def test_set_nested():
    state = {"characters": {"Alice": {"location": "home"}}}
    patch = {"set": {"characters.Alice.location": "forest"}, "append": {}, "delete": []}
    result = apply_state_patch(state, patch)
    assert result["characters"]["Alice"]["location"] == "forest"


def test_set_creates_intermediate_dicts():
    state = {}
    patch = {"set": {"a.b.c": "value"}, "append": {}, "delete": []}
    result = apply_state_patch(state, patch)
    assert result["a"]["b"]["c"] == "value"


def test_set_does_not_mutate_original():
    state = {"a": 1}
    patch = {"set": {"a": 99}, "append": {}, "delete": []}
    result = apply_state_patch(state, patch)
    assert state["a"] == 1
    assert result["a"] == 99


# ── Append operations ─────────────────────────────────────────────────────────

def test_append_to_existing_list():
    state = {"events": ["event1"]}
    patch = {"set": {}, "append": {"events": "event2"}, "delete": []}
    result = apply_state_patch(state, patch)
    assert result["events"] == ["event1", "event2"]


def test_append_creates_list():
    state = {}
    patch = {"set": {}, "append": {"events": "first event"}, "delete": []}
    result = apply_state_patch(state, patch)
    assert result["events"] == ["first event"]


def test_append_nested():
    state = {"characters": {"Alice": {"actions": []}}}
    patch = {"set": {}, "append": {"characters.Alice.actions": "ran away"}, "delete": []}
    result = apply_state_patch(state, patch)
    assert result["characters"]["Alice"]["actions"] == ["ran away"]


def test_append_non_list_is_skipped():
    state = {"note": "text"}  # not a list
    patch = {"set": {}, "append": {"note": "extra"}, "delete": []}
    result = apply_state_patch(state, patch)
    # Original non-list value unchanged
    assert result["note"] == "text"


# ── Delete operations ─────────────────────────────────────────────────────────

def test_delete_top_level():
    state = {"a": 1, "b": 2}
    patch = {"set": {}, "append": {}, "delete": ["a"]}
    result = apply_state_patch(state, patch)
    assert "a" not in result
    assert result["b"] == 2


def test_delete_nested():
    state = {"characters": {"Alice": {"status": "alive", "location": "forest"}}}
    patch = {"set": {}, "append": {}, "delete": ["characters.Alice.status"]}
    result = apply_state_patch(state, patch)
    assert "status" not in result["characters"]["Alice"]
    assert result["characters"]["Alice"]["location"] == "forest"


def test_delete_missing_path_is_noop():
    state = {"a": 1}
    patch = {"set": {}, "append": {}, "delete": ["nonexistent.path"]}
    result = apply_state_patch(state, patch)
    assert result["a"] == 1


# ── Disallowed mutations ──────────────────────────────────────────────────────

def test_disallowed_meta_not_mutated():
    """_meta keys must be restored after patch."""
    state = {"_meta": {"version": "1.0"}, "a": 1}
    patch = {
        "set": {"_meta.version": "9.9", "a": 2},
        "append": {},
        "delete": [],
    }
    result = apply_state_patch(state, patch)
    # _meta.version restored
    assert result["_meta"]["version"] == "1.0"
    # Regular field changed
    assert result["a"] == 2


def test_disallowed_locked_not_mutated():
    state = {"_locked": {"key": "secret"}}
    patch = {"set": {"_locked.key": "hacked"}, "append": {}, "delete": []}
    result = apply_state_patch(state, patch)
    assert result["_locked"]["key"] == "secret"


# ── Complex scenarios ─────────────────────────────────────────────────────────

def test_full_patch():
    state = {
        "characters": {
            "Alice": {"location": "home", "health": 100},
        },
        "events": ["started"],
        "world_state": {},
    }
    patch = {
        "set": {"characters.Alice.location": "dungeon", "world_state.weather": "stormy"},
        "append": {"events": "Alice entered the dungeon"},
        "delete": [],
    }
    result = apply_state_patch(state, patch)
    assert result["characters"]["Alice"]["location"] == "dungeon"
    assert result["characters"]["Alice"]["health"] == 100
    assert result["world_state"]["weather"] == "stormy"
    assert "Alice entered the dungeon" in result["events"]


def test_empty_patch():
    state = {"a": 1, "b": [1, 2]}
    patch = {"set": {}, "append": {}, "delete": []}
    result = apply_state_patch(state, patch)
    assert result == state


# ── Helper function tests ─────────────────────────────────────────────────────

def test_get_nested_found():
    d = {"a": {"b": {"c": 42}}}
    assert _get_nested(d, ["a", "b", "c"]) == 42


def test_get_nested_missing():
    d = {"a": {}}
    assert _get_nested(d, ["a", "b", "c"]) is None


def test_set_nested_creates():
    d = {}
    _set_nested(d, ["x", "y", "z"], "val")
    assert d["x"]["y"]["z"] == "val"


def test_delete_nested_no_op():
    d = {"a": 1}
    _delete_nested(d, ["x", "y"])  # Should not raise
    assert d == {"a": 1}
