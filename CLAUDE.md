# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All commands assume the venv is active. The venv is at `.venv/`.

```bash
# Install (editable + all dev deps)
.venv/bin/pip install -e ".[dev,tokens]"

# Run all tests
.venv/bin/pytest tests/ -v

# Run a single test file
.venv/bin/pytest tests/test_dag.py -v

# Run a single test by name
.venv/bin/pytest tests/ -k "test_atomic_write"

# Lint
.venv/bin/ruff check quillan/ tests/

# Type check
.venv/bin/mypy quillan/

# Selftest (no API calls)
.venv/bin/quillan selftest
```

## Architecture

Quillan is an async Python story generation engine. It uses LiteLLM to call multiple LLM providers and generates story content stored as a filesystem hierarchy.

### Path hierarchy

All paths flow through `paths.py:Paths`. The data layout is:
```
<data_dir>/
  worlds/<world>/
    canons/<canon>/
      series/<series>/
        stories/<story>/
          outline.yaml
          dependency_map.json
          beats/<beat_id>/
            spec.yaml, draft.md, context.json, inputs.json
            forensics/
          continuity/
            summary.md, threads.yaml, ledger.yaml, queue/
          state/
            bundle.json, current.json
      canon_packet.yaml
  .runs/        # telemetry JSONL
  .cache/       # LLM response cache
  .tmp/         # atomic write temp files
```

`Paths.ensure(path)` creates parents and returns the path — use this before writing.

### Configuration

`config.py:Settings` is a Pydantic Settings class. It reads from environment variables and `.env` files. Key conventions:
- Three provider stages: `planning`, `draft`, `forensic`
- Three model tiers per stage (0=fast/cheap, 1=medium, 2=best); LLM escalates on failure
- `litellm_model_string(stage, tier)` returns the LiteLLM-format string; `litellm_kwargs(stage)` returns api_base/api_key overrides needed for non-OpenAI providers

### LLM calling

`llm.py:LLMClient` is the sole interface to LLMs:
- `await client.call(stage, system, user, mode)` → `str`
- `await client.call_json(stage, system, user, required_keys)` → `dict` (uses `py_extract_json` internally)
- Caches by SHA-256 of (provider, model, mode, system, user); skips cache with `QUILLAN_LLM_CACHE=false`
- Trims user text to `max_prompt_tokens` before sending

### Draft pipeline

`pipeline/runner.py:draft_story()` orchestrates everything:
1. Loads `dependency_map.json`, calls `pipeline/dag.py:compute_batches()` → list of independent beat batches (topological sort / Kahn's algorithm)
2. **Phase 1** (parallel within batch, semaphore-gated): bundle context → draft prose → audit
3. **Phase 2** (serial within batch): extract state patch → apply → update continuity

### Key module responsibilities

| Module | Role |
|---|---|
| `io.py` | `atomic_write(dest, content)`: temp+rename; `cap_file_chars`: sliding window (60% head + 40% tail) |
| `lock.py` | `file_lock(path)` async ctx mgr; `sync_file_lock(path)` for non-async — wraps `fcntl.flock` |
| `validate.py` | `py_extract_json(text, keys)`: strips fences, tries JSON then YAML fallback; typed `validate_*` helpers |
| `token_tool.py` | `estimate_tokens(text)`: tiktoken or word×1.3 heuristic; `trim_to_tokens`: binary-search char boundary |
| `telemetry.py` | `Telemetry(runs_dir)`: per-run JSONL call log + prompt hash forensics; `finalize()` writes summary JSON |
| `continuity/state.py` | `apply_state_patch(state, patch)`: dot-notation set/append/delete with `_meta`/`_locked` protection |

### Tests

`tests/conftest.py` provides fixtures: `data_dir` (tmp_path scoped), `paths`, `settings` (no API keys, telemetry off), `world`/`canon`/`series`/`story` strings. All async tests run automatically via `asyncio_mode = "auto"`.

### Adding a new LLM stage

1. Add `<stage>_provider`, `<stage>_model_tier0/1/2` fields to `Settings`
2. Add a branch in `Settings.provider_for_stage()` and `Settings.model_for_stage()`
3. Call `client.call(stage, ...)` — caching, retry, trimming, and telemetry are automatic
