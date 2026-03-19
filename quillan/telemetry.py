"""Per-run structured telemetry logging for Quillan."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger("quillan.telemetry")


class Telemetry:
    """Tracks LLM calls, phase timings, and prompt hashes for one run."""

    def __init__(self, runs_dir: Path, enabled: bool = True) -> None:
        self.enabled = enabled
        self._runs_dir = Path(runs_dir)
        self._run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        self._calls: list[dict] = []
        self._phase_times: list[dict] = []
        self._cache_hits: list[dict] = []
        self._start_time = time.time()
        self._calls_path: Path | None = None
        self._hash_log_path: Path | None = None

        if self.enabled:
            self._runs_dir.mkdir(parents=True, exist_ok=True)
            self._calls_path = self._runs_dir / f"calls_{self._run_id}.jsonl"
            self._hash_log_path = self._runs_dir / f"prompt_hashes_{self._run_id}.jsonl"

    # ── Public API ────────────────────────────────────────────────────────

    def record_cache_hit(self, stage: str, provider: str, model: str) -> None:
        """Record an LLM cache hit (no network call was made)."""
        if not self.enabled:
            return
        self._cache_hits.append({"ts": time.time(), "stage": stage, "provider": provider, "model": model})

    @classmethod
    def load_run_summaries(cls, runs_dir: Path, limit: int = 20) -> list[dict]:
        """Return recent telemetry summary dicts, newest first.

        Reads ``telemetry_*.json`` files from *runs_dir*; missing/malformed files
        are silently skipped.
        """
        runs_dir = Path(runs_dir)
        if not runs_dir.exists():
            return []
        files = sorted(runs_dir.glob("telemetry_*.json"), reverse=True)[:limit]
        summaries = []
        for f in files:
            try:
                summaries.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception as exc:
                logger.warning("Could not load telemetry file %s: %s", f, exc)
        return summaries

    def record_call(
        self,
        phase: str,
        provider: str,
        model: str,
        tokens: int,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """Record one LLM call with token usage.

        *input_tokens* and *output_tokens* are the prompt/completion split
        needed for cost estimation. *tokens* is the total (kept for backward
        compatibility with callers that do not split).
        """
        if not self.enabled:
            return
        entry = {
            "ts": time.time(),
            "phase": phase,
            "provider": provider,
            "model": model,
            "tokens": tokens,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
        self._calls.append(entry)
        if self._calls_path:
            with open(self._calls_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")

    @property
    def current_cost_usd(self) -> float:
        """Running estimated USD cost across all calls recorded so far."""
        from quillan.config import estimated_call_cost
        return sum(
            estimated_call_cost(c["model"], c.get("input_tokens", 0), c.get("output_tokens", 0))
            for c in self._calls
        )

    def record_phase_time(self, phase: str, start: float, end: float) -> None:
        """Record wall-clock duration for a pipeline phase."""
        if not self.enabled:
            return
        self._phase_times.append(
            {"phase": phase, "start": start, "end": end, "duration": end - start}
        )

    def log_prompt_hash(
        self,
        stage: str,
        provider: str,
        model: str,
        sys_text: str,
        user_text: str,
    ) -> None:
        """Append SHA-256 of prompts to the forensic hash log (never cleaned up)."""
        if not self.enabled or not self._hash_log_path:
            return

        combo = f"{sys_text}\n{user_text}"
        digest = hashlib.sha256(combo.encode()).hexdigest()
        entry = {
            "ts": time.time(),
            "stage": stage,
            "provider": provider,
            "model": model,
            "sha256": digest,
        }
        with open(self._hash_log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")

    def finalize(self) -> Path | None:
        """Write telemetry summary JSON. Returns output path (or None if disabled)."""
        if not self.enabled:
            return None

        from quillan.config import estimated_call_cost

        total_tokens = sum(c["tokens"] for c in self._calls)
        total_calls = len(self._calls)
        elapsed = time.time() - self._start_time

        by_provider: dict[str, int] = {}
        by_phase: dict[str, int] = {}
        total_cost = 0.0
        for c in self._calls:
            by_provider[c["provider"]] = by_provider.get(c["provider"], 0) + c["tokens"]
            by_phase[c["phase"]] = by_phase.get(c["phase"], 0) + 1
            total_cost += estimated_call_cost(
                c["model"],
                c.get("input_tokens", 0),
                c.get("output_tokens", 0),
            )

        summary = {
            "run_id": self._run_id,
            "elapsed_seconds": round(elapsed, 2),
            "total_calls": total_calls,
            "cache_hits": len(self._cache_hits),
            "total_tokens": total_tokens,
            "estimated_cost_usd": round(total_cost, 6),
            "calls_by_provider": by_provider,
            "calls_by_phase": by_phase,
            "phase_times": self._phase_times,
        }

        out_path = self._runs_dir / f"telemetry_{self._run_id}.json"
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2)

        # Clean up the .jsonl calls file (forensic hash log is intentionally kept)
        if self._calls_path and self._calls_path.exists():
            self._calls_path.unlink(missing_ok=True)

        return out_path
