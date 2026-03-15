"""Tests for Telemetry cost tracking."""

from __future__ import annotations

import json

import pytest


# ── estimated_call_cost ────────────────────────────────────────────────────────

def test_estimated_call_cost_known_model():
    """A known model returns input*rate + output*rate scaled to per-token."""
    from quillan.config import estimated_call_cost
    # gpt-4o-mini: 0.15 input / 0.60 output per 1M tokens
    cost = estimated_call_cost("gpt-4o-mini", input_tokens=1_000_000, output_tokens=0)
    assert abs(cost - 0.15) < 1e-9

    cost = estimated_call_cost("gpt-4o-mini", input_tokens=0, output_tokens=1_000_000)
    assert abs(cost - 0.60) < 1e-9


def test_estimated_call_cost_unknown_model():
    """An unknown model string returns 0.0 — no crash, no KeyError."""
    from quillan.config import estimated_call_cost
    assert estimated_call_cost("totally/unknown-model", 1000, 500) == 0.0


def test_estimated_call_cost_zero_tokens():
    from quillan.config import estimated_call_cost
    assert estimated_call_cost("gpt-4o", 0, 0) == 0.0


# ── Telemetry.record_call with input/output split ──────────────────────────────

def test_record_call_stores_input_output_tokens(tmp_path):
    """record_call stores input_tokens and output_tokens in the call entry."""
    from quillan.telemetry import Telemetry

    tel = Telemetry(tmp_path / "runs", enabled=True)
    tel.record_call("draft", "openai", "gpt-4o-mini", 1500, input_tokens=1000, output_tokens=500)

    assert len(tel._calls) == 1
    entry = tel._calls[0]
    assert entry["input_tokens"] == 1000
    assert entry["output_tokens"] == 500
    assert entry["tokens"] == 1500


def test_record_call_backward_compatible(tmp_path):
    """record_call still works without input_tokens/output_tokens (defaults to 0)."""
    from quillan.telemetry import Telemetry

    tel = Telemetry(tmp_path / "runs", enabled=True)
    tel.record_call("planning", "openai", "gpt-4o", 200)

    entry = tel._calls[0]
    assert entry["input_tokens"] == 0
    assert entry["output_tokens"] == 0
    assert entry["tokens"] == 200


# ── Telemetry.finalize includes estimated_cost_usd ────────────────────────────

def test_finalize_includes_estimated_cost_usd(tmp_path):
    """finalize() writes estimated_cost_usd to the summary JSON."""
    from quillan.telemetry import Telemetry

    tel = Telemetry(tmp_path / "runs", enabled=True)
    # gpt-4o-mini: (0.15 in + 0.60 out) per 1M
    # 1000 input + 500 output → (1000*0.15 + 500*0.60) / 1_000_000 = 0.00045
    tel.record_call(
        "draft", "openai", "gpt-4o-mini", 1500,
        input_tokens=1000, output_tokens=500,
    )
    out_path = tel.finalize()

    assert out_path is not None and out_path.exists()
    data = json.loads(out_path.read_text())
    assert "estimated_cost_usd" in data
    assert data["estimated_cost_usd"] == pytest.approx(0.00045, rel=1e-5)


def test_finalize_zero_cost_for_unknown_model(tmp_path):
    """estimated_cost_usd is 0.0 when the model is not in MODEL_PRICING."""
    from quillan.telemetry import Telemetry

    tel = Telemetry(tmp_path / "runs", enabled=True)
    tel.record_call("draft", "mystery", "mystery/new-model", 100, 50, 50)
    out_path = tel.finalize()

    data = json.loads(out_path.read_text())
    assert data["estimated_cost_usd"] == 0.0


def test_finalize_disabled_returns_none(tmp_path):
    """When telemetry is disabled, finalize() returns None."""
    from quillan.telemetry import Telemetry

    tel = Telemetry(tmp_path / "runs", enabled=False)
    tel.record_call("draft", "openai", "gpt-4o-mini", 100)
    assert tel.finalize() is None


def test_finalize_no_calls(tmp_path):
    """A run with no calls has 0 cost and 0 tokens."""
    from quillan.telemetry import Telemetry

    tel = Telemetry(tmp_path / "runs", enabled=True)
    out_path = tel.finalize()

    data = json.loads(out_path.read_text())
    assert data["total_calls"] == 0
    assert data["total_tokens"] == 0
    assert data["estimated_cost_usd"] == 0.0


def test_finalize_multi_model_cost(tmp_path):
    """Cost is summed correctly across calls with different models."""
    from quillan.telemetry import Telemetry

    tel = Telemetry(tmp_path / "runs", enabled=True)
    # gpt-4o-mini: 1000 in + 0 out → 1000 * 0.15 / 1M = 0.00015
    tel.record_call("planning", "openai", "gpt-4o-mini", 1000, 1000, 0)
    # gpt-4o: 0 in + 500 out → 500 * 10.0 / 1M = 0.005
    tel.record_call("draft", "openai", "gpt-4o", 500, 0, 500)
    out_path = tel.finalize()

    data = json.loads(out_path.read_text())
    expected = (1000 * 0.15 + 500 * 10.0) / 1_000_000
    assert data["estimated_cost_usd"] == pytest.approx(expected, rel=1e-5)


# ── M5: model_pricing.yaml loader ─────────────────────────────────────────────

def test_model_pricing_yaml_loads_bundled_entries():
    """The bundled model_pricing.yaml is loaded and all known models are present."""
    from quillan.config import MODEL_PRICING
    # Spot-check a few models across providers
    assert "gpt-4o-mini" in MODEL_PRICING
    assert "openai/grok-3" in MODEL_PRICING
    assert "gemini/gemini-2.5-pro" in MODEL_PRICING
    assert "claude-sonnet-4-5" in MODEL_PRICING


def test_model_pricing_values_are_float_tuples():
    """Every entry in MODEL_PRICING is a (float, float) tuple."""
    from quillan.config import MODEL_PRICING
    for model, rates in MODEL_PRICING.items():
        assert isinstance(rates, tuple) and len(rates) == 2, f"Bad shape for {model}"
        assert all(isinstance(r, float) for r in rates), f"Non-float rates for {model}"


def test_model_pricing_user_override(tmp_path, monkeypatch):
    """A model_pricing.yaml in the working directory is merged on top of the bundled table."""
    import yaml

    override = tmp_path / "model_pricing.yaml"
    override.write_text(yaml.dump({"my-custom-model": [1.23, 4.56]}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    # Reload the module so _load_model_pricing() runs again in the new cwd
    import quillan.config as cfg_mod
    pricing = cfg_mod._load_model_pricing()

    assert "my-custom-model" in pricing
    assert pricing["my-custom-model"] == pytest.approx((1.23, 4.56))
    # Bundled entries are still present
    assert "gpt-4o-mini" in pricing


def test_model_pricing_override_replaces_existing(tmp_path, monkeypatch):
    """A working-dir override can change the price of a bundled model."""
    import yaml

    override = tmp_path / "model_pricing.yaml"
    override.write_text(yaml.dump({"gpt-4o-mini": [9.99, 99.99]}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    import quillan.config as cfg_mod
    pricing = cfg_mod._load_model_pricing()

    assert pricing["gpt-4o-mini"] == pytest.approx((9.99, 99.99))
