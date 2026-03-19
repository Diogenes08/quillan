"""Typed settings for Quillan, loaded from environment variables and .env file."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

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


# ── Writer presets ────────────────────────────────────────────────────────────
# A preset is a named group of settings aimed at a particular writing goal.
# Set QUILLAN_PRESET=quality (or budget / fast / balanced) in quillan.env.
#
# Precedence (later wins):  field defaults  <  preset  <  explicit env var / quillan.env
# So any setting you specify explicitly always overrides the preset.

_PRESETS: dict[str, dict] = {
    # ── quality ───────────────────────────────────────────────────────────────
    # Best possible prose. Uses the strongest models, gives each beat full
    # context, re-checks output more thoroughly, and compresses continuity so
    # the AI never loses the thread of a long story.
    # Trade-off: slower and more expensive.
    "quality": {
        "max_parallel":               2,
        "max_prompt_tokens":          65536,
        "distill_continuity":         True,
        "continuity_last_beats_n":    10,
        "draft_audit_retries":        2,
        "stage_max_retries":          2,
        "stage_max_escalations":      3,
    },

    # ── balanced ──────────────────────────────────────────────────────────────
    # The default behaviour, spelled out explicitly so writers can see it.
    # Good quality at a reasonable cost and speed.
    "balanced": {
        "max_parallel":               3,
        "max_prompt_tokens":          32768,
        "distill_continuity":         False,
        "continuity_last_beats_n":    5,
        "draft_audit_retries":        1,
        "stage_max_retries":          1,
        "stage_max_escalations":      3,
    },

    # ── budget ────────────────────────────────────────────────────────────────
    # Uses the smaller, cheaper model in each provider family (mini / flash).
    # Still produces a quality draft — just less expensive per scene.
    # Trade-off: slightly lower ceiling on prose quality.
    "budget": {
        "planning_tier0_model":       "gpt-4.1-mini",
        "draft_tier0_model":          "grok-3-mini",
        "forensic_tier0_model":       "gemini-2.0-flash",
        "max_parallel":               2,
        "max_prompt_tokens":          16384,
        "distill_continuity":         False,
        "continuity_last_beats_n":    3,
        "draft_audit_retries":        0,
        "stage_max_retries":          1,
        "stage_max_escalations":      1,
    },

    # ── fast ──────────────────────────────────────────────────────────────────
    # Get a rough first draft on the page as quickly as possible.
    # Uses fast/small models with maximum parallelism. Quality checks are
    # minimal — treat the output as a first pass to revise later.
    # Trade-off: fastest and cheapest; prose quality is good but not refined.
    "fast": {
        "planning_tier0_model":       "gpt-4.1-mini",
        "draft_tier0_model":          "grok-3-mini",
        "forensic_tier0_model":       "gemini-2.0-flash",
        "max_parallel":               6,
        "max_prompt_tokens":          16384,
        "distill_continuity":         False,
        "continuity_last_beats_n":    3,
        "draft_audit_retries":        0,
        "stage_max_retries":          0,
        "stage_max_escalations":      1,
    },
}

# Public list of valid preset names (used in CLI help text and docs).
PRESET_NAMES: tuple[str, ...] = tuple(_PRESETS)


class _PresetSource(PydanticBaseSettingsSource):
    """Settings source that injects preset values.

    Priority slot:  init_kwargs  >  env vars  >  **_PresetSource**  >  dotenv  >  defaults

    This means:
    - Shell env var  QUILLAN_MAX_PARALLEL=5  overrides the preset  ✓
    - quillan.env    QUILLAN_MAX_PARALLEL=3  is overridden by the preset  ✓
    - Constructor    Settings(max_parallel=8) overrides the preset  ✓

    The preset name is resolved from (in order of priority):
      1. Constructor kwarg  preset='...'
      2. Shell env var      QUILLAN_PRESET=...
      3. dotenv_settings source (already configured with the correct file paths)
    """

    def __init__(
        self,
        settings_cls: type,
        init_kwargs: dict,
        dotenv_source: PydanticBaseSettingsSource,
    ) -> None:
        super().__init__(settings_cls)
        self._init_kwargs = init_kwargs
        self._dotenv_source = dotenv_source
        self._resolved: dict | None = None  # lazily computed

    def _resolve(self) -> dict:
        if self._resolved is not None:
            return self._resolved

        import os

        name = ""

        # 1. Constructor kwarg — highest authority for preset name
        if "preset" in self._init_kwargs:
            name = str(self._init_kwargs["preset"]).strip()

        # 2. Shell environment variable
        if not name:
            name = os.environ.get("QUILLAN_PRESET", "").strip()

        # 3. Dotenv file — via the already-configured dotenv source so we respect
        #    any _env_file= override passed to the Settings constructor
        if not name:
            try:
                dotenv_data = self._dotenv_source()
                name = str(dotenv_data.get("preset", "")).strip()
            except Exception:
                pass

        name = name.lower()
        if not name:
            self._resolved = {}
            return {}

        preset = _PRESETS.get(name)
        if preset is None:
            _log.warning(
                "Unknown QUILLAN_PRESET=%r — ignored. Valid values: %s",
                name,
                ", ".join(_PRESETS),
            )
            self._resolved = {}
            return {}

        _log.debug("Applying preset %r (%d settings)", name, len(preset))
        self._resolved = dict(preset)
        return self._resolved

    def get_field_value(self, field, field_name: str):  # type: ignore[override]
        value = self._resolve().get(field_name)
        return value, field_name, False

    def __call__(self) -> dict:
        return self._resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="QUILLAN_",
        env_file=["quillan.env", ".env"],   # quillan.env checked first, auto-detected
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Preset ────────────────────────────────────────────────────────────
    # One word that configures a sensible group of settings for a writing goal.
    # Valid values: quality | balanced | budget | fast
    # Any setting you set explicitly will override what the preset chooses.
    preset: str = ""

    # ── Storage ───────────────────────────────────────────────────────────
    data_dir: Path = Path("./quillan_data")
    canon: str = "default"
    series: str = "default"

    # ── Model tiers: planning (OpenAI quality → OpenAI budget → xAI → Gemini) ──
    planning_tier0_provider: str = "openai"
    planning_tier0_model:    str = "gpt-4.1"            # quality default
    planning_tier1_provider: str = "openai"
    planning_tier1_model:    str = "gpt-4.1-mini"       # cost fallback
    planning_tier2_provider: str = "xai"
    planning_tier2_model:    str = "grok-3"              # second provider
    planning_tier3_provider: str = "gemini"
    planning_tier3_model:    str = "gemini-2.5-pro"     # third provider

    # ── Model tiers: draft (xAI quality → xAI budget → OpenAI → Gemini) ─────
    draft_tier0_provider: str = "xai"
    draft_tier0_model:    str = "grok-3"                # quality default
    draft_tier1_provider: str = "xai"
    draft_tier1_model:    str = "grok-3-mini"           # cost fallback
    draft_tier2_provider: str = "openai"
    draft_tier2_model:    str = "gpt-4.1"               # second provider
    draft_tier3_provider: str = "gemini"
    draft_tier3_model:    str = "gemini-2.5-pro"        # third provider

    # ── Model tiers: forensic (Gemini quality → Gemini budget → OpenAI → xAI) ─
    forensic_tier0_provider: str = "gemini"
    forensic_tier0_model:    str = "gemini-2.5-pro"     # quality default
    forensic_tier1_provider: str = "gemini"
    forensic_tier1_model:    str = "gemini-2.0-flash"   # cost fallback
    forensic_tier2_provider: str = "openai"
    forensic_tier2_model:    str = "gpt-4.1"             # second provider
    forensic_tier3_provider: str = "xai"
    forensic_tier3_model:    str = "grok-3"              # third provider

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
    llm_min_call_interval: float = 0.0  # minimum seconds between API calls; 0 = no floor

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

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Priority order (highest → lowest):
          init kwargs  →  shell env vars  →  PRESET  →  quillan.env  →  built-in defaults
        """
        preset_source = _PresetSource(settings_cls, init_settings.init_kwargs, dotenv_settings)
        return (init_settings, env_settings, preset_source, dotenv_settings, file_secret_settings)

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
            model = getattr(self, f"planning_tier{tier}_model", "gpt-4.1")
        return model or "gpt-4.1"

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
