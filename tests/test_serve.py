"""Tests for the 'serve' command JWT secret guard."""

from __future__ import annotations

import os
from unittest.mock import patch

from click.testing import CliRunner

_DEFAULT_SECRET = "dev-secret-change-in-production"


def test_serve_refuses_when_no_jwt_secret_set():
    """serve exits non-zero when QUILLAN_JWT_SECRET is absent (defaults to insecure value)."""
    from quillan.cli import main

    runner = CliRunner()
    with patch.dict(os.environ, {"QUILLAN_JWT_SECRET": _DEFAULT_SECRET}):
        result = runner.invoke(main, ["serve"])

    assert result.exit_code != 0
    assert "QUILLAN_JWT_SECRET" in result.output


def test_serve_error_message_contains_hint():
    """The error message tells the user how to fix the problem."""
    from quillan.cli import main

    runner = CliRunner()
    with patch.dict(os.environ, {"QUILLAN_JWT_SECRET": _DEFAULT_SECRET}):
        result = runner.invoke(main, ["serve"])

    assert "openssl" in result.output or "--dev" in result.output


def test_serve_dev_flag_warns_and_starts(tmp_path):
    """--dev allows starting with the default secret but prints a warning."""
    from quillan.cli import main

    runner = CliRunner()
    with patch.dict(os.environ, {"QUILLAN_JWT_SECRET": _DEFAULT_SECRET}):
        with patch("uvicorn.run"):
            result = runner.invoke(main, ["--data-dir", str(tmp_path), "serve", "--dev"])

    assert result.exit_code == 0
    assert "Warning" in result.output


def test_serve_custom_secret_starts_without_warning(tmp_path):
    """A non-default JWT secret allows serve to start with no warning."""
    from quillan.cli import main

    runner = CliRunner()
    with patch.dict(os.environ, {"QUILLAN_JWT_SECRET": "a-genuinely-secret-key-xyz789"}):
        with patch("uvicorn.run"):
            result = runner.invoke(main, ["--data-dir", str(tmp_path), "serve"])

    assert result.exit_code == 0
    assert "Warning" not in result.output
