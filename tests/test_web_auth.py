"""Unit tests for quillan.web.auth — JWT and bcrypt functions."""

from __future__ import annotations

import time
from datetime import timedelta

import pytest


# ── hash_password / verify_password ───────────────────────────────────────────


def test_hash_password_returns_bcrypt_hash():
    from quillan.web.auth import hash_password

    hashed = hash_password("secret123")
    # bcrypt hashes always start with $2b$ (or $2a$)
    assert hashed.startswith("$2")


def test_verify_password_correct():
    from quillan.web.auth import hash_password, verify_password

    hashed = hash_password("correct")
    assert verify_password("correct", hashed) is True


def test_verify_password_wrong():
    from quillan.web.auth import hash_password, verify_password

    hashed = hash_password("correct")
    assert verify_password("wrong", hashed) is False


# ── create_access_token / decode_token ────────────────────────────────────────


def test_create_and_decode_token_roundtrip():
    from quillan.web.auth import create_access_token, decode_token

    payload = {"sub": "42", "extra": "data"}
    token = create_access_token(payload)
    decoded = decode_token(token)

    assert decoded["sub"] == "42"
    assert decoded["extra"] == "data"
    assert "exp" in decoded


def test_token_with_custom_expiry():
    from quillan.web.auth import create_access_token, decode_token

    token = create_access_token({"sub": "1"}, expires_delta=timedelta(hours=1))
    decoded = decode_token(token)
    # Expiry should be roughly 1 hour from now (within 10 seconds tolerance)
    remaining = decoded["exp"] - time.time()
    assert 3580 < remaining < 3610


def test_decode_expired_token_raises():
    from quillan.web.auth import create_access_token, decode_token

    # Token that expired a minute ago
    token = create_access_token({"sub": "1"}, expires_delta=timedelta(seconds=-60))
    with pytest.raises(ValueError, match="Invalid token"):
        decode_token(token)


def test_decode_garbage_raises():
    from quillan.web.auth import decode_token

    with pytest.raises(ValueError, match="Invalid token"):
        decode_token("not.a.valid.jwt")


def test_decode_tampered_signature_raises():
    from quillan.web.auth import create_access_token, decode_token

    token = create_access_token({"sub": "99"})
    # Corrupt the signature (last segment)
    parts = token.split(".")
    parts[-1] = parts[-1][::-1]  # reverse it
    bad_token = ".".join(parts)
    with pytest.raises(ValueError):
        decode_token(bad_token)


# ── Default-secret warning ────────────────────────────────────────────────────


def test_default_secret_warning_logged(caplog):
    """When QUILLAN_JWT_SECRET is unset the module should emit a WARNING."""
    import logging

    with caplog.at_level(logging.WARNING, logger="quillan.web.auth"):
        import importlib
        import quillan.web.auth as auth_module
        # The warning fires at module import time — it will already have been
        # emitted if the module was loaded without the env var.  Reload to
        # trigger it in a controlled environment.
        import os
        original = os.environ.pop("QUILLAN_JWT_SECRET", None)
        try:
            importlib.reload(auth_module)
        finally:
            if original is not None:
                os.environ["QUILLAN_JWT_SECRET"] = original

    assert any("QUILLAN_JWT_SECRET" in r.message for r in caplog.records)
