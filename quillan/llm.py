"""LiteLLM wrapper with tiered calling, caching, and retry/backoff."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quillan.config import Settings
    from quillan.telemetry import Telemetry

try:
    import litellm

    litellm.telemetry = False  # disable litellm's own analytics
except ImportError:
    litellm = None  # type: ignore[assignment]

import logging

from quillan.token_tool import trim_to_tokens
from quillan.validate import py_extract_json

logger = logging.getLogger("quillan.llm")


class LLMError(Exception):
    """Raised when all tiers/retries are exhausted."""


class LLMClient:
    """LiteLLM wrapper with tiered escalation, caching, and telemetry."""

    def __init__(
        self,
        settings: "Settings",
        telemetry: "Telemetry",
        cache_dir: Path | None = None,
    ) -> None:
        self.settings = settings
        self.telemetry = telemetry
        self._cache_dir = Path(cache_dir) if cache_dir else None
        if self._cache_dir and settings.llm_cache:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            if settings.cache_ttl_days > 0:
                from quillan.io import prune_old_cache
                deleted = prune_old_cache(self._cache_dir, settings.cache_ttl_days)
                if deleted:
                    logger.debug("Pruned %d stale cache entries (ttl=%dd)", deleted, settings.cache_ttl_days)
        self._call_count = 0

    # ── Public API ────────────────────────────────────────────────────────

    async def call(
        self,
        stage: str,
        system: str,
        user: str,
        mode: str = "text",
    ) -> str:
        """Tiered call: try TIER0, escalate on failure up to max_escalations.

        *mode* is "text" or "json".
        Returns the response text (or JSON string).
        """
        max_esc = self.settings.stage_max_escalations
        last_error: Exception | None = None

        for tier in range(max_esc + 1):
            provider = self.settings.provider_for_stage(stage, tier)
            model_str = self.settings.litellm_model_string(stage, tier)
            try:
                result = await self._call_once(provider, model_str, stage, tier, system, user, mode)
                return result
            except Exception as exc:
                last_error = exc
                if tier < max_esc:
                    continue  # escalate

        raise LLMError(
            f"All tiers exhausted for stage={stage}. Last error: {last_error or 'unknown'} "
            "Check API keys ('quillan doctor') and connection."
        ) from last_error

    async def call_json(
        self,
        stage: str,
        system: str,
        user: str,
        required_keys: list[str] | None = None,
    ) -> dict:
        """Convenience: call in json mode and extract parsed dict."""
        raw = await self.call(stage, system, user, mode="json")
        return py_extract_json(raw, required_keys)

    async def call_stream(
        self,
        stage: str,
        system: str,
        user: str,
    ) -> AsyncGenerator[str, None]:
        """Streaming call: yields text chunks as they arrive.

        Cache hit: yields the cached response as a single chunk (no network call).
        Cache miss: streams live, caches the full assembled text on completion.
        Falls back to a regular (non-streaming) call if streaming is unsupported.
        """
        if litellm is None:
            raise LLMError("litellm is not installed")

        if not self.settings.has_api_keys:
            raise LLMError(
                "No API keys configured. Set OPENAI_API_KEY / XAI_API_KEY / GEMINI_API_KEY, "
                "or configure a local LLM with QUILLAN_DRAFT_API_BASE."
            )

        max_tok = self.settings.max_prompt_tokens
        if max_tok > 0:
            user = trim_to_tokens(user, max_tok)

        provider = self.settings.provider_for_stage(stage, 0)
        model_str = self.settings.litellm_model_string(stage, 0)
        cache_key = self._cache_key(provider, model_str, "text", system, user)

        # Cache hit: yield as one chunk
        if self.settings.llm_cache:
            cached = self._cache_get(cache_key)
            if cached is not None:
                self.telemetry.record_cache_hit(stage, provider, model_str)
                yield cached
                return

        self.telemetry.log_prompt_hash(stage, provider, model_str, system, user)

        extra_kwargs = self.settings.litellm_kwargs(stage, 0)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        timeout = self.settings.llm_call_timeout or None
        collected: list[str] = []
        input_tokens = 0
        output_tokens = 0

        try:
            resp = await asyncio.wait_for(
                litellm.acompletion(
                    model=model_str,
                    messages=messages,
                    stream=True,
                    **extra_kwargs,
                ),
                timeout=timeout,
            )
            async for chunk in resp:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    collected.append(delta)
                    yield delta
                # Accumulate usage if provided in final chunk
                if hasattr(chunk, "usage") and chunk.usage:
                    input_tokens = getattr(chunk.usage, "prompt_tokens", 0)
                    output_tokens = getattr(chunk.usage, "completion_tokens", 0)
        except Exception as exc:
            # Streaming failed: fall back to regular call
            logger.warning("Streaming call failed for stage=%s, falling back: %s", stage, exc)
            text = await self.call(stage, system, user, mode="text")
            yield text
            return

        self._call_count += 1
        full_text = "".join(collected)
        # Estimate tokens from collected text if usage not reported
        if not output_tokens:
            output_tokens = len(full_text.split())
        total_tokens = input_tokens + output_tokens
        self.telemetry.record_call(
            stage, provider, model_str, total_tokens,
            input_tokens=input_tokens, output_tokens=output_tokens,
        )
        # Check cost cap (mirrors _call_once behaviour)
        cap = self.settings.run_max_cost_usd
        if cap > 0:
            current_cost = self.telemetry.current_cost_usd
            if current_cost > cap:
                raise LLMError(
                    f"Run cost cap reached (${current_cost:.4f} > ${cap}). "
                    "Increase QUILLAN_RUN_MAX_COST_USD or draft fewer beats."
                )
        if self.settings.llm_cache:
            self._cache_put(cache_key, full_text)

    async def generate_image(self, prompt: str, size: str = "1024x1792") -> bytes:
        """Generate an image via DALL-E 3; return raw PNG bytes.

        Raises LLMError if no API keys are configured.
        Uses the same run_in_executor pattern as call() to stay non-blocking.
        """
        if not self.settings.has_api_keys:
            raise LLMError(
                "Image generation requires API keys (no image provider configured). "
                "Run 'quillan doctor' to check."
            )
        import base64
        import litellm as _litellm
        resp = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: _litellm.image_generation(
                model="dall-e-3",
                prompt=prompt,
                n=1,
                size=size,
                response_format="b64_json",
            ),
        )
        data_list = resp.data or []  # type: ignore[union-attr]
        if not data_list:
            raise LLMError(
                "Image generation returned no data. "
                "Try adjusting cover_style or seed text."
            )
        b64 = data_list[0].b64_json  # type: ignore[index]
        return base64.b64decode(b64)  # type: ignore[arg-type]

    # ── Internal ──────────────────────────────────────────────────────────

    async def _call_once(
        self,
        provider: str,
        model_str: str,
        stage: str,
        tier: int,
        system: str,
        user: str,
        mode: str,
    ) -> str:
        """Single LiteLLM call with retry/backoff on 429/5xx.

        Pre-trims user text to max_prompt_tokens if configured.
        """
        if litellm is None:
            raise LLMError("litellm is not installed. Install with: pip install litellm")

        if not self.settings.has_api_keys:
            raise LLMError("No API keys configured. Set OPENAI_API_KEY / XAI_API_KEY / GEMINI_API_KEY.")

        # Cap prompt
        max_tok = self.settings.max_prompt_tokens
        if max_tok > 0:
            user = trim_to_tokens(user, max_tok)

        # Check cache
        cache_key = self._cache_key(provider, model_str, mode, system, user)
        if self.settings.llm_cache:
            cached = self._cache_get(cache_key)
            if cached is not None:
                self.telemetry.record_cache_hit(stage, provider, model_str)
                return cached

        # Log prompt hash (forensic, never cleaned)
        self.telemetry.log_prompt_hash(stage, provider, model_str, system, user)

        # Check run cap
        if self.settings.run_max_calls > 0 and self._call_count >= self.settings.run_max_calls:
            raise LLMError(
                f"Run call cap reached ({self.settings.run_max_calls}). "
                "Increase QUILLAN_RUN_MAX_CALLS or draft fewer beats."
            )

        extra_kwargs = self.settings.litellm_kwargs(stage, tier)
        # Per-stage temperature and global top_p
        temp = getattr(self.settings, f"{stage}_temperature", None)
        if temp is not None:
            extra_kwargs = {**extra_kwargs, "temperature": temp}
        if self.settings.top_p is not None:
            extra_kwargs = {**extra_kwargs, "top_p": self.settings.top_p}
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        response_format = None
        if mode == "json":
            response_format = {"type": "json_object"}

        max_retries = self.settings.stage_max_retries
        last_err: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                kwargs: dict = {
                    "model": model_str,
                    "messages": messages,
                    **extra_kwargs,
                }
                if response_format:
                    kwargs["response_format"] = response_format

                timeout = self.settings.llm_call_timeout or None
                try:
                    resp = await asyncio.wait_for(
                        asyncio.get_running_loop().run_in_executor(
                            None,
                            lambda kw=kwargs: litellm.completion(**kw),  # type: ignore[misc]
                        ),
                        timeout=timeout,
                    )
                except asyncio.TimeoutError:
                    raise LLMError(
                        f"Call timed out after {timeout}s. "
                        "Check connection. If using a local LLM, increase QUILLAN_LLM_CALL_TIMEOUT."
                    )
                self._call_count += 1

                text = resp.choices[0].message.content or ""
                input_tokens = getattr(resp.usage, "prompt_tokens", 0) if resp.usage else 0
                output_tokens = getattr(resp.usage, "completion_tokens", 0) if resp.usage else 0
                tokens = input_tokens + output_tokens
                self.telemetry.record_call(
                    stage, provider, model_str, tokens,
                    input_tokens=input_tokens, output_tokens=output_tokens,
                )

                # Check cost cap after recording the call
                cap = self.settings.run_max_cost_usd
                if cap > 0:
                    current_cost = self.telemetry.current_cost_usd
                    if current_cost > cap:
                        raise LLMError(
                            f"Run cost cap reached (${current_cost:.4f} > ${cap}). "
                            "Increase QUILLAN_RUN_MAX_COST_USD or draft fewer beats."
                        )

                if self.settings.llm_cache:
                    self._cache_put(cache_key, text)

                return text

            except Exception as exc:
                last_err = exc
                exc_name = type(exc).__name__.lower()
                is_rate_limit = "ratelimit" in exc_name or "429" in str(exc)
                is_server_err = any(
                    code in str(exc) for code in ("500", "502", "503", "504")
                )

                if (is_rate_limit or is_server_err) and attempt < max_retries:
                    wait = 2 ** attempt * (5 if is_rate_limit else 1)
                    await asyncio.sleep(wait)
                    continue

                # Raise RateLimitError with sentinel for adaptive throttling
                if is_rate_limit:
                    raise _RateLimitError(str(exc)) from exc

                raise

        raise LLMError(f"All retries exhausted: {last_err}") from last_err

    # ── Cache helpers ─────────────────────────────────────────────────────

    def _cache_key(
        self, provider: str, model: str, mode: str, system: str, user: str
    ) -> str:
        combo = f"{provider}|{model}|{mode}|{system}|{user}"
        return hashlib.sha256(combo.encode()).hexdigest()

    def _cache_get(self, key: str) -> str | None:
        if not self._cache_dir:
            return None
        path = self._cache_dir / f"{key[:2]}" / f"{key}.txt"
        if path.exists():
            try:
                return path.read_text(encoding="utf-8")
            except OSError:
                return None
        return None

    def _cache_put(self, key: str, response: str) -> None:
        if not self._cache_dir:
            return
        path = self._cache_dir / f"{key[:2]}" / f"{key}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(response, encoding="utf-8")
        except OSError:
            pass


class _RateLimitError(LLMError):
    """Raised specifically on HTTP 429 to signal adaptive throttling."""
