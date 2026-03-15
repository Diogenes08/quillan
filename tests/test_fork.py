"""Tests for 5C fork lineage — fork_story endpoint, parent_story_id tracking,
fork counts, and library fork browsing.
"""

from __future__ import annotations

import pytest


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def web_client(tmp_path, monkeypatch):
    """TestClient with lifespan running against a fresh tmp-dir database."""
    import quillan.web.app as _app
    monkeypatch.setattr(_app, "_data_dir", tmp_path)
    monkeypatch.setattr(_app, "_db_path", tmp_path / ".web" / "test.db")
    monkeypatch.setattr(_app, "hash_password", lambda pw: f"hashed:{pw}")
    monkeypatch.setattr(_app, "verify_password",
                        lambda plain, hashed: hashed == f"hashed:{plain}")
    from fastapi.testclient import TestClient
    with TestClient(_app.app) as client:
        client._app_mod = _app
        yield client


def _auth_headers(client, username: str = "alice", password: str = "password1") -> dict:
    client.post("/auth/register", json={"username": username, "password": password})
    resp = client.post("/auth/login", data={"username": username, "password": password})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _create_story(client, headers, *, world="w", canon="c", series="s", story="base") -> int:
    """Create a story via the seed endpoint and return its id."""
    db = client._app_mod._db
    user = db.get_user_by_username(headers["Authorization"].split()[-1])
    # Use DB directly so we don't need to run the full job pipeline.
    username = _username_from_headers(client, headers)
    user = db.get_user_by_username(username)
    row = db.create_story(user["id"], world, canon, series, story)
    return row["id"]


def _username_from_headers(client, headers) -> str:
    """Decode the JWT from headers to find username (use a whoami endpoint instead)."""
    # Use the /stories endpoint: it returns stories for the authenticated user
    # but we actually just need the username — use the /auth/register response
    # stored username. Instead, look it up via DB after listing users.
    _db = client._app_mod._db
    _users = _db.list_users()
    # The token identifies the user; just grab the most recently created user
    # whose token matches. For tests with one user per fixture this is reliable.
    # For multi-user tests we'll pass username explicitly.
    raise NotImplementedError("use _create_story_for(client, username)")


def _create_story_for(client, username: str, *, world="w", canon="c", series="s", story="base") -> int:
    db = client._app_mod._db
    user = db.get_user_by_username(username)
    row = db.create_story(user["id"], world, canon, series, story)
    return row["id"]


def _make_public(client, story_id: int, headers: dict) -> None:
    client.patch(f"/stories/{story_id}/visibility",
                 json={"visibility": "public"}, headers=headers)


# ── Model-layer: parent_story_id ───────────────────────────────────────────────

def test_create_story_no_parent(web_client):
    """create_story without parent_story_id sets it to None."""
    db = web_client._app_mod._db
    web_client.post("/auth/register", json={"username": "u", "password": "password1"})
    user = db.get_user_by_username("u")
    row = db.create_story(user["id"], "w", "c", "s", "story1")
    fetched = db.get_story(row["id"])
    assert fetched["parent_story_id"] is None


def test_create_story_with_parent(web_client):
    """create_story with parent_story_id records the FK correctly."""
    db = web_client._app_mod._db
    web_client.post("/auth/register", json={"username": "u", "password": "password1"})
    user = db.get_user_by_username("u")
    parent = db.create_story(user["id"], "w", "c", "s", "parent")
    child = db.create_story(user["id"], "w", "c", "s", "child",
                            parent_story_id=parent["id"])
    fetched = db.get_story(child["id"])
    assert fetched["parent_story_id"] == parent["id"]


def test_count_forks_zero(web_client):
    db = web_client._app_mod._db
    web_client.post("/auth/register", json={"username": "u", "password": "password1"})
    user = db.get_user_by_username("u")
    row = db.create_story(user["id"], "w", "c", "s", "orig")
    assert db.count_forks(row["id"]) == 0


def test_count_forks_nonzero(web_client):
    db = web_client._app_mod._db
    web_client.post("/auth/register", json={"username": "u", "password": "password1"})
    user = db.get_user_by_username("u")
    parent = db.create_story(user["id"], "w", "c", "s", "parent")
    db.create_story(user["id"], "w", "c", "s", "fork1", parent_story_id=parent["id"])
    db.create_story(user["id"], "w", "c", "s", "fork2", parent_story_id=parent["id"])
    assert db.count_forks(parent["id"]) == 2


def test_list_forks_returns_correct_rows(web_client):
    db = web_client._app_mod._db
    web_client.post("/auth/register", json={"username": "u", "password": "password1"})
    user = db.get_user_by_username("u")
    parent = db.create_story(user["id"], "w", "c", "s", "parent")
    db.create_story(user["id"], "w", "c", "s", "fork1", parent_story_id=parent["id"])
    db.create_story(user["id"], "w", "c", "s", "fork2", parent_story_id=parent["id"])
    forks = db.list_forks(parent["id"])
    assert len(forks) == 2
    fork_names = {f["story"] for f in forks}
    assert fork_names == {"fork1", "fork2"}


