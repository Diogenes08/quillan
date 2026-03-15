"""Unit tests for quillan.web.models — Database CRUD and job lifecycle."""

from __future__ import annotations

import pytest
import sqlite3


@pytest.fixture
def db(tmp_path):
    from quillan.web.models import Database
    d = Database(tmp_path / "test.db")
    d.init_schema()
    return d


# ── Users ──────────────────────────────────────────────────────────────────────

def test_create_and_get_user(db):
    user = db.create_user("alice", "hashed_pw")
    assert user["username"] == "alice"
    assert user["id"] is not None

    found = db.get_user_by_username("alice")
    assert found is not None
    assert found["hashed_password"] == "hashed_pw"


def test_get_user_not_found_returns_none(db):
    assert db.get_user_by_username("ghost") is None


def test_get_user_by_id(db):
    user = db.create_user("bob", "pw")
    found = db.get_user_by_id(user["id"])
    assert found is not None
    assert found["username"] == "bob"


def test_duplicate_username_raises(db):
    db.create_user("carol", "pw1")
    with pytest.raises(sqlite3.IntegrityError):
        db.create_user("carol", "pw2")


# ── Stories ────────────────────────────────────────────────────────────────────

def test_create_and_get_story(db):
    user = db.create_user("alice", "pw")
    story = db.create_story(user["id"], "world1", "default", "default", "my_story")
    assert story["story"] == "my_story"
    assert story["user_id"] == user["id"]

    found = db.get_story(story["id"])
    assert found is not None
    assert found["world"] == "world1"


def test_get_story_not_found_returns_none(db):
    assert db.get_story(9999) is None


def test_list_stories_for_user(db):
    user = db.create_user("dave", "pw")
    db.create_story(user["id"], "w", "c", "s", "story_a")
    db.create_story(user["id"], "w", "c", "s", "story_b")
    stories = db.list_stories(user["id"])
    assert len(stories) == 2
    names = {s["story"] for s in stories}
    assert names == {"story_a", "story_b"}


def test_list_stories_empty_for_other_user(db):
    user1 = db.create_user("eve", "pw")
    user2 = db.create_user("frank", "pw")
    db.create_story(user1["id"], "w", "c", "s", "story")
    assert db.list_stories(user2["id"]) == []


# ── Jobs ───────────────────────────────────────────────────────────────────────

def _make_story(db):
    user = db.create_user(f"user_{id(db)}", "pw")
    return db.create_story(user["id"], "w", "c", "s", "st")


def test_create_and_list_jobs(db):
    story = _make_story(db)
    job = db.create_job(story["id"], "create", {"seed": "test"})
    assert job["status"] == "queued"
    assert job["type"] == "create"

    jobs = db.list_jobs(story["id"])
    assert len(jobs) == 1
    assert jobs[0]["id"] == job["id"]


def test_pop_queued_job_marks_running(db):
    story = _make_story(db)
    db.create_job(story["id"], "create", {})

    popped = db.pop_queued_job()
    assert popped is not None
    # pop_queued_job returns the pre-UPDATE snapshot; re-query to see 'running'
    assert db.get_job(popped["id"])["status"] == "running"


def test_pop_queued_job_empty_returns_none(db):
    assert db.pop_queued_job() is None


def test_pop_queued_job_fifo_order(db):
    story = _make_story(db)
    j1 = db.create_job(story["id"], "create", {"n": 1})
    j2 = db.create_job(story["id"], "create", {"n": 2})

    first = db.pop_queued_job()
    assert first["id"] == j1["id"]
    second = db.pop_queued_job()
    assert second["id"] == j2["id"]


def test_finish_job_done(db):
    story = _make_story(db)
    db.create_job(story["id"], "create", {})
    popped = db.pop_queued_job()

    db.finish_job(popped["id"], result={"story": "my_story"})

    done = db.get_job(popped["id"])
    assert done["status"] == "done"
    assert done["error"] is None
    assert done["finished_at"] is not None


def test_finish_job_failed(db):
    story = _make_story(db)
    db.create_job(story["id"], "create", {})
    popped = db.pop_queued_job()

    db.finish_job(popped["id"], error="something exploded")

    failed = db.get_job(popped["id"])
    assert failed["status"] == "failed"
    assert "something exploded" in failed["error"]
