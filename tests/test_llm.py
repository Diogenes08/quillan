"""Tests for LLMClient: caching, tier escalation, timeout, cost cap."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from quillan.config import Settings
from quillan.llm import LLMClient, LLMError
from quillan.telemetry import Telemetry


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_response(content: str = "test response", prompt_tokens: int = 10, completion_tokens: int = 5):
    """Build a minimal litellm-style response object."""
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens

    msg = MagicMock()
    msg.content = content

    choice = MagicMock()
    choice.message = msg

    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


def _make_client(tmp_path: Path, **settings_kwargs) -> tuple[LLMClient, Telemetry]:
    """Create an LLMClient with no-API-key settings (patched to have keys) and temp cache."""
    settings = Settings(
        data_dir=tmp_path,
        llm_cache=True,
        telemetry=False,
        **settings_kwargs,
    )
    # Patch has_api_keys so _call_once doesn't bail out early
    with patch.object(type(settings), "has_api_keys", new_callable=lambda: property(lambda s: True)):
        pass  # just checking the approach — we'll patch inline in each test

    tel = Telemetry(tmp_path / "runs", enabled=False)
    cache_dir = tmp_path / ".cache"
    client = LLMClient(settings, tel, cache_dir=cache_dir)
    return client, tel, settings


# ── Tests ──────────────────────────────────────────────────────────────────────

async def test_call_returns_text(tmp_path: Path):
    """Happy path: call() returns the LLM response text."""
    settings = Settings(data_dir=tmp_path, llm_cache=False, telemetry=False)
    tel = Telemetry(tmp_path / "runs", enabled=False)
    client = LLMClient(settings, tel, cache_dir=None)

    mock_resp = _make_response("hello from LLM")
    with (
        patch.object(type(settings), "has_api_keys", new_callable=lambda: property(lambda s: True)),
        patch("litellm.completion", return_value=mock_resp),
    ):
        result = await client.call("planning", "sys", "user")

    assert result == "hello from LLM"


async def test_call_caches_result(tmp_path: Path):
    """Two identical calls → litellm.completion called once (cache hit on second)."""
    settings = Settings(data_dir=tmp_path, llm_cache=True, telemetry=False)
    tel = Telemetry(tmp_path / "runs", enabled=False)
    client = LLMClient(settings, tel, cache_dir=tmp_path / ".cache")

    mock_resp = _make_response("cached response")
    with (
        patch.object(type(settings), "has_api_keys", new_callable=lambda: property(lambda s: True)),
        patch("litellm.completion", return_value=mock_resp) as mock_completion,
    ):
        r1 = await client.call("planning", "sys", "same user prompt")
        r2 = await client.call("planning", "sys", "same user prompt")

    assert r1 == r2 == "cached response"
    assert mock_completion.call_count == 1  # second call served from cache


async def test_call_cache_miss_different_prompt(tmp_path: Path):
    """Different prompts produce cache misses — litellm called twice."""
    settings = Settings(data_dir=tmp_path, llm_cache=True, telemetry=False)
    tel = Telemetry(tmp_path / "runs", enabled=False)
    client = LLMClient(settings, tel, cache_dir=tmp_path / ".cache")

    mock_resp = _make_response("response")
    with (
        patch.object(type(settings), "has_api_keys", new_callable=lambda: property(lambda s: True)),
        patch("litellm.completion", return_value=mock_resp) as mock_completion,
    ):
        await client.call("planning", "sys", "prompt A")
        await client.call("planning", "sys", "prompt B")

    assert mock_completion.call_count == 2


async def test_call_escalates_on_failure(tmp_path: Path):
    """Tier 0 raises; tier 1 succeeds → result from tier 1."""
    settings = Settings(
        data_dir=tmp_path, llm_cache=False, telemetry=False,
        stage_max_escalations=3,
    )
    tel = Telemetry(tmp_path / "runs", enabled=False)
    client = LLMClient(settings, tel, cache_dir=None)

    success_resp = _make_response("tier-1 response")
    call_count = 0

    def side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("tier 0 failed")
        return success_resp

    with (
        patch.object(type(settings), "has_api_keys", new_callable=lambda: property(lambda s: True)),
        patch("litellm.completion", side_effect=side_effect),
    ):
        result = await client.call("planning", "sys", "user")

    assert result == "tier-1 response"
    assert call_count == 2


async def test_call_raises_after_all_tiers_exhausted(tmp_path: Path):
    """If all tiers fail, LLMError is raised."""
    settings = Settings(
        data_dir=tmp_path, llm_cache=False, telemetry=False,
        stage_max_escalations=3, stage_max_retries=0,
    )
    tel = Telemetry(tmp_path / "runs", enabled=False)
    client = LLMClient(settings, tel, cache_dir=None)

    with (
        patch.object(type(settings), "has_api_keys", new_callable=lambda: property(lambda s: True)),
        patch("litellm.completion", side_effect=RuntimeError("all fail")),
        pytest.raises(LLMError, match="All tiers exhausted"),
    ):
        await client.call("planning", "sys", "user")


async def test_run_max_calls_cap(tmp_path: Path):
    """run_max_calls=1 → second call raises LLMError."""
    settings = Settings(
        data_dir=tmp_path, llm_cache=False, telemetry=False,
        run_max_calls=1, stage_max_escalations=0,
    )
    tel = Telemetry(tmp_path / "runs", enabled=False)
    client = LLMClient(settings, tel, cache_dir=None)

    mock_resp = _make_response("ok")
    with (
        patch.object(type(settings), "has_api_keys", new_callable=lambda: property(lambda s: True)),
        patch("litellm.completion", return_value=mock_resp),
    ):
        # First call succeeds
        await client.call("planning", "sys", "prompt 1")
        # Second call exceeds cap
        with pytest.raises(LLMError, match="cap"):
            await client.call("planning", "sys", "prompt 2")


async def test_call_timeout_raises(tmp_path: Path):
    """asyncio.wait_for timeout → LLMError containing 'timed out'."""
    settings = Settings(
        data_dir=tmp_path, llm_cache=False, telemetry=False,
        llm_call_timeout=1, stage_max_escalations=0, stage_max_retries=0,
    )
    tel = Telemetry(tmp_path / "runs", enabled=False)
    client = LLMClient(settings, tel, cache_dir=None)

    with (
        patch.object(type(settings), "has_api_keys", new_callable=lambda: property(lambda s: True)),
        patch("quillan.llm.asyncio.wait_for", side_effect=asyncio.TimeoutError()),
        pytest.raises(LLMError, match="timed out"),
    ):
        await client.call("planning", "sys", "user")


async def test_cost_cap_raises(tmp_path: Path):
    """run_max_cost_usd cap → LLMError containing 'cost cap'."""
    settings = Settings(
        data_dir=tmp_path, llm_cache=False, telemetry=True,
        run_max_cost_usd=0.0001,  # tiny cap — will be exceeded by any real call
        stage_max_escalations=0, stage_max_retries=0,
    )
    tel = Telemetry(tmp_path / "runs", enabled=True)
    client = LLMClient(settings, tel, cache_dir=None)

    # gpt-4o-mini: 0.15/1M input + 0.60/1M output
    # 1M input tokens → $0.15, way above $0.0001 cap
    big_resp = _make_response("response", prompt_tokens=1_000_000, completion_tokens=0)

    with (
        patch.object(type(settings), "has_api_keys", new_callable=lambda: property(lambda s: True)),
        patch("litellm.completion", return_value=big_resp),
        pytest.raises(LLMError, match="cost cap"),
    ):
        await client.call("planning", "sys", "user")