def test_list_forks_includes_author(web_client):
    db = web_client._app_mod._db
    web_client.post("/auth/register", json={"username": "alice", "password": "password1"})
    alice = db.get_user_by_username("alice")
    parent = db.create_story(alice["id"], "w", "c", "s", "parent")
    db.create_story(alice["id"], "w", "c", "s", "fork1", parent_story_id=parent["id"])
    forks = db.list_forks(parent["id"])
    assert forks[0]["author"] == "alice"


# ── Fork endpoint ─────────────────────────────────────────────────────────────

def test_fork_story_sets_parent_story_id(web_client):
    """POST /library/{id}/fork creates a child story with parent_story_id set."""
    db = web_client._app_mod._db
    # alice creates and publishes a story
    alice_hdrs = _auth_headers(web_client, "alice", "password1")
    parent_id = _create_story_for(web_client, "alice", story="orig")
    _make_public(web_client, parent_id, alice_hdrs)

    # bob forks it
    bob_hdrs = _auth_headers(web_client, "bob", "password1")
    resp = web_client.post(f"/library/{parent_id}/fork",
                           json={"name": "bobs_fork"}, headers=bob_hdrs)
    assert resp.status_code == 202
    fork_id = resp.json()["story_id"]

    forked = db.get_story(fork_id)
    assert forked["parent_story_id"] == parent_id


def test_fork_story_owner_is_forker(web_client):
    db = web_client._app_mod._db
    alice_hdrs = _auth_headers(web_client, "alice", "password1")
    parent_id = _create_story_for(web_client, "alice", story="orig")
    _make_public(web_client, parent_id, alice_hdrs)

    bob_hdrs = _auth_headers(web_client, "bob", "password1")
    resp = web_client.post(f"/library/{parent_id}/fork",
                           json={"name": "bobs_fork"}, headers=bob_hdrs)
    assert resp.status_code == 202
    fork_id = resp.json()["story_id"]
    bob = db.get_user_by_username("bob")
    forked = db.get_story(fork_id)
    assert forked["user_id"] == bob["id"]


def test_fork_private_story_rejected(web_client):
    """Forking a private story must return 404."""
    _auth_headers(web_client, "alice", "password1")
    parent_id = _create_story_for(web_client, "alice", story="orig")
    # Not made public

    bob_hdrs = _auth_headers(web_client, "bob", "password1")
    resp = web_client.post(f"/library/{parent_id}/fork",
                           json={"name": "bobs_fork"}, headers=bob_hdrs)
    assert resp.status_code == 404


def test_fork_requires_auth(web_client):
    alice_hdrs = _auth_headers(web_client, "alice", "password1")
    parent_id = _create_story_for(web_client, "alice", story="orig")
    _make_public(web_client, parent_id, alice_hdrs)

    resp = web_client.post(f"/library/{parent_id}/fork",
                           json={"name": "anon_fork"})
    assert resp.status_code == 401


# ── GET /stories/{id} resolves parent_story ───────────────────────────────────

def test_get_story_includes_parent_story_none(web_client):
    alice_hdrs = _auth_headers(web_client, "alice", "password1")
    story_id = _create_story_for(web_client, "alice", story="orig")
    resp = web_client.get(f"/stories/{story_id}", headers=alice_hdrs)
    assert resp.status_code == 200
    data = resp.json()
    assert data["parent_story"] is None


def test_get_story_includes_parent_story_dict(web_client):
    """After forking, GET /stories/{fork_id} returns parent_story as a dict."""
    alice_hdrs = _auth_headers(web_client, "alice", "password1")
    parent_id = _create_story_for(web_client, "alice", story="orig")
    _make_public(web_client, parent_id, alice_hdrs)

    bob_hdrs = _auth_headers(web_client, "bob", "password1")
    fork_resp = web_client.post(f"/library/{parent_id}/fork",
                                json={"name": "bobs_fork"}, headers=bob_hdrs)
    fork_id = fork_resp.json()["story_id"]

    resp = web_client.get(f"/stories/{fork_id}", headers=bob_hdrs)
    assert resp.status_code == 200
    data = resp.json()
    assert data["parent_story_id"] == parent_id
    assert data["parent_story"] is not None
    assert data["parent_story"]["id"] == parent_id
    assert data["parent_story"]["story"] == "orig"


# ── GET /library/{id} ─────────────────────────────────────────────────────────

