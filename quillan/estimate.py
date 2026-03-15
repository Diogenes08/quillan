"""Pre-run cost and token estimation for a Quillan2 draft run.

No LLM calls are made — all estimates are derived from local artefacts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import yaml

from quillan.validate import parse_beats_mode as _parse_beats_mode

if TYPE_CHECKING:
    from quillan.config import Settings
    from quillan.paths import Paths

# ── Fallback token budgets when spec/context files aren't present ─────────────
_DRAFT_INPUT_FALLBACK = 8_000    # context bundle: canon + spec + history
_DRAFT_OUTPUT_FALLBACK = 2_500   # typical prose per beat (~1 750 words)
_AUDIT_INPUT_FALLBACK = 6_000    # prose + spec fed to audit
_AUDIT_OUTPUT_FALLBACK = 600     # structured JSON audit result
_STATE_INPUT_FALLBACK = 4_000    # prose-only fed to state extractor
_STATE_OUTPUT_FALLBACK = 400     # JSON patch

# Words-to-tokens ratio (rough; tiktoken heuristic is ~0.75 words/token)
_WORDS_PER_TOKEN = 0.75


@dataclass
class BeatEstimate:
    beat_id: str
    draft_input: int
    draft_output: int
    audit_input: int
    audit_output: int
    state_input: int
    state_output: int


@dataclass
class EstimateResult:
    """Full cost/token breakdown for a pending draft run."""

    num_beats: int
    draft_model: str
    forensic_model: str
    beat_estimates: list[BeatEstimate] = field(default_factory=list)

    # Optimistic = no retries; Pessimistic = full audit_retries
    draft_retries: int = 1  # settings.draft_audit_retries

    @property
    def total_draft_input(self) -> int:
        return sum(b.draft_input for b in self.beat_estimates)

    @property
    def total_draft_output(self) -> int:
        return sum(b.draft_output for b in self.beat_estimates)

    @property
    def total_forensic_input(self) -> int:
        return sum(b.audit_input + b.state_input for b in self.beat_estimates)

    @property
    def total_forensic_output(self) -> int:
        return sum(b.audit_output + b.state_output for b in self.beat_estimates)

    def cost_usd(self, retries: int = 0) -> float:
        """Estimated USD cost.  retries=0 = best case, retries=N = worst case."""
        from quillan.config import estimated_call_cost

        draft_mult = 1 + retries
        draft = estimated_call_cost(
            self.draft_model,
            self.total_draft_input * draft_mult,
            self.total_draft_output * draft_mult,
        )
        # audit runs once per attempt; state extraction runs once (after success)
        audit_calls = 1 + retries
        forensic_input = sum(
            b.audit_input * audit_calls + b.state_input for b in self.beat_estimates
        )
        forensic_output = sum(
            b.audit_output * audit_calls + b.state_output for b in self.beat_estimates
        )
        forensic = estimated_call_cost(self.forensic_model, forensic_input, forensic_output)
        return draft + forensic

    def as_dict(self) -> dict:
        return {
            "num_beats": self.num_beats,
            "draft_model": self.draft_model,
            "forensic_model": self.forensic_model,
            "draft_retries": self.draft_retries,
            "tokens": {
                "draft_input": self.total_draft_input,
                "draft_output": self.total_draft_output,
                "forensic_input": self.total_forensic_input,
                "forensic_output": self.total_forensic_output,
            },
            "cost_usd": {
                "optimistic": round(self.cost_usd(retries=0), 4),
                "pessimistic": round(self.cost_usd(retries=self.draft_retries), 4),
            },
        }

    def summary_lines(self) -> list[str]:
        opt = self.cost_usd(retries=0)
        pess = self.cost_usd(retries=self.draft_retries)
        return [
            f"  Beats to draft  : {self.num_beats}",
            f"  Draft model     : {self.draft_model}",
            f"  Forensic model  : {self.forensic_model}",
            f"  Draft tokens    : ~{self.total_draft_input:,} in / ~{self.total_draft_output:,} out",
            f"  Forensic tokens : ~{self.total_forensic_input:,} in / ~{self.total_forensic_output:,} out",
            f"  Cost estimate   : ~${opt:.3f} (best) — ~${pess:.3f} (with retries)",
        ]


def estimate_draft_cost(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    settings: "Settings",
    beats_mode: str | int = "all",
    explicit_beats: list[str] | None = None,
    force: bool = False,
) -> EstimateResult:
    """Compute a cost/token estimate without making any LLM calls.

    Reads: dependency_map.json, beat_spec.yaml (each beat), canon_packet.yaml.
    Falls back to conservative defaults when files are missing.
    """
    from quillan.validate import validate_dependency_map
    from quillan.pipeline.dag import compute_batches
    from quillan.token_tool import estimate_tokens

    draft_model = settings.litellm_model_string("draft", 0)
    forensic_model = settings.litellm_model_string("forensic", 0)

    # Load beat list in dependency order
    dep_path = paths.dependency_map(world, canon, series, story)
    if not dep_path.exists():
        return EstimateResult(
            num_beats=0,
            draft_model=draft_model,
            forensic_model=forensic_model,
        )

    dep_map = validate_dependency_map(dep_path)
    batches = compute_batches(dep_map)
    all_beats: list[str] = [bid for batch in batches for bid in batch]

    # Apply explicit_beats filter
    if explicit_beats is not None:
        explicit_set = set(explicit_beats)
        all_beats = [b for b in all_beats if b in explicit_set]

    # Apply beats_mode limit
    beat_limit = _parse_beats_mode(beats_mode)
    if beat_limit is not None:
        all_beats = all_beats[:beat_limit]

    # Skip already-drafted beats unless force=True
    if not force:
        all_beats = [
            b for b in all_beats
            if not paths.beat_draft(world, canon, series, story, b).exists()
        ]

    # Baseline canon packet size
    canon_tokens = _DRAFT_INPUT_FALLBACK // 3
    canon_packet_path = paths.canon_packet(world, canon, series, story)
    if canon_packet_path.exists():
        try:
            canon_tokens = estimate_tokens(
                canon_packet_path.read_text(encoding="utf-8", errors="replace")
            )
        except OSError:
            pass

    beat_estimates: list[BeatEstimate] = []
    for beat_id in all_beats:
        spec_path = paths.beat_spec(world, canon, series, story, beat_id)
        word_count_target = 1_750  # fallback
        spec_tokens = 500
        if spec_path.exists():
            try:
                spec_text = spec_path.read_text(encoding="utf-8", errors="replace")
                spec_tokens = estimate_tokens(spec_text)
                spec_data = yaml.safe_load(spec_text) or {}
                word_count_target = int(spec_data.get("word_count_target", 1_750))
            except (OSError, yaml.YAMLError, ValueError):
                pass

        draft_input = canon_tokens + spec_tokens + _DRAFT_INPUT_FALLBACK // 3
        draft_output = max(500, int(word_count_target / _WORDS_PER_TOKEN))
        audit_input = draft_output + spec_tokens + 500
        audit_output = _AUDIT_OUTPUT_FALLBACK
        state_input = min(draft_output, 4_000) + 300
        state_output = _STATE_OUTPUT_FALLBACK

        beat_estimates.append(BeatEstimate(
            beat_id=beat_id,
            draft_input=draft_input,
            draft_output=draft_output,
            audit_input=audit_input,
            audit_output=audit_output,
            state_input=state_input,
            state_output=state_output,
        ))

    return EstimateResult(
        num_beats=len(beat_estimates),
        draft_model=draft_model,
        forensic_model=forensic_model,
        beat_estimates=beat_estimates,
        draft_retries=settings.draft_audit_retries,
    )
