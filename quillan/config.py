"""Typed settings for Quillan2, loaded from environment variables and .env file."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from quillan.paths import Paths

_log = logging.getLogger("quillan.config")


# ── Pricing table ─────────────────────────────────────────────────────────────
# Loaded from quillan/model_pricing.yaml (bundled) then merged with
# model_pricing.yaml in the current working directory (user overrides).
# Keys are LiteLLM model strings; values are (input_per_1M, output_per_1M) USD.

def _load_model_pricing() -> dict[str, tuple[float, float]]:
    """Load pricing from the bundled YAML, then merge any working-dir overrides."""
    import yaml  # local import — only needed once at startup

    bundled = Path(__file__).parent / "model_pricing.yaml"
    data: dict = {}
    try:
        data = yaml.safe_load(bundled.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # pragma: no cover
        _log.warning("Could not load bundled model_pricing.yaml: %s", exc)

    # User override: model_pricing.yaml in the current working directory
    user_file = Path("model_pricing.yaml")
    if user_file.exists():
        try:
            overrides = yaml.safe_load(user_file.read_text(encoding="utf-8")) or {}
            data.update(overrides)
            _log.debug("Merged %d model pricing overrides from %s", len(overrides), user_file)
        except Exception as exc:
            _log.warning("Could not load model_pricing.yaml override: %s", exc)

    return {k: (float(v[0]), float(v[1])) for k, v in data.items() if isinstance(v, list) and len(v) == 2}


MODEL_PRICING: dict[str, tuple[float, float]] = _load_model_pricing()


def estimated_call_cost(model_str: str, input_tokens: int, output_tokens: int) -> float:
    """Return estimated USD cost for one LLM call.

    Returns 0.0 if the model is not in MODEL_PRICING.
    """
    if model_str not in MODEL_PRICING:
        return 0.0
    in_rate, out_rate = MODEL_PRICING[model_str]
    return (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="QUILLAN_",
        env_file=["quillan.env", ".env"],   # quillan.env checked first, auto-detected
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Storage ───────────────────────────────────────────────────────────
    data_dir: Path = Path("./quillan_data")
    canon: str = "default"
    series: str = "default"

    # ── Model tiers: planning (OpenAI budget → OpenAI quality → xAI → Gemini) ──
    planning_tier0_provider: str = "openai"
    planning_tier0_model:    str = "gpt-4o-mini"     # budget first
    planning_tier1_provider: str = "openai"
    planning_tier1_model:    str = "gpt-4o"           # quality escalation
    planning_tier2_provider: str = "xai"
    planning_tier2_model:    str = "grok-2"            # second provider
    planning_tier3_provider: str = "gemini"
    planning_tier3_model:    str = "gemini-1.5-pro"    # third provider

    # ── Model tiers: draft (xAI budget → xAI quality → OpenAI → Gemini) ─────
    draft_tier0_provider: str = "xai"
    draft_tier0_model:    str = "grok-2-mini"          # budget first
    draft_tier1_provider: str = "xai"
    draft_tier1_model:    str = "grok-2"               # quality escalation
    draft_tier2_provider: str = "openai"
    draft_tier2_model:    str = "gpt-4o"               # second provider
    draft_tier3_provider: str = "gemini"
    draft_tier3_model:    str = "gemini-1.5-pro"       # third provider

    # ── Model tiers: forensic (Gemini budget → Gemini quality → OpenAI → xAI) ─
    forensic_tier0_provider: str = "gemini"
    forensic_tier0_model:    str = "gemini-1.5-flash"  # budget first
    forensic_tier1_provider: str = "gemini"
    forensic_tier1_model:    str = "gemini-1.5-pro"    # quality escalation
    forensic_tier2_provider: str = "openai"
    forensic_tier2_model:    str = "gpt-4o"             # second provider
    forensic_tier3_provider: str = "xai"
    forensic_tier3_model:    str = "grok-2"              # third provider

    # ── Model tiers: struct ("" → inherit from planning tier) ────────────────
    struct_tier0_provider: str = ""
    struct_tier0_model:    str = ""
    struct_tier1_provider: str = ""
    struct_tier1_model:    str = ""
    struct_tier2_provider: str = ""
    struct_tier2_model:    str = ""
    struct_tier3_provider: str = ""
    struct_tier3_model:    str = ""

    # ── Execution ─────────────────────────────────────────────────────────
    max_parallel: int = 3
    stage_max_retries: int = 1
    stage_max_escalations: int = 3
    draft_audit_retries: int = 1    # how many times to redraft a beat that fails audit
    run_max_calls: int = 0          # 0 = no cap
    llm_call_timeout: int = 120     # seconds per call; 0 = no limit
    run_max_cost_usd: float = 0.0   # abort run if estimated cost exceeds this; 0 = no limit

    # ── Token budget ──────────────────────────────────────────────────────
    max_prompt_tokens: int = 32768  # 0 = disabled

    # ── Caching ───────────────────────────────────────────────────────────
    llm_cache: bool = True
    cache_dir: Path = Path("./quillan_data/.cache")
    cache_ttl_days: int = 30     # 0 = never expire cache entries

    # ── Continuity ────────────────────────────────────────────────────────
    distill_continuity: bool = False
    continuity_last_beats_n: int = 5
    continuity_include_history: bool = True
    continuity_max_context_chars: int = 18000
    continuity_summary_max_chars: int = 12000
    continuity_open_threads_max_chars: int = 9000
    continuity_ledger_max_chars: int = 14000

    # ── Prose analyzer thresholds ─────────────────────────────────────────
    prose_word_overuse_min: int = 5        # occurrences per beat → flag
    prose_phrase_overuse_min: int = 3      # 2-gram occurrences per beat → flag
    prose_opener_dominant_pct: float = 0.30  # fraction of sentences sharing first word → flag
    prose_adverb_density_warn: float = 0.03  # fraction of words ending -ly → flag
    prose_story_overuse_beats: int = 3     # appears in N prior beats → flag

    # ── Cover image ───────────────────────────────────────────────────────
    cover_style: str = "cinematic, photorealistic, dramatic lighting, high contrast"
    # e.g. "watercolor illustration, soft pastels", "noir ink sketch, high contrast"

    # ── LLM generation parameters ─────────────────────────────────────────
    planning_temperature: float | None = None   # None = provider default
    draft_temperature: float | None = None
    forensic_temperature: float | None = None
    struct_temperature: float | None = None
    top_p: float | None = None                  # applied to all stages; None = provider default

    # ── Audiobook (TTS) ───────────────────────────────────────────────────
    tts_provider: str = "openai"   # "openai" | "elevenlabs"
    tts_model: str = "tts-1"
    tts_voice: str = "alloy"   # alloy | echo | fable | onyx | nova | shimmer
    # ElevenLabs
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"  # "Rachel" default
    elevenlabs_model: str = "eleven_monolingual_v1"

    # ── Telemetry ─────────────────────────────────────────────────────────
    telemetry: bool = True
    tmp_ttl_hours: int = 24

    # ── Local LLM base URLs (Ollama / vLLM / LM Studio) ──────────────────
    # When set, overrides the provider's default api_base for that stage.
    planning_api_base: str = ""
    draft_api_base: str = ""
    forensic_api_base: str = ""
    struct_api_base: str = ""

    # ── API keys (no QUILLAN_ prefix — read raw env names) ───────────────
    openai_api_key: str = ""
    xai_api_key: str = ""
    gemini_api_key: str = ""
    anthropic_api_key: str = ""

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def _read_openai_key(cls, v: str) -> str:
        import os
        return v or os.environ.get("OPENAI_API_KEY", "")

    @field_validator("xai_api_key", mode="before")
    @classmethod
    def _read_xai_key(cls, v: str) -> str:
        import os
        return v or os.environ.get("XAI_API_KEY", "")

    @field_validator("gemini_api_key", mode="before")
    @classmethod
    def _read_gemini_key(cls, v: str) -> str:
        import os
        return v or os.environ.get("GEMINI_API_KEY", "")

    @field_validator("anthropic_api_key", mode="before")
    @classmethod
    def _read_anthropic_key(cls, v: str) -> str:
        import os
        return v or os.environ.get("ANTHROPIC_API_KEY", "")

    # ── Derived properties ────────────────────────────────────────────────

    @property
    def has_api_keys(self) -> bool:
        return bool(
            self.openai_api_key
            or self.xai_api_key
            or self.gemini_api_key
            or self.anthropic_api_key
            or self.planning_api_base
            or self.draft_api_base
            or self.forensic_api_base
            or self.struct_api_base
        )

    def provider_for_stage(self, stage: str, tier: int = 0) -> str:
        """Return the provider name for the given pipeline stage and tier."""
        tier = max(0, min(3, tier))
        provider = getattr(self, f"{stage}_tier{tier}_provider", "")
        if not provider and stage == "struct":
            provider = getattr(self, f"planning_tier{tier}_provider", "openai")
        return provider or "openai"

    def model_for_stage(self, stage: str, tier: int = 0) -> str:
        """Return the model ID for the given stage and escalation tier (0–3)."""
        tier = max(0, min(3, tier))
        model = getattr(self, f"{stage}_tier{tier}_model", "")
        if not model and stage == "struct":
            model = getattr(self, f"planning_tier{tier}_model", "gpt-4o")
        return model or "gpt-4o"

    def litellm_model_string(self, stage: str, tier: int = 0) -> str:
        """Return the LiteLLM model string for the given stage and tier."""
        provider = self.provider_for_stage(stage, tier)
        model = self.model_for_stage(stage, tier)
        if provider == "openai":
            return model
        if provider == "xai":
            return f"openai/{model}"
        if provider == "gemini":
            return f"gemini/{model}"
        if provider == "anthropic":
            return model  # LiteLLM recognises claude-* model strings natively
        return model

    def litellm_kwargs(self, stage: str, tier: int = 0) -> dict:
        """Extra kwargs for LiteLLM calls (api_base, api_key) by provider."""
        provider = self.provider_for_stage(stage, tier)
        # Per-stage api_base override takes priority (local LLM support)
        stage_key = stage if stage in ("planning", "draft", "forensic", "struct") else "planning"
        local_base = getattr(self, f"{stage_key}_api_base", "")
        if local_base:
            return {"api_base": local_base}
        if provider == "xai":
            return {
                "api_base": "https://api.x.ai/v1",
                "api_key": self.xai_api_key,
            }
        if provider == "gemini":
            return {"api_key": self.gemini_api_key}
        if provider == "anthropic":
            kw = {}
            if self.anthropic_api_key:
                kw["api_key"] = self.anthropic_api_key
            return kw
        if provider == "openai":
            kw = {}
            if self.openai_api_key:
                kw["api_key"] = self.openai_api_key
            return kw
        return {}


# ── Per-story / per-world settings overlay ────────────────────────────────────

# Fields that may never be overridden via quillan.yaml (security boundary).
_OVERRIDE_BLOCKED: frozenset[str] = frozenset({
    "openai_api_key", "xai_api_key", "gemini_api_key", "anthropic_api_key",
    "elevenlabs_api_key",
    "planning_api_base", "draft_api_base", "forensic_api_base", "struct_api_base",
})


def load_story_settings(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    base: "Settings | None" = None,
) -> "Settings":
    """Return Settings with world + story ``quillan.yaml`` overrides merged in.

    Merge order (later wins): global env/defaults → world quillan.yaml → story quillan.yaml.

    API keys (openai_api_key, xai_api_key, gemini_api_key) are never overridable
    from quillan.yaml files — they must come from environment variables.

    If neither override file exists the *base* instance is returned unchanged
    (no copy is made).  If YAML is malformed a warning is logged and that file
    is skipped.

    Args:
        paths:  Paths instance anchored at the project data_dir.
        world, canon, series, story:  Story coordinates.
        base:   Starting Settings; defaults to ``Settings()`` when omitted.
    """
    if base is None:
        base = Settings()

    overrides: dict = {}

    def _load_yaml(path: Path, label: str) -> None:
        if not path.exists():
            return
        try:
            import yaml
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                _log.warning("Ignoring %s quillan.yaml — expected a YAML mapping, got %s", label, type(raw).__name__)
                return
            safe = {k: v for k, v in raw.items() if k not in _OVERRIDE_BLOCKED}
            overrides.update(safe)
            _log.debug("Loaded %d override(s) from %s quillan.yaml", len(safe), label)
        except Exception as exc:
            _log.warning("Skipping malformed %s quillan.yaml (%s): %s", label, path, exc)

    _load_yaml(paths.world_settings(world), f"world '{world}'")
    if story:
        _load_yaml(paths.story_settings(world, canon, series, story), f"story '{story}'")

    if not overrides:
        return base

    try:
        merged = {**base.model_dump(), **overrides}
        return type(base)(**merged)
    except Exception as exc:
        _log.warning("Failed to apply settings overrides — using base settings: %s", exc)
        return base
