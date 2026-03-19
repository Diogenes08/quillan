"""Tests for quillan.config — Settings env loading and derived properties."""

from __future__ import annotations

import os
from pathlib import Path


from quillan.config import Settings


# Tests that verify code defaults must not load quillan.env (which the developer
# may have customised). _S() creates Settings without reading any env files —
# only explicit kwargs and environment variables (monkeypatch.setenv) apply.
def _S(**kw) -> Settings:
    return Settings(_env_file=(), **kw)


def test_defaults():
    s = _S()
    assert s.max_parallel == 3
    assert s.max_prompt_tokens == 32768
    assert s.continuity_last_beats_n == 5
    assert s.llm_cache is True
    assert s.distill_continuity is False


def test_data_dir_is_path():
    s = Settings(data_dir=Path("/tmp/test"))
    assert isinstance(s.data_dir, Path)


def test_has_api_keys_false_by_default():
    s = _S()
    # In test environment, keys are unlikely to be set
    if not any([
        os.environ.get("OPENAI_API_KEY"),
        os.environ.get("XAI_API_KEY"),
        os.environ.get("GEMINI_API_KEY"),
    ]):
        assert s.has_api_keys is False


def test_has_api_keys_true_when_set(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    s = _S()
    assert s.has_api_keys is True


def test_model_for_stage_planning():
    s = _S()
    assert s.model_for_stage("planning", 0) == "gpt-4.1"          # quality default
    assert s.model_for_stage("planning", 1) == "gpt-4.1-mini"     # cost fallback
    assert s.model_for_stage("planning", 2) == "grok-3"            # cross-provider
    assert s.model_for_stage("planning", 3) == "gemini-2.5-pro"   # last-resort


def test_model_for_stage_draft():
    s = _S()
    assert s.model_for_stage("draft", 0) == "grok-3"              # quality default
    assert s.model_for_stage("draft", 1) == "grok-3-mini"         # cost fallback
    assert s.model_for_stage("draft", 2) == "gpt-4.1"             # cross-provider
    assert s.model_for_stage("draft", 3) == "gemini-2.5-pro"      # last-resort


def test_model_for_stage_forensic():
    s = _S()
    assert s.model_for_stage("forensic", 0) == "gemini-2.5-pro"   # quality default
    assert s.model_for_stage("forensic", 1) == "gemini-2.0-flash"  # cost fallback
    assert s.model_for_stage("forensic", 2) == "gpt-4.1"           # cross-provider
    assert s.model_for_stage("forensic", 3) == "grok-3"             # last-resort


def test_model_for_stage_clamps_tier():
    """Tier values outside 0-3 should be clamped."""
    s = _S()
    assert s.model_for_stage("planning", -1) == s.model_for_stage("planning", 0)
    assert s.model_for_stage("planning", 99) == s.model_for_stage("planning", 3)


def test_provider_for_stage():
    s = _S()
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
    s = _S(struct_tier0_provider="")
    assert s.provider_for_stage("struct", 0) == "openai"


def test_provider_for_stage_struct_override():
    s = _S(struct_tier0_provider="gemini")
    assert s.provider_for_stage("struct", 0) == "gemini"


def test_litellm_model_string_openai():
    s = _S()
    assert s.litellm_model_string("planning", 0) == "gpt-4.1"


def test_litellm_model_string_xai():
    s = _S()
    result = s.litellm_model_string("draft", 0)
    assert result == "openai/grok-3"


def test_litellm_model_string_gemini():
    s = _S()
    result = s.litellm_model_string("forensic", 0)
    assert result == "gemini/gemini-2.5-pro"


def test_litellm_model_string_cross_provider():
    """Tier 2 for planning (xAI) should produce openai/ prefix."""
    s = _S()
    assert s.litellm_model_string("planning", 2) == "openai/grok-3"


def test_litellm_kwargs_xai():
    s = _S(xai_api_key="xai-test-key")
    kw = s.litellm_kwargs("draft", 0)
    assert kw["api_base"] == "https://api.x.ai/v1"
    assert kw["api_key"] == "xai-test-key"


def test_litellm_kwargs_gemini():
    s = _S(gemini_api_key="gai-test")
    kw = s.litellm_kwargs("forensic", 0)
    assert kw["api_key"] == "gai-test"


def test_litellm_kwargs_tier2_switches_provider():
    """Tier 2 for draft is openai, so kwargs should not have api_base."""
    s = _S(openai_api_key="sk-test")
    kw = s.litellm_kwargs("draft", 2)
    assert "api_base" not in kw
    assert kw.get("api_key") == "sk-test"


# ── Preset tests ──────────────────────────────────────────────────────────────

def test_preset_quality_sets_group():
    s = _S(preset="quality")
    assert s.max_parallel == 2
    assert s.max_prompt_tokens == 65536
    assert s.distill_continuity is True
    assert s.continuity_last_beats_n == 10
    assert s.draft_audit_retries == 2


def test_preset_budget_swaps_models():
    s = _S(preset="budget")
    assert s.planning_tier0_model == "gpt-4.1-mini"
    assert s.draft_tier0_model == "grok-3-mini"
    assert s.forensic_tier0_model == "gemini-2.0-flash"
    assert s.max_parallel == 2
    assert s.draft_audit_retries == 0


def test_preset_fast_maximises_parallel():
    s = _S(preset="fast")
    assert s.max_parallel == 6
    assert s.stage_max_retries == 0


def test_preset_balanced_matches_defaults():
    """The 'balanced' preset should produce the same values as no preset."""
    plain = _S()
    balanced = _S(preset="balanced")
    assert balanced.max_parallel == plain.max_parallel
    assert balanced.max_prompt_tokens == plain.max_prompt_tokens
    assert balanced.distill_continuity == plain.distill_continuity


def test_preset_explicit_override_wins():
    """An explicit kwarg must beat whatever the preset would set."""
    s = _S(preset="quality", max_parallel=8)
    assert s.max_parallel == 8          # explicit wins
    assert s.distill_continuity is True  # preset still applied for other keys


def test_preset_unknown_is_ignored(caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="quillan.config"):
        s = _S(preset="nonexistent")
    assert s.max_parallel == 3   # unchanged defaults
    assert "Unknown QUILLAN_PRESET" in caplog.text


def test_preset_case_insensitive():
    s = _S(preset="QUALITY")
    assert s.distill_continuity is True


def test_preset_empty_string_is_noop():
    s = _S(preset="")
    assert s.max_parallel == 3   # unaffected default


def test_preset_overrides_dotenv_value(monkeypatch, tmp_path):
    """Preset must win over a value explicitly written in quillan.env.

    This is the core behaviour the user asked for: adding QUILLAN_PRESET=quality
    to quillan.env should override QUILLAN_MAX_PARALLEL=3 in the same file.
    """
    env_file = tmp_path / "quillan.env"
    env_file.write_text("QUILLAN_PRESET=quality\nQUILLAN_MAX_PARALLEL=3\n")
    # Load using the temp env file directly (not _S, which disables env files)
    s = Settings(_env_file=str(env_file), data_dir=tmp_path)
    # quality preset sets max_parallel=2; the quillan.env value of 3 must lose
    assert s.max_parallel == 2
    assert s.distill_continuity is True   # other preset values also applied


def test_shell_env_var_overrides_preset(monkeypatch, tmp_path):
    """Shell env var must beat the preset (highest priority)."""
    monkeypatch.setenv("QUILLAN_MAX_PARALLEL", "7")
    s = _S(preset="quality")   # quality would set max_parallel=2
    assert s.max_parallel == 7  # shell wins


def test_env_override_max_parallel(monkeypatch):
    monkeypatch.setenv("QUILLAN_MAX_PARALLEL", "8")
    s = _S()
    assert s.max_parallel == 8


def test_env_override_distill(monkeypatch):
    monkeypatch.setenv("QUILLAN_DISTILL_CONTINUITY", "true")
    s = _S()
    assert s.distill_continuity is True


# ── M2: Local LLM (api_base) tests ───────────────────────────────────────────

def test_has_api_keys_true_with_local_base():
    """Local api_base counts as 'has keys' — enables full pipeline without cloud keys."""
    s = _S(draft_api_base="http://localhost:11434")
    assert s.has_api_keys is True


def test_has_api_keys_false_no_local_base_no_keys():
    """No cloud keys and no api_base → offline stub mode."""
    s = _S(
        openai_api_key="", xai_api_key="", gemini_api_key="",
        planning_api_base="", draft_api_base="", forensic_api_base="", struct_api_base="",
    )
    # Only valid in environments where env vars are also absent
    import os
    if not any(os.environ.get(k) for k in ("OPENAI_API_KEY", "XAI_API_KEY", "GEMINI_API_KEY")):
        assert s.has_api_keys is False


def test_litellm_kwargs_local_base_overrides_provider():
    """Per-stage api_base should take priority over provider-default api_base."""
    s = _S(draft_api_base="http://localhost:11434", xai_api_key="key")
    kw = s.litellm_kwargs("draft", 0)
    assert kw == {"api_base": "http://localhost:11434"}
    assert "api_key" not in kw


def test_litellm_kwargs_local_base_planning():
    s = _S(planning_api_base="http://localhost:8080/v1")
    kw = s.litellm_kwargs("planning", 0)
    assert kw["api_base"] == "http://localhost:8080/v1"


def test_litellm_kwargs_local_base_forensic():
    s = _S(forensic_api_base="http://vllm:8000/v1")
    kw = s.litellm_kwargs("forensic", 0)
    assert kw["api_base"] == "http://vllm:8000/v1"


def test_litellm_kwargs_no_local_base_uses_provider():
    """Without local base, provider logic (xAI url) still applies."""
    s = _S(draft_api_base="", xai_api_key="xai-test")
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
    s = _S(
        draft_tier0_provider="anthropic",
        draft_tier0_model="claude-sonnet-4-6",
    )
    assert s.litellm_model_string("draft", 0) == "claude-sonnet-4-6"


def test_litellm_kwargs_anthropic_with_key():
    """Anthropic provider passes api_key when set."""
    s = _S(
        draft_tier0_provider="anthropic",
        draft_tier0_model="claude-sonnet-4-6",
        anthropic_api_key="sk-ant-test",
    )
    kw = s.litellm_kwargs("draft", 0)
    assert kw.get("api_key") == "sk-ant-test"
    assert "api_base" not in kw


def test_litellm_kwargs_anthropic_no_key():
    """Anthropic provider with no key returns empty dict (lets env var take over)."""
    s = _S(
        draft_tier0_provider="anthropic",
        draft_tier0_model="claude-sonnet-4-6",
        anthropic_api_key="",
    )
    kw = s.litellm_kwargs("draft", 0)
    assert kw == {}


def test_has_api_keys_true_with_anthropic_key():
    """anthropic_api_key alone satisfies has_api_keys."""
    s = _S(anthropic_api_key="sk-ant-test")
    assert s.has_api_keys is True


def test_anthropic_api_key_override_blocked():
    """anthropic_api_key must not be settable via quillan.yaml overrides."""
    from quillan.config import _OVERRIDE_BLOCKED
    assert "anthropic_api_key" in _OVERRIDE_BLOCKED


def test_anthropic_api_key_reads_env(monkeypatch):
    """ANTHROPIC_API_KEY environment variable is picked up automatically."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")
    s = _S(anthropic_api_key="")
    assert s.anthropic_api_key == "sk-ant-from-env"
