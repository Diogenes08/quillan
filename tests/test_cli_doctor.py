"""Tests for M5: quillan doctor command."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from quillan.cli import main


@pytest.fixture
def runner():
    return CliRunner()


def _invoke(runner, args, **kwargs):
    return runner.invoke(main, args, catch_exceptions=False, **kwargs)


# ── Basic invocation ──────────────────────────────────────────────────────────

def test_doctor_runs_without_error(runner, tmp_path):
    result = _invoke(runner, ["--data-dir", str(tmp_path), "doctor"])
    assert result.exit_code in (0, 1)  # 0=all ok, 1=some FAIL
    assert "Doctor summary:" in result.output
    assert "[OK]" in result.output or "[WARN]" in result.output or "[FAIL]" in result.output


def test_doctor_output_sections(runner, tmp_path):
    result = _invoke(runner, ["--data-dir", str(tmp_path), "doctor"])
    assert "Python:" in result.output
    assert "Required packages:" in result.output
    assert "Optional packages:" in result.output
    assert "External tools:" in result.output
    assert "API keys:" in result.output
    assert "Data directory:" in result.output
    assert "Disk space:" in result.output


def test_doctor_python_version_ok(runner, tmp_path):
    result = _invoke(runner, ["--data-dir", str(tmp_path), "doctor"])
    # We're running on Python 3.10+ so this must show OK
    assert "[OK]" in result.output
    assert "Python" in result.output


def test_doctor_data_dir_writable(runner, tmp_path):
    result = _invoke(runner, ["--data-dir", str(tmp_path), "doctor"])
    assert "writable" in result.output


def test_doctor_exits_1_on_fail(runner, tmp_path):
    """Simulate a missing required package → exit code 1."""
    import builtins
    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "litellm":
            raise ImportError("no module named litellm")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        result = runner.invoke(main, ["--data-dir", str(tmp_path), "doctor"], catch_exceptions=False)
    assert result.exit_code == 1
    assert "FAIL" in result.output


def test_doctor_disk_space_check(runner, tmp_path):
    """disk_usage returning low space → WARN in output."""
    mock_usage = MagicMock()
    mock_usage.free = 512 * 1024 * 1024  # 0.5 GB

    with patch("shutil.disk_usage", return_value=mock_usage):
        result = _invoke(runner, ["--data-dir", str(tmp_path), "doctor"])
    assert "WARN" in result.output
    assert "0.50 GB free" in result.output or "0.5" in result.output


def test_doctor_external_tools_missing(runner, tmp_path):
    """If pandoc absent → WARN (not FAIL)."""
    with patch("shutil.which", return_value=None):
        result = _invoke(runner, ["--data-dir", str(tmp_path), "doctor"])
    assert "[WARN]" in result.output
    # Should still exit 0 or 1 (depending on keys), not crash
    assert result.exit_code in (0, 1)


def test_doctor_summary_line_format(runner, tmp_path):
    result = _invoke(runner, ["--data-dir", str(tmp_path), "doctor"])
    lines = result.output.splitlines()
    summary = next((line for line in lines if line.startswith("Doctor summary:")), None)
    assert summary is not None
    assert "OK" in summary
    assert "WARN" in summary
    assert "FAIL" in summary
