"""Tests for M3: Telemetry visibility — cache hits, run summaries, CLI runs command."""

from __future__ import annotations

import json

import pytest

from quillan.telemetry import Telemetry


# ── record_cache_hit ──────────────────────────────────────────────────────────

def test_record_cache_hit_stored(tmp_path):
    t = Telemetry(tmp_path / "runs")
    t.record_cache_hit("draft", "xai", "grok-2-mini")
    assert len(t._cache_hits) == 1
    hit = t._cache_hits[0]
    assert hit["stage"] == "draft"
    assert hit["provider"] == "xai"
    assert hit["model"] == "grok-2-mini"
    assert "ts" in hit


def test_record_cache_hit_disabled(tmp_path):
    t = Telemetry(tmp_path / "runs", enabled=False)
    t.record_cache_hit("draft", "xai", "grok-2-mini")
    assert t._cache_hits == []


def test_record_multiple_cache_hits(tmp_path):
    t = Telemetry(tmp_path / "runs")
    t.record_cache_hit("planning", "openai", "gpt-4o-mini")
    t.record_cache_hit("draft", "xai", "grok-2")
    t.record_cache_hit("forensic", "gemini", "gemini-1.5-flash")
    assert len(t._cache_hits) == 3


# ── finalize includes cache_hits ──────────────────────────────────────────────

def test_finalize_includes_cache_hits(tmp_path):
    runs_dir = tmp_path / "runs"
    t = Telemetry(runs_dir)
    t.record_cache_hit("draft", "xai", "grok-2-mini")
    t.record_cache_hit("draft", "xai", "grok-2-mini")
    out = t.finalize()
    assert out is not None and out.exists()
    data = json.loads(out.read_text())
    assert data["cache_hits"] == 2


def test_finalize_cache_hits_zero_when_none(tmp_path):
    runs_dir = tmp_path / "runs"
    t = Telemetry(runs_dir)
    out = t.finalize()
    data = json.loads(out.read_text())
    assert data["cache_hits"] == 0


def test_finalize_disabled_returns_none(tmp_path):
    t = Telemetry(tmp_path / "runs", enabled=False)
    assert t.finalize() is None


# ── load_run_summaries ─────────────────────────────────────────────────────────

def test_load_run_summaries_empty_dir(tmp_path):
    result = Telemetry.load_run_summaries(tmp_path / "nonexistent")
    assert result == []


def test_load_run_summaries_reads_files(tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    summary = {"run_id": "20250312_100000_000000", "total_calls": 5, "cache_hits": 2}
    (runs_dir / "telemetry_20250312_100000_000000.json").write_text(json.dumps(summary))
    result = Telemetry.load_run_summaries(runs_dir)
    assert len(result) == 1
    assert result[0]["cache_hits"] == 2


def test_load_run_summaries_newest_first(tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    for i in range(3):
        ts = f"20250312_10000{i}_000000"
        (runs_dir / f"telemetry_{ts}.json").write_text(json.dumps({"run_id": ts}))
    result = Telemetry.load_run_summaries(runs_dir)
    assert result[0]["run_id"] > result[1]["run_id"] > result[2]["run_id"]


def test_load_run_summaries_limit(tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    for i in range(10):
        ts = f"20250312_1000{i:02d}_000000"
        (runs_dir / f"telemetry_{ts}.json").write_text(json.dumps({"run_id": ts}))
    result = Telemetry.load_run_summaries(runs_dir, limit=3)
    assert len(result) == 3


def test_load_run_summaries_skips_malformed(tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    (runs_dir / "telemetry_20250312_100000_000000.json").write_text("{bad json")
    (runs_dir / "telemetry_20250312_100001_000000.json").write_text('{"run_id": "ok"}')
    result = Telemetry.load_run_summaries(runs_dir)
    assert len(result) == 1
    assert result[0]["run_id"] == "ok"


# ── web endpoint ─────────────────────────────────────────────────────────────

@pytest.fixture
def _web_client(tmp_path, monkeypatch):
    import quillan.web.app as _app
    monkeypatch.setattr(_app, "_data_dir", tmp_path)
    monkeypatch.setattr(_app, "_db_path", tmp_path / ".web" / "test.db")
    import bcrypt as _bcrypt
    monkeypatch.setattr(_bcrypt, "checkpw", lambda pw, hashed: True)
    monkeypatch.setattr(_bcrypt, "hashpw", lambda pw, salt: b"$2b$12$fakehash")
    import quillan.web.auth as _auth
    monkeypatch.setattr(_auth, "verify_password", lambda plain, hashed: True)
    from fastapi.testclient import TestClient
    with TestClient(_app.app) as client:
        yield client


def test_web_runs_endpoint_admin_only(_web_client):
    """Non-admin user should get 403 from /runs."""
    _web_client.post("/auth/register", json={"username": "admin", "password": "password1"})
    _web_client.post("/auth/register", json={"username": "user", "password": "password1"})
    resp = _web_client.post("/auth/login", data={"username": "user", "password": "password1"})
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    r = _web_client.get("/runs", headers=headers)
    assert r.status_code == 403


def test_web_runs_endpoint_admin_ok(_web_client):
    """Admin user should get 200 with runs list."""
    _web_client.post("/auth/register", json={"username": "admin", "password": "password1"})
    resp = _web_client.post("/auth/login", data={"username": "admin", "password": "password1"})
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    r = _web_client.get("/runs", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert "runs" in body
    assert "total" in body