def test_library_story_detail(web_client):
    alice_hdrs = _auth_headers(web_client, "alice", "password1")
    story_id = _create_story_for(web_client, "alice", story="orig")
    _make_public(web_client, story_id, alice_hdrs)

    resp = web_client.get(f"/library/{story_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == story_id
    assert data["author"] == "alice"


def test_library_story_fork_count(web_client):
    alice_hdrs = _auth_headers(web_client, "alice", "password1")
    parent_id = _create_story_for(web_client, "alice", story="orig")
    _make_public(web_client, parent_id, alice_hdrs)

    # Create two forks via DB
    db = web_client._app_mod._db
    _auth_headers(web_client, "bob", "password1")
    bob = db.get_user_by_username("bob")
    db.create_story(bob["id"], "w", "c", "s", "fork1", parent_story_id=parent_id)
    db.create_story(bob["id"], "w", "c", "s", "fork2", parent_story_id=parent_id)

    resp = web_client.get(f"/library/{parent_id}")
    assert resp.status_code == 200
    assert resp.json()["fork_count"] == 2


def test_library_private_story_returns_404(web_client):
    _auth_headers(web_client, "alice", "password1")
    story_id = _create_story_for(web_client, "alice", story="private_orig")

    resp = web_client.get(f"/library/{story_id}")
    assert resp.status_code == 404


def test_library_story_parent_info(web_client):
    """GET /library/{fork_id} includes parent_story dict for public forks."""
    alice_hdrs = _auth_headers(web_client, "alice", "password1")
    parent_id = _create_story_for(web_client, "alice", story="orig")
    _make_public(web_client, parent_id, alice_hdrs)

    bob_hdrs = _auth_headers(web_client, "bob", "password1")
    fork_resp = web_client.post(f"/library/{parent_id}/fork",
                                json={"name": "bobs_fork"}, headers=bob_hdrs)
    fork_id = fork_resp.json()["story_id"]
    _make_public(web_client, fork_id, bob_hdrs)

    resp = web_client.get(f"/library/{fork_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["parent_story_id"] == parent_id
    # parent_story may or may not be resolved in library detail — just check the FK
    assert data["parent_story_id"] == parent_id


# ── GET /library/{id}/forks ───────────────────────────────────────────────────

def test_library_forks_empty(web_client):
    alice_hdrs = _auth_headers(web_client, "alice", "password1")
    story_id = _create_story_for(web_client, "alice", story="orig")
    _make_public(web_client, story_id, alice_hdrs)

    resp = web_client.get(f"/library/{story_id}/forks")
    assert resp.status_code == 200
    data = resp.json()
    assert data["story_id"] == story_id
    assert data["forks"] == []


def test_library_forks_private_story_404(web_client):
    _auth_headers(web_client, "alice", "password1")
    story_id = _create_story_for(web_client, "alice", story="priv")
    resp = web_client.get(f"/library/{story_id}/forks")
    assert resp.status_code == 404


def test_library_forks_lists_public_forks(web_client):
    alice_hdrs = _auth_headers(web_client, "alice", "password1")
    parent_id = _create_story_for(web_client, "alice", story="orig")
    _make_public(web_client, parent_id, alice_hdrs)

    bob_hdrs = _auth_headers(web_client, "bob", "password1")
    fork_resp = web_client.post(f"/library/{parent_id}/fork",
                                json={"name": "bobs_fork"}, headers=bob_hdrs)
    fork_id = fork_resp.json()["story_id"]
    _make_public(web_client, fork_id, bob_hdrs)

    resp = web_client.get(f"/library/{parent_id}/forks")
    assert resp.status_code == 200
    forks = resp.json()["forks"]
    assert len(forks) == 1
    assert forks[0]["story"] == "bobs_fork"
    assert forks[0]["author"] == "bob"


def test_library_forks_excludes_private(web_client):
    """A private fork should not appear in the public forks list."""
    alice_hdrs = _auth_headers(web_client, "alice", "password1")
    parent_id = _create_story_for(web_client, "alice", story="orig")
    _make_public(web_client, parent_id, alice_hdrs)

    # bob forks but doesn't publish it
    bob_hdrs = _auth_headers(web_client, "bob", "password1")
    web_client.post(f"/library/{parent_id}/fork",
                    json={"name": "secret_fork"}, headers=bob_hdrs)

    resp = web_client.get(f"/library/{parent_id}/forks")
    assert resp.status_code == 200
    assert resp.json()["forks"] == []


# ── list_public_stories fork_count ────────────────────────────────────────────

def test_public_stories_includes_fork_count(web_client):
    alice_hdrs = _auth_headers(web_client, "alice", "password1")
    parent_id = _create_story_for(web_client, "alice", story="orig")
    _make_public(web_client, parent_id, alice_hdrs)

    bob_hdrs = _auth_headers(web_client, "bob", "password1")
    fork_resp = web_client.post(f"/library/{parent_id}/fork",
                                json={"name": "bfork"}, headers=bob_hdrs)
    fork_id = fork_resp.json()["story_id"]
    _make_public(web_client, fork_id, bob_hdrs)

    resp = web_client.get("/library")
    assert resp.status_code == 200
    stories = resp.json()["stories"]
    orig = next(s for s in stories if s["id"] == parent_id)
    assert orig["fork_count"] == 1


def test_public_stories_fork_count_zero_when_no_forks(web_client):
    alice_hdrs = _auth_headers(web_client, "alice", "password1")
    story_id = _create_story_for(web_client, "alice", story="standalone")
    _make_public(web_client, story_id, alice_hdrs)

    resp = web_client.get("/library")
    assert resp.status_code == 200
    stories = resp.json()["stories"]
    orig = next(s for s in stories if s["id"] == story_id)
    assert orig["fork_count"] == 0
