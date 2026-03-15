"""Shared pytest fixtures for Quillan2 tests."""

from __future__ import annotations

import pytest
from pathlib import Path


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Temporary data directory for tests."""
    d = tmp_path / "quillan_data"
    d.mkdir()
    return d


@pytest.fixture
def paths(data_dir: Path):
    """Paths instance pointing to tmp data dir."""
    from quillan.paths import Paths
    return Paths(data_dir)


@pytest.fixture
def settings(data_dir: Path):
    """Settings with temp data dir, no API keys."""
    from quillan.config import Settings
    return Settings(data_dir=data_dir, llm_cache=False, telemetry=False)


@pytest.fixture
def world() -> str:
    return "testworld"


@pytest.fixture
def canon() -> str:
    return "default"


@pytest.fixture
def series() -> str:
    return "default"


@pytest.fixture
def story() -> str:
    return "teststory"
