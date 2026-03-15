"""Tests for quillan.config — Settings env loading and derived properties."""

from __future__ import annotations

import os
from pathlib import Path


from quillan.config import Settings


def test_defaults():
    s = Settings()
    assert s.max_parallel == 3
    assert s.max_prompt_tokens == 32768
    assert s.continuity_last_beats_n == 5
    assert s.llm_cache is True
    assert s.distill_continuity is False


def test_data_dir_is_path():
    s = Settings(data_dir=Path("/tmp/test"))
    assert isinstance(s.data_dir, Path)


def test_has_api_keys_false_by_default():
    s = Settings()
    # In test environment, keys are unlikely to be set
    if not any([
        os.environ.get("OPENAI_API_KEY"),
        os.environ.get("XAI_API_KEY"),
        os.environ.get("GEMINI_API_KEY"),
    ]):
        assert s.has_api_keys is False


def test_has_api_keys_true_when_set(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    s = Settings()
    assert s.has_api_keys is True


def test_model_for_stage_planning():
    s = Settings()
    assert s.model_for_stage("planning", 0) == "gpt-4o-mini"   # budget
    assert s.model_for_stage("planning", 1) == "gpt-4o"         # quality escalation
    assert s.model_for_stage("planning", 2) == "grok-2"          # cross-provider
    assert s.model_for_stage("planning", 3) == "gemini-1.5-pro"  # last-resort


def test_model_for_stage_draft():
    s = Settings()
    assert s.model_for_stage("draft", 0) == "grok-2-mini"       # budget
    assert s.model_for_stage("draft", 1) == "grok-2"             # quality escalation
    assert s.model_for_stage("draft", 2) == "gpt-4o"             # cross-provider
    assert s.model_for_stage("draft", 3) == "gemini-1.5-pro"     # last-resort


def test_model_for_stage_forensic():
    s = Settings()
    assert s.model_for_stage("forensic", 0) == "gemini-1.5-flash"  # budget
    assert s.model_for_stage("forensic", 1) == "gemini-1.5-pro"    # quality escalation
    assert s.model_for_stage("forensic", 2) == "gpt-4o"             # cross-provider
    assert s.model_for_stage("forensic", 3) == "grok-2"              # last-resort


def test_model_for_stage_clamps_tier():
    """Tier values outside 0-3 should be clamped."""
    s = Settings()
    assert s.model_for_stage("planning", -1) == s.model_for_stage("planning", 0)
    assert s.model_for_stage("planning", 99) == s.model_for_stage("planning", 3)


def test_provider_for_stage():
    s = Settings()
    # Tier 0 (budget): each stage uses its primary provider
    assert s.provider_for_stage("planning", 0) == "openai"
    assert s.provider_for_stage("draft", 0) == "xai"
    assert s.provider_for_stage("forensic", 0) == "gemini"
    # Tier 2 (cross-provider escape)
    assert s.provider_for_stage("planning", 2) == "xai"
    assert s.provider_for_stage("draft", 2) == "openai"
    assert s.provider_for_stage("forensic", 2) == "openai"


def test_provider_for_stage_struct_inherits():
    """struct stage should inherit planning tier when struct fields are empty."""
    s = Settings(struct_tier0_provider="")
    assert s.provider_for_stage("struct", 0) == "openai"


def test_provider_for_stage_struct_override():
    s = Settings(struct_tier0_provider="gemini")
    assert s.provider_for_stage("struct", 0) == "gemini"


def test_litellm_model_string_openai():
    s = Settings()
    assert s.litellm_model_string("planning", 0) == "gpt-4o-mini"


def test_litellm_model_string_xai():
    s = Settings()
    result = s.litellm_model_string("draft", 0)
    assert result == "openai/grok-2-mini"


def test_litellm_model_string_gemini():
    s = Settings()
    result = s.litellm_model_string("forensic", 0)
    assert result == "gemini/gemini-1.5-flash"


def test_litellm_model_string_cross_provider():
    """Tier 2 for planning (xAI) should produce openai/ prefix."""
    s = Settings()
    assert s.litellm_model_string("planning", 2) == "openai/grok-2"


def test_litellm_kwargs_xai():
    s = Settings(xai_api_key="xai-test-key")
    kw = s.litellm_kwargs("draft", 0)
    assert kw["api_base"] == "https://api.x.ai/v1"
    assert kw["api_key"] == "xai-test-key"


def test_litellm_kwargs_gemini():
    s = Settings(gemini_api_key="gai-test")
    kw = s.litellm_kwargs("forensic", 0)
    assert kw["api_key"] == "gai-test"


def test_litellm_kwargs_tier2_switches_provider():
    """Tier 2 for draft is openai, so kwargs should not have api_base."""
    s = Settings(openai_api_key="sk-test")
    kw = s.litellm_kwargs("draft", 2)
    assert "api_base" not in kw
    assert kw.get("api_key") == "sk-test"


def test_env_override_max_parallel(monkeypatch):
    monkeypatch.setenv("QUILLAN_MAX_PARALLEL", "8")
    s = Settings()
    assert s.max_parallel == 8


def test_env_override_distill(monkeypatch):
    monkeypatch.setenv("QUILLAN_DISTILL_CONTINUITY", "true")
    s = Settings()
    assert s.distill_continuity is True


# ── M2: Local LLM (api_base) tests ───────────────────────────────────────────

def test_has_api_keys_true_with_local_base():
    """Local api_base counts as 'has keys' — enables full pipeline without cloud keys."""
    s = Settings(draft_api_base="http://localhost:11434")
    assert s.has_api_keys is True


def test_has_api_keys_false_no_local_base_no_keys():
    """No cloud keys and no api_base → offline stub mode."""
    s = Settings(
        openai_api_key="", xai_api_key="", gemini_api_key="",
        planning_api_base="", draft_api_base="", forensic_api_base="", struct_api_base="",
    )
    # Only valid in environments where env vars are also absent
    import os
    if not any(os.environ.get(k) for k in ("OPENAI_API_KEY", "XAI_API_KEY", "GEMINI_API_KEY")):
        assert s.has_api_keys is False


def test_litellm_kwargs_local_base_overrides_provider():
    """Per-stage api_base should take priority over provider-default api_base."""
    s = Settings(draft_api_base="http://localhost:11434", xai_api_key="key")
    kw = s.litellm_kwargs("draft", 0)
    assert kw == {"api_base": "http://localhost:11434"}
    assert "api_key" not in kw


def test_litellm_kwargs_local_base_planning():
    s = Settings(planning_api_base="http://localhost:8080/v1")
    kw = s.litellm_kwargs("planning", 0)
    assert kw["api_base"] == "http://localhost:8080/v1"


def test_litellm_kwargs_local_base_forensic():
    s = Settings(forensic_api_base="http://vllm:8000/v1")
    kw = s.litellm_kwargs("forensic", 0)
    assert kw["api_base"] == "http://vllm:8000/v1"


def test_litellm_kwargs_no_local_base_uses_provider():
    """Without local base, provider logic (xAI url) still applies."""
    s = Settings(draft_api_base="", xai_api_key="xai-test")
    kw = s.litellm_kwargs("draft", 0)
    assert kw["api_base"] == "https://api.x.ai/v1"


def test_override_blocked_contains_api_bases():
    from quillan.config import _OVERRIDE_BLOCKED
    assert "planning_api_base" in _OVERRIDE_BLOCKED
    assert "draft_api_base" in _OVERRIDE_BLOCKED
    assert "forensic_api_base" in _OVERRIDE_BLOCKED
    assert "struct_api_base" in _OVERRIDE_BLOCKED


# ── F1: Anthropic provider ────────────────────────────────────────────────────

def test_litellm_model_string_anthropic():
    """Anthropic provider returns the model name directly (no prefix)."""
    s = Settings(
        draft_tier0_provider="anthropic",
        draft_tier0_model="claude-sonnet-4-6",
    )
    assert s.litellm_model_string("draft", 0) == "claude-sonnet-4-6"


def test_litellm_kwargs_anthropic_with_key():
    """Anthropic provider passes api_key when set."""
    s = Settings(
        draft_tier0_provider="anthropic",
        draft_tier0_model="claude-sonnet-4-6",
        anthropic_api_key="sk-ant-test",
    )
    kw = s.litellm_kwargs("draft", 0)
    assert kw.get("api_key") == "sk-ant-test"
    assert "api_base" not in kw


def test_litellm_kwargs_anthropic_no_key():
    """Anthropic provider with no key returns empty dict (lets env var take over)."""
    s = Settings(
        draft_tier0_provider="anthropic",
        draft_tier0_model="claude-sonnet-4-6",
        anthropic_api_key="",
    )
    kw = s.litellm_kwargs("draft", 0)
    assert kw == {}


def test_has_api_keys_true_with_anthropic_key():
    """anthropic_api_key alone satisfies has_api_keys."""
    s = Settings(anthropic_api_key="sk-ant-test")
    assert s.has_api_keys is True


def test_anthropic_api_key_override_blocked():
    """anthropic_api_key must not be settable via quillan.yaml overrides."""
    from quillan.config import _OVERRIDE_BLOCKED
    assert "anthropic_api_key" in _OVERRIDE_BLOCKED


def test_anthropic_api_key_reads_env(monkeypatch):
    """ANTHROPIC_API_KEY environment variable is picked up automatically."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")
    s = Settings(anthropic_api_key="")
    assert s.anthropic_api_key == "sk-ant-from-env"
