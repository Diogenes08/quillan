"""Data-directory migration system for Quillan2.

Tracks a single integer version in ``<data_dir>/.quillan_version``.
On startup, ``run_migrations(data_dir)`` applies any pending migrations
in order and updates the version marker.

Adding a new migration:
1. Increment ``DATA_VERSION``.
2. Add a ``_migrate_N`` function (where N == DATA_VERSION).
3. Register it in ``_MIGRATIONS``.
"""

from __future__ import annotations

import logging
from pathlib import Path

_log = logging.getLogger("quillan.migrate")

# Bump this whenever a new migration is added.
DATA_VERSION: int = 1

_VERSION_FILE = ".quillan_version"


# ── Migration functions ───────────────────────────────────────────────────────
# Each function migrates from version (N-1) → N.
# They must be idempotent — safe to re-run if interrupted.


def _migrate_1(data_dir: Path) -> None:
    """Version 1 — baseline; no filesystem transforms required."""
    # This migration exists to stamp the version marker on existing data dirs
    # that pre-date the migration system.  All structural invariants were
    # already enforced by Paths.ensure() and init_schema() at runtime.


# ── Registry ─────────────────────────────────────────────────────────────────
# Keys are the TARGET version produced by each function.
_MIGRATIONS: dict[int, callable] = {
    1: _migrate_1,
}


# ── Public API ────────────────────────────────────────────────────────────────


def _read_version(data_dir: Path) -> int:
    """Return the current data-dir version (0 if marker absent)."""
    marker = data_dir / _VERSION_FILE
    if not marker.exists():
        return 0
    try:
        return int(marker.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return 0


def _write_version(data_dir: Path, version: int) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / _VERSION_FILE).write_text(str(version), encoding="utf-8")


def run_migrations(data_dir: Path) -> None:
    """Apply all pending migrations to *data_dir* and update the version marker.

    Safe to call on every startup — skips already-applied migrations.
    Logs a warning and re-raises on migration failure.
    """
    data_dir = Path(data_dir)
    current = _read_version(data_dir)

    if current == DATA_VERSION:
        return  # nothing to do

    if current > DATA_VERSION:
        _log.warning(
            "Data directory version %d is newer than this build (%d). "
            "Upgrade Quillan2 or check your data_dir.",
            current,
            DATA_VERSION,
        )
        return

    for target in range(current + 1, DATA_VERSION + 1):
        fn = _MIGRATIONS.get(target)
        if fn is None:
            _log.error("No migration registered for version %d — skipping.", target)
            continue
        _log.info("Applying data migration %d → %d …", target - 1, target)
        try:
            fn(data_dir)
        except Exception:
            _log.exception("Migration to version %d FAILED — data_dir may be inconsistent.", target)
            raise
        _write_version(data_dir, target)
        _log.info("Migration to version %d complete.", target)
