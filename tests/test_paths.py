"""Tests for quillan.paths — path construction."""

from pathlib import Path

import pytest

from quillan.paths import Paths


@pytest.fixture
def p(tmp_path):
    return Paths(tmp_path / "data")


def test_data_dir(p, tmp_path):
    assert p.data_dir == tmp_path / "data"


def test_worlds_dir(p, tmp_path):
    assert p.worlds_dir() == tmp_path / "data" / "worlds"


def test_runs_dir(p, tmp_path):
    assert p.runs_dir() == tmp_path / "data" / ".runs"


def test_world(p, tmp_path):
    assert p.world("myworld") == tmp_path / "data" / "worlds" / "myworld"


def test_world_planning(p, tmp_path):
    result = p.world_planning("myworld")
    assert result == tmp_path / "data" / "worlds" / "myworld" / "planning"


def test_canon(p, tmp_path):
    result = p.canon("w", "c")
    assert result == tmp_path / "data" / "worlds" / "w" / "canons" / "c"


def test_series(p, tmp_path):
    result = p.series("w", "c", "s")
    assert result == tmp_path / "data" / "worlds" / "w" / "canons" / "c" / "series" / "s"


def test_story(p, tmp_path):
    result = p.story("w", "c", "s", "st")
    expected = tmp_path / "data" / "worlds" / "w" / "canons" / "c" / "series" / "s" / "stories" / "st"
    assert result == expected


def test_story_subdirs(p):
    """All story subdirectory methods return paths under story()."""
    story_base = p.story("w", "c", "s", "st")
    assert p.story_input("w", "c", "s", "st") == story_base / "input"
    assert p.story_planning("w", "c", "s", "st") == story_base / "planning"
    assert p.story_structure("w", "c", "s", "st") == story_base / "structure"
    assert p.story_beats("w", "c", "s", "st") == story_base / "beats"
    assert p.story_state("w", "c", "s", "st") == story_base / "state"
    assert p.story_export("w", "c", "s", "st") == story_base / "export"
    assert p.story_continuity("w", "c", "s", "st") == story_base / "continuity"


def test_beat(p):
    result = p.beat("w", "c", "s", "st", "C1-S1-B1")
    assert result.name == "C1-S1-B1"
    assert result.parent.name == "beats"


def test_beat_spec(p):
    result = p.beat_spec("w", "c", "s", "st", "C1-S1-B1")
    assert result.name == "beat_spec.yaml"
    assert result.parent.name == "C1-S1-B1"


def test_beat_draft(p):
    result = p.beat_draft("w", "c", "s", "st", "C1-S1-B1")
    assert result.name == "Beat_Draft.md"


def test_state_bundle(p):
    result = p.state_bundle("w", "c", "s", "st", "C1-S1-B1")
    assert result.name == "C1-S1-B1_state.yaml"
    assert result.parent.name == "state"


def test_state_current(p):
    result = p.state_current("w", "c", "s", "st")
    assert result.name == "current_state.yaml"
    assert result.parent.name == "state"


def test_queue_dir(p):
    result = p.queue_dir("w", "c", "s", "st")
    assert result.name == "queue"
    assert result.parent.name == "continuity"


def test_outline(p):
    result = p.outline("w", "c", "s", "st")
    assert result.name == "Outline.yaml"
    assert result.parent.name == "structure"


def test_dependency_map(p):
    result = p.dependency_map("w", "c", "s", "st")
    assert result.name == "dependency_map.json"


def test_canon_packet(p):
    result = p.canon_packet("w", "c", "s", "st")
    assert result.name == "Canon_Packet.md"


def test_beat_mega_audit(p):
    result = p.beat_mega_audit("w", "c", "s", "st", "C2-S3-B7")
    assert result.name == "mega_audit.json"
    assert result.parent.name == "forensic"


def test_continuity_files(p):
    assert p.continuity_summary("w", "c", "s", "st").name == "Summary.md"
    assert p.continuity_threads("w", "c", "s", "st").name == "Open_Threads.md"
    assert p.continuity_ledger("w", "c", "s", "st").name == "Ledger.md"


def test_ensure_file(p, tmp_path):
    """ensure() creates parent directory for a file path."""
    file_path = p.story("w", "c", "s", "st") / "structure" / "Outline.yaml"
    result = p.ensure(file_path)
    assert result == file_path
    assert file_path.parent.is_dir()


def test_ensure_dir(p, tmp_path):
    """ensure() creates the directory itself for a dir path."""
    dir_path = p.world("myworld")
    p.ensure(dir_path)
    assert dir_path.is_dir()


def test_path_accepts_string_data_dir():
    """Paths should accept a string data_dir and convert to Path."""
    p = Paths("/tmp/q2test")
    assert isinstance(p.data_dir, Path)
    assert p.data_dir == Path("/tmp/q2test")
