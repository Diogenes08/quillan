"""Tests for quillan.migrate data-directory migration system."""

from __future__ import annotations


import pytest

from quillan.migrate import (
    DATA_VERSION,
    _VERSION_FILE,
    _read_version,
    _write_version,
    run_migrations,
)


# ── Version file helpers ───────────────────────────────────────────────────────


def test_read_version_absent_returns_zero(tmp_path):
    assert _read_version(tmp_path) == 0


def test_read_version_after_write(tmp_path):
    _write_version(tmp_path, 3)
    assert _read_version(tmp_path) == 3


def test_read_version_corrupt_file_returns_zero(tmp_path):
    (tmp_path / _VERSION_FILE).write_text("not-a-number", encoding="utf-8")
    assert _read_version(tmp_path) == 0


# ── run_migrations ─────────────────────────────────────────────────────────────


def test_run_migrations_stamps_version(tmp_path):
    """Fresh data dir (version 0) gets stamped to DATA_VERSION."""
    run_migrations(tmp_path)
    assert _read_version(tmp_path) == DATA_VERSION


def test_run_migrations_idempotent(tmp_path):
    """Calling run_migrations twice is safe and leaves version unchanged."""
    run_migrations(tmp_path)
    run_migrations(tmp_path)
    assert _read_version(tmp_path) == DATA_VERSION


def test_run_migrations_already_at_current_version(tmp_path):
    """If already at DATA_VERSION, nothing changes."""
    _write_version(tmp_path, DATA_VERSION)
    run_migrations(tmp_path)
    assert _read_version(tmp_path) == DATA_VERSION


def test_run_migrations_newer_version_logs_warning(tmp_path, caplog):
    """A data dir newer than the build emits a warning and does not downgrade."""
    future_version = DATA_VERSION + 5
    _write_version(tmp_path, future_version)
    import logging
    with caplog.at_level(logging.WARNING, logger="quillan.migrate"):
        run_migrations(tmp_path)
    assert any("newer" in r.message for r in caplog.records)
    # Version must not be downgraded
    assert _read_version(tmp_path) == future_version


def test_run_migrations_creates_data_dir_if_absent(tmp_path):
    """run_migrations creates the data_dir if it doesn't exist yet."""
    new_dir = tmp_path / "brand_new"
    assert not new_dir.exists()
    run_migrations(new_dir)
    assert new_dir.exists()
    assert _read_version(new_dir) == DATA_VERSION


def test_run_migrations_failure_reraises(tmp_path, monkeypatch):
    """If a migration function raises, run_migrations re-raises."""
    import quillan.migrate as _m

    # Temporarily add a broken migration at DATA_VERSION + 1
    original_version = _m.DATA_VERSION
    original_migrations = dict(_m._MIGRATIONS)
    _m.DATA_VERSION = original_version + 1
    _m._MIGRATIONS[original_version + 1] = lambda _: (_ for _ in ()).throw(RuntimeError("boom"))

    try:
        _write_version(tmp_path, original_version)
        with pytest.raises(RuntimeError, match="boom"):
            run_migrations(tmp_path)
    finally:
        _m.DATA_VERSION = original_version
        _m._MIGRATIONS.clear()
        _m._MIGRATIONS.update(original_migrations)
