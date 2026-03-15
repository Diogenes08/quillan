"""Tests for M1 — Beat Locking."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from quillan.paths import Paths


# ── paths.beat_lock ────────────────────────────────────────────────────────────

def test_beat_lock_returns_path(paths, world, canon, series, story):
    lock = paths.beat_lock(world, canon, series, story, "C1-S1-B1")
    assert isinstance(lock, Path)


def test_beat_lock_filename(paths, world, canon, series, story):
    lock = paths.beat_lock(world, canon, series, story, "C1-S1-B1")
    assert lock.name == ".lock"


def test_beat_lock_inside_beat_dir(paths, world, canon, series, story):
    lock = paths.beat_lock(world, canon, series, story, "C1-S1-B1")
    assert lock.parent.name == "C1-S1-B1"


def test_beat_lock_different_beats(paths, world, canon, series, story):
    lock_a = paths.beat_lock(world, canon, series, story, "C1-S1-B1")
    lock_b = paths.beat_lock(world, canon, series, story, "C1-S1-B2")
    assert lock_a != lock_b
    assert lock_a.parent != lock_b.parent


# ── runner skips locked beats ──────────────────────────────────────────────────

def _make_dep_map(beat_id: str = "C1-S1-B1") -> dict:
    return {"dependencies": {beat_id: []}}


def _write_dep_map(paths: Paths, world: str, canon: str, series: str,
                   story: str, dep_map: dict) -> None:
    import json
    dep_path = paths.dependency_map(world, canon, series, story)
    dep_path.parent.mkdir(parents=True, exist_ok=True)
    dep_path.write_text(json.dumps(dep_map), encoding="utf-8")


def test_locked_beat_skipped_even_with_force(paths, world, canon, series, story):
    """A locked beat must be skipped even when force=True."""
    from quillan.config import Settings
    from quillan.llm import LLMClient
    from quillan.telemetry import Telemetry
    from quillan.pipeline.runner import draft_story

    beat_id = "C1-S1-B1"
    _write_dep_map(paths, world, canon, series, story, _make_dep_map(beat_id))

    # Create and touch the lock file
    lock_path = paths.beat_lock(world, canon, series, story, beat_id)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.touch()

    settings = Settings(data_dir=paths.data_dir, llm_cache=False, telemetry=False)
    tel = Telemetry(paths.runs_dir(), enabled=False)
    llm = LLMClient(settings, tel, cache_dir=settings.cache_dir)

    result = asyncio.run(
        draft_story(
            paths, world, canon, series, story,
            beats_mode="all",
            settings=settings, llm=llm, telemetry=tel,
            force=True,
        )
    )

    # Beat was skipped — no draft written, no failure recorded
    draft_path = paths.beat_draft(world, canon, series, story, beat_id)
    assert not draft_path.exists(), "Draft should not have been created for a locked beat"
    assert beat_id not in result.completed
    assert beat_id not in result.failed


def test_unlocked_beat_is_drafted(paths, world, canon, series, story):
    """An unlocked beat is drafted normally (offline stub creates the file)."""
    from quillan.config import Settings
    from quillan.llm import LLMClient
    from quillan.telemetry import Telemetry
    from quillan.pipeline.runner import draft_story

    beat_id = "C1-S1-B1"
    _write_dep_map(paths, world, canon, series, story, _make_dep_map(beat_id))

    # Ensure no lock file exists
    lock_path = paths.beat_lock(world, canon, series, story, beat_id)
    assert not lock_path.exists()

    settings = Settings(data_dir=paths.data_dir, llm_cache=False, telemetry=False)
    tel = Telemetry(paths.runs_dir(), enabled=False)
    llm = LLMClient(settings, tel, cache_dir=settings.cache_dir)

    asyncio.run(
        draft_story(
            paths, world, canon, series, story,
            beats_mode="all",
            settings=settings, llm=llm, telemetry=tel,
            force=False,
        )
    )

    # The offline stub should have written something
    draft_path = paths.beat_draft(world, canon, series, story, beat_id)
    assert draft_path.exists(), "Unlocked beat should produce a draft"


# ── CLI lock-beat / unlock-beat ───────────────────────────────────────────────

def _make_outline(beat_ids: list[str]) -> dict:
    return {
        "chapters": [
            {
                "chapter": 1,
                "beats": [{"beat_id": bid} for bid in beat_ids],
            }
        ]
    }


def _write_outline(paths: Paths, world: str, canon: str, series: str,
                   story: str, beat_ids: list[str]) -> None:
    import yaml
    outline_path = paths.outline(world, canon, series, story)
    outline_path.parent.mkdir(parents=True, exist_ok=True)
    outline_path.write_text(yaml.dump(_make_outline(beat_ids)), encoding="utf-8")


def test_cli_lock_beat(tmp_path):
    from click.testing import CliRunner
    from quillan.cli import main

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    paths = Paths(data_dir)
    world, canon, series, story = "w", "c", "s", "st"
    beat_id = "C1-S1-B1"
    # Create the beat directory so lock can be created
    beat_dir = paths.beat(world, canon, series, story, beat_id)
    beat_dir.mkdir(parents=True, exist_ok=True)

    runner = CliRunner()
    result = runner.invoke(main, [
        "--data-dir", str(data_dir),
        "--world", world,
        "--canon", canon,
        "--series", series,
        "lock-beat", story, beat_id,
    ])
    assert result.exit_code == 0, result.output
    lock_path = paths.beat_lock(world, canon, series, story, beat_id)
    assert lock_path.exists()


def test_cli_unlock_beat(tmp_path):
    from click.testing import CliRunner
    from quillan.cli import main

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    paths = Paths(data_dir)
    world, canon, series, story = "w", "c", "s", "st"
    beat_id = "C1-S1-B1"

    # Pre-create the lock file
    lock_path = paths.beat_lock(world, canon, series, story, beat_id)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.touch()
    assert lock_path.exists()

    runner = CliRunner()
    result = runner.invoke(main, [
        "--data-dir", str(data_dir),
        "--world", world,
        "--canon", canon,
        "--series", series,
        "unlock-beat", story, beat_id,
    ])
    assert result.exit_code == 0, result.output
    assert not lock_path.exists()


def test_cli_unlock_beat_not_locked(tmp_path):
    from click.testing import CliRunner
    from quillan.cli import main

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    paths = Paths(data_dir)
    world, canon, series, story = "w", "c", "s", "st"
    beat_id = "C1-S1-B1"
    beat_dir = paths.beat(world, canon, series, story, beat_id)
    beat_dir.mkdir(parents=True, exist_ok=True)

    runner = CliRunner()
    result = runner.invoke(main, [
        "--data-dir", str(data_dir),
        "--world", world,
        "--canon", canon,
        "--series", series,
        "unlock-beat", story, beat_id,
    ])
    assert result.exit_code == 0, result.output
    assert "not locked" in result.output


def test_cli_lock_beat_all(tmp_path):
    from click.testing import CliRunner
    from quillan.cli import main

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    paths = Paths(data_dir)
    world, canon, series, story = "w", "c", "s", "st"
    beat_ids = ["C1-S1-B1", "C1-S1-B2", "C1-S1-B3"]
    _write_outline(paths, world, canon, series, story, beat_ids)
    for bid in beat_ids:
        paths.beat(world, canon, series, story, bid).mkdir(parents=True, exist_ok=True)

    runner = CliRunner()
    result = runner.invoke(main, [
        "--data-dir", str(data_dir),
        "--world", world,
        "--canon", canon,
        "--series", series,
        "lock-beat", story, "--all",
    ])
    assert result.exit_code == 0, result.output
    for bid in beat_ids:
        assert paths.beat_lock(world, canon, series, story, bid).exists()


def test_cli_unlock_beat_all(tmp_path):
    from click.testing import CliRunner
    from quillan.cli import main

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    paths = Paths(data_dir)
    world, canon, series, story = "w", "c", "s", "st"
    beat_ids = ["C1-S1-B1", "C1-S1-B2"]
    _write_outline(paths, world, canon, series, story, beat_ids)
    for bid in beat_ids:
        lock_path = paths.beat_lock(world, canon, series, story, bid)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.touch()

    runner = CliRunner()
    result = runner.invoke(main, [
        "--data-dir", str(data_dir),
        "--world", world,
        "--canon", canon,
        "--series", series,
        "unlock-beat", story, "--all",
    ])
    assert result.exit_code == 0, result.output
    for bid in beat_ids:
        assert not paths.beat_lock(world, canon, series, story, bid).exists()


# ── Web endpoints ──────────────────────────────────────────────────────────────

@pytest.fixture
def web_client(tmp_path, monkeypatch):
    """TestClient with lifespan against a fresh tmp-dir database."""
    import quillan.web.app as _app
    monkeypatch.setattr(_app, "_data_dir", tmp_path)
    monkeypatch.setattr(_app, "_db_path", tmp_path / ".web" / "test.db")
    monkeypatch.setattr(_app, "hash_password", lambda pw: f"hashed:{pw}")
    monkeypatch.setattr(_app, "verify_password",
                        lambda plain, hashed: hashed == f"hashed:{plain}")
    from fastapi.testclient import TestClient
    with TestClient(_app.app) as client:
        client.post("/auth/register", json={"username": "u", "password": "password1"})
        resp = client.post("/auth/login", data={"username": "u", "password": "password1"})
        token = resp.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})
        client._app_mod = _app
        yield client


def _create_beat_for_web(client, beat_id: str = "C1-S1-B1") -> int:
    """Create a story DB record and beat directory, return story_id."""
    app_mod = client._app_mod
    data_dir = app_mod._data_dir
    db = app_mod._db

    user = db.get_user_by_username("u")
    row = db.create_story(user["id"], "world", "default", "default", "teststory")
    story_id = row["id"]

    paths = Paths(data_dir)
    beat_dir = paths.beat("world", "default", "default", "teststory", beat_id)
    beat_dir.mkdir(parents=True, exist_ok=True)
    return story_id


def test_web_lock_beat_returns_200(web_client):
    beat_id = "C1-S1-B1"
    story_id = _create_beat_for_web(web_client, beat_id)
    r = web_client.put(f"/stories/{story_id}/beats/{beat_id}/lock")
    assert r.status_code == 200
    data = r.json()
    assert data["locked"] is True
    assert data["beat_id"] == beat_id


def test_web_lock_creates_lock_file(web_client):
    beat_id = "C1-S1-B1"
    story_id = _create_beat_for_web(web_client, beat_id)
    web_client.put(f"/stories/{story_id}/beats/{beat_id}/lock")

    paths = Paths(web_client._app_mod._data_dir)
    lock_path = paths.beat_lock("world", "default", "default", "teststory", beat_id)
    assert lock_path.exists()


def test_web_unlock_beat_returns_200(web_client):
    beat_id = "C1-S1-B1"
    story_id = _create_beat_for_web(web_client, beat_id)

    # Lock first
    web_client.put(f"/stories/{story_id}/beats/{beat_id}/lock")

    r = web_client.delete(f"/stories/{story_id}/beats/{beat_id}/lock")
    assert r.status_code == 200
    data = r.json()
    assert data["locked"] is False
    assert data["beat_id"] == beat_id


def test_web_unlock_removes_lock_file(web_client):
    beat_id = "C1-S1-B1"
    story_id = _create_beat_for_web(web_client, beat_id)
    web_client.put(f"/stories/{story_id}/beats/{beat_id}/lock")
    web_client.delete(f"/stories/{story_id}/beats/{beat_id}/lock")

    paths = Paths(web_client._app_mod._data_dir)
    lock_path = paths.beat_lock("world", "default", "default", "teststory", beat_id)
    assert not lock_path.exists()


def test_web_unlock_not_locked_returns_404(web_client):
    beat_id = "C1-S1-B1"
    story_id = _create_beat_for_web(web_client, beat_id)
    r = web_client.delete(f"/stories/{story_id}/beats/{beat_id}/lock")
    assert r.status_code == 404
