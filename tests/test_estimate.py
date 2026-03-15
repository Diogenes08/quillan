"""Tests for quillan.estimate and the shared parse_beats_mode helper."""

from __future__ import annotations

import json

import yaml

from quillan.estimate import BeatEstimate, EstimateResult, estimate_draft_cost
from quillan.validate import parse_beats_mode


# ── parse_beats_mode ──────────────────────────────────────────────────────────

def test_parse_beats_mode_all():
    assert parse_beats_mode("all") is None


def test_parse_beats_mode_integer_string():
    assert parse_beats_mode("5") == 5


def test_parse_beats_mode_integer():
    assert parse_beats_mode(10) == 10


def test_parse_beats_mode_zero():
    assert parse_beats_mode("0") == 0


def test_parse_beats_mode_invalid_returns_none():
    assert parse_beats_mode("bogus") is None


def test_parse_beats_mode_none_returns_none():
    assert parse_beats_mode(None) is None  # type: ignore[arg-type]


# ── EstimateResult computed properties ───────────────────────────────────────

def _make_beat(bid: str, di=100, do=50, ai=80, ao=20, si=60, so=10) -> BeatEstimate:
    return BeatEstimate(
        beat_id=bid,
        draft_input=di,
        draft_output=do,
        audit_input=ai,
        audit_output=ao,
        state_input=si,
        state_output=so,
    )


def test_estimate_result_totals():
    beats = [_make_beat("C1-S1-B1"), _make_beat("C1-S1-B2")]
    result = EstimateResult(
        num_beats=2,
        draft_model="openai/gpt-4o-mini",
        forensic_model="openai/gpt-4o-mini",
        beat_estimates=beats,
    )
    assert result.total_draft_input == 200
    assert result.total_draft_output == 100
    assert result.total_forensic_input == 280   # (80+60)*2
    assert result.total_forensic_output == 60   # (20+10)*2


def test_estimate_result_cost_usd_is_float():
    beats = [_make_beat("C1-S1-B1", di=1000, do=500)]
    result = EstimateResult(
        num_beats=1,
        draft_model="openai/gpt-4o-mini",
        forensic_model="openai/gpt-4o-mini",
        beat_estimates=beats,
    )
    cost = result.cost_usd(retries=0)
    assert isinstance(cost, float)
    assert cost >= 0.0


def test_estimate_result_pessimistic_gte_optimistic():
    beats = [_make_beat("C1-S1-B1", di=1000, do=500)]
    result = EstimateResult(
        num_beats=1,
        draft_model="openai/gpt-4o-mini",
        forensic_model="openai/gpt-4o-mini",
        beat_estimates=beats,
        draft_retries=2,
    )
    assert result.cost_usd(retries=2) >= result.cost_usd(retries=0)


def test_estimate_result_as_dict_keys():
    result = EstimateResult(
        num_beats=0,
        draft_model="openai/gpt-4o-mini",
        forensic_model="openai/gpt-4o-mini",
    )
    d = result.as_dict()
    assert "num_beats" in d
    assert "tokens" in d
    assert "cost_usd" in d
    assert "optimistic" in d["cost_usd"]
    assert "pessimistic" in d["cost_usd"]


def test_estimate_result_summary_lines():
    beats = [_make_beat("C1-S1-B1")]
    result = EstimateResult(
        num_beats=1,
        draft_model="openai/gpt-4o-mini",
        forensic_model="openai/gpt-4o-mini",
        beat_estimates=beats,
    )
    lines = result.summary_lines()
    assert any("1" in line for line in lines)
    assert any("Cost" in line for line in lines)


# ── estimate_draft_cost with fixture data ────────────────────────────────────

def _write_dep_map(path, beat_ids: list[str]) -> None:
    deps = {}
    for i, bid in enumerate(beat_ids):
        deps[bid] = [beat_ids[i - 1]] if i > 0 else []
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"dependencies": deps}), encoding="utf-8")


def _write_outline(path, beat_ids: list[str]) -> None:
    beats = [{"beat_id": bid, "title": f"Beat {bid}"} for bid in beat_ids]
    data = {"chapters": [{"chapter_id": "C1", "beats": beats}]}
    path.write_text(yaml.dump(data), encoding="utf-8")


def test_estimate_draft_cost_no_dep_map(paths, settings, world, canon, series, story):
    result = estimate_draft_cost(paths, world, canon, series, story, settings)
    assert result.num_beats == 0


def test_estimate_draft_cost_basic(paths, settings, world, canon, series, story):
    story_dir = paths.story(world, canon, series, story)
    story_dir.mkdir(parents=True, exist_ok=True)

    beat_ids = ["C1-S1-B1", "C1-S1-B2", "C1-S1-B3"]
    _write_dep_map(paths.dependency_map(world, canon, series, story), beat_ids)

    result = estimate_draft_cost(paths, world, canon, series, story, settings, force=True)
    assert result.num_beats == 3
    assert len(result.beat_estimates) == 3


def test_estimate_draft_cost_beats_mode_limit(paths, settings, world, canon, series, story):
    story_dir = paths.story(world, canon, series, story)
    story_dir.mkdir(parents=True, exist_ok=True)

    beat_ids = ["C1-S1-B1", "C1-S1-B2", "C1-S1-B3", "C1-S1-B4"]
    _write_dep_map(paths.dependency_map(world, canon, series, story), beat_ids)

    result = estimate_draft_cost(
        paths, world, canon, series, story, settings, beats_mode="2", force=True
    )
    assert result.num_beats == 2


def test_estimate_draft_cost_skips_drafted(paths, settings, world, canon, series, story):
    story_dir = paths.story(world, canon, series, story)
    story_dir.mkdir(parents=True, exist_ok=True)

    beat_ids = ["C1-S1-B1", "C1-S1-B2"]
    _write_dep_map(paths.dependency_map(world, canon, series, story), beat_ids)

    # Mark C1-S1-B1 as drafted
    draft_path = paths.beat_draft(world, canon, series, story, "C1-S1-B1")
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text("some prose", encoding="utf-8")

    result = estimate_draft_cost(paths, world, canon, series, story, settings, force=False)
    assert result.num_beats == 1  # only undrafted beat counted
