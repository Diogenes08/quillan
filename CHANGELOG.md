# Changelog

All notable changes to Quillan are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), versioned per [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.3.0] — 2026-03-19

### Core Engine

- **Rate floor** (`llm_min_call_interval`) — new setting enforces a minimum delay between API calls; prevents free-tier RPM overruns (e.g. `QUILLAN_LLM_MIN_CALL_INTERVAL=5` for Gemini free tier)
- **Improved 429 backoff** — base wait raised from 5s → 65s for rate-limit errors; ensures at least one full Gemini per-minute quota window clears before retry; now logs a warning with attempt count

### Config

- `quillan.env.example` updated with new rate settings and clearer comments
- `README.md` rewritten — accurate install steps, web-app pointer, TUI references removed

### Package

- Completed `quillan2` → `quillan` rename across all imports, env prefixes, and entry points

---

## [1.1.0] — 2026-03-13

### Core Engine

- **Style fingerprint extraction** (`structure/style.py`) — register prose samples and extract a fingerprint injected into every beat context bundle
- **Continuity drift detection** (`continuity/drift.py`) — fast pure-Python scan plus optional LLM deep-check for character/prop/subplot inconsistencies; results written to `continuity/drift_report.json`
- **Character voice profiles** (`structure/dialogue.py`) — per-character dialogue fingerprint included automatically in beat context bundles
- **Beat revision workflow** (`draft/revise.py`) — targeted LLM revision with user-supplied notes; current draft snapshotted before applying
- **Plugin/Hook system** (`hooks.py`) — 6 events (`pre_create`, `post_create`, `pre_draft`, `post_draft`, `pre_export`, `post_export`), 3-tier discovery (global → world → story)
- **Outline editor utilities** (`structure/outline_editor.py`) — outline validation, beat insertion, dependency-map rebuild, YAML formatting
- **Prompt templates externalized** to `templates/` — LLM prompt strings decoupled from Python source

### CLI

Eight new commands:

- `show-outline STORY` — print the outline as YAML
- `edit-outline STORY` — open the outline in `$EDITOR`
- `add-beat STORY --chapter N --goal TEXT` — insert a beat, rebuild dep map, regenerate spec
- `add-sample STORY FILE [--extract-profile]` — register a style reference sample
- `character-voice STORY CHARACTER` — generate or update a dialogue voice profile
- `revise STORY BEAT_ID --notes TEXT` — LLM revision with targeted feedback
- `continuity-check STORY [--llm]` — drift scan (pure-Python, optionally LLM-assisted)
- `hooks STORY` — list installed hooks by event

### Security

- Path component validation on world/canon/series parameters in web endpoints
- `ChangePasswordBody` now requires the current password before accepting a new one
- Minimum 8-character password enforced at registration and password-change endpoints
- `_trim_chars_to_tokens` tail extraction correctness fix
- `lock.py` portability: conditional `fcntl` import for non-Unix platforms
- `lulu.py` cascading import fix in `_load_font()`
- `sanitize_story_name` consolidated in `validate.py` (removed duplicates from web layer)
- `py.typed` PEP 561 marker added

---

## [1.0.0] — 2026-03-12

Initial stable release. Full async Python rewrite of the original Bash Quillan engine.

### Core Engine

- **Filesystem-driven story hierarchy** — worlds → canons (alt-timelines) → series → stories → beats, all paths through `paths.py:Paths`
- **Parallel planning pipeline** — seven artifacts generated concurrently: Creative Brief, Story Spine, Character Arcs, Subplots, Conflict Map, Outline, Dependency Map
- **Beat drafting** — two-phase pipeline: Phase 1 (parallel draft + LLM audit per batch), Phase 2 (serial state patch + continuity)
- **Topological draft order** — Kahn's algorithm DAG from `dependency_map.json`; beats drafted in correct story order respecting dependencies
- **Multi-tier LLM escalation** — three model tiers per stage (0=budget, 1=medium, 2=best); automatic retry + escalation on failure
- **Adaptive throttle** — 429 responses trigger exponential back-off with jitter
- **LLM response cache** — SHA-256 keyed; cache TTL configurable (`QUILLAN_CACHE_TTL_DAYS`, default 30 days)
- **Atomic writes** — all file writes via temp+rename to prevent partial state
- **File locking** — `fcntl.flock`-based async and sync context managers

### Planning Artifacts

- Creative Brief (specificity-gated, optional interview mode)
- Story Spine (act structure, tension curve, turning points)
- Character Arcs
- Subplot Register
- Conflict Map
- Per-beat Spec YAML
- Beat Dependency Map (JSON)
- Universe Bible, Canon Rules, World Axioms, Canon Packet
- Series Handoff (prior-story continuity injection)

### Continuity System

- `continuity/state.py` — dot-notation state patches (set/append/delete), `_meta`/`_locked` key protection
- Queue-based aggregator — batches 3 artifact updates into 1 LLM call; file-lock protected
- Summary, Threads, Ledger maintained per story

### Context Bundle

Each beat draft receives: Canon Packet + Beat Spec + Scope Contract + Author Context + Continuity Deltas + Story History

### Audit System

- `prose_analyzer.py` — zero-LLM: word overuse, bigram repetition, opener dominance, adverb density; thresholds configurable
- `mega_audit` — LLM forensic audit fed prose-analyzer metrics; retries with escalation on failure

### Export

- Markdown, EPUB, DOCX, PDF, print-PDF, MOBI, AZW3 via pandoc
- Audiobook via TTS (OpenAI TTS + ElevenLabs)
- Cover image via DALL-E 3 (`cover_style` configurable)
- Lulu POD bundle (zip with interior PDF + cover)

### Web Interface (FastAPI)

- JWT auth with bcrypt; first user auto-admin
- Stories CRUD with world/canon/series hierarchy
- Background job queue with WebSocket progress streaming
- Plan editor (Brief, Spine, Arcs, Subplots, Conflicts, World artifacts)
- Prose editor with live draft streaming, beat spec editor, history panel
- Story statistics dashboard (word counts, tension sparkline, audit pills, character bars)
- Library (public stories, forking, fork count)
- Version history — list, diff, restore with snapshot-before-restore safety
- Manuscript import (Markdown + DOCX) with optional planning run
- Admin panel: user management, password changes, account deletion
- Mobile-responsive layout with slide-in drawers for beat list and context panel
- Light/dark mode toggle (localStorage persistence)
- `GET /runs` admin endpoint for run history and costs
- Data directory migration via `migrate.py` on startup

### TUI (Textual)

- Beat list with status indicators and lock icon (🔒)
- Draft view with prose rendering
- Context panel (goal, arc, motifs, characters, threads)
- Arc view
- `r` — redraft beat; `h` — author mode (Ctrl-S syncs state); `p` — planning review; `l` — toggle beat lock

### CLI

- `create` — plan + draft new story (with optional `--no-interview`)
- `quickdraft` — minimal spec → immediate draft
- `draft` — draft/redraft beats (`--beats`, `--force`)
- `estimate` — cost estimate before drafting (`--beats`)
- `export` / `publish` — multi-format export (includes `--dry-run`)
- `cover` — generate cover image
- `import-story` — ingest existing Markdown/DOCX manuscript
- `versions` / `restore-beat` — version history management
- `lock-beat` / `unlock-beat` — per-beat human-edit protection (`--all` flag)
- `runs` — table view of run history with cost/token totals (`--limit`, `--run-id`)
- `restore-state` — restore from state checkpoint
- `selftest` — internal integrity checks (no API calls)
- `doctor` — system readiness check: Python version, packages, external tools (pandoc, calibre, ffmpeg), API keys, local LLM connectivity, disk space

### Configuration

- `config.py:Settings` — Pydantic Settings with `QUILLAN_` env prefix; `.env` / `quillan.env` support
- Per-world and per-story `quillan.yaml` override files (API keys blocked from overrides)
- Three provider stages: `planning`, `draft`, `forensic`; three model tiers each
- **Local LLM support** — `planning/draft/forensic/struct_api_base` for Ollama, vLLM, LM Studio
- Temperature and top_p configurable per stage
- Prose analyzer thresholds configurable
- `doctor` command checks local LLM connectivity when `*_api_base` is set

### Reliability & Security

- Beat locking (`.lock` marker file) — skips locked beats even with `--force`
- Story name path traversal sanitized (allowlist `[a-z0-9_-]`)
- JWT secret logs WARNING at startup if using default
- `call_stream()` enforces cost cap
- Silent `except: pass` replaced throughout with `logger.warning`
- WebSocket disconnect handling
- WAL-mode SQLite with single persistent connection

### Telemetry

- Per-run JSONL call log with cost tracking (`MODEL_PRICING` table, updated for 2025 models)
- Cache-hit recording (`record_cache_hit`)
- `load_run_summaries()` for CLI `runs` command
- `finalize()` writes summary JSON including `cache_hits` count

### Data Migration

- `migrate.py:run_migrations()` — version marker at `<data_dir>/.quillan_version`; runs on web startup and CLI init

### Packaging

- `pyproject.toml` — Python ≥ 3.10; optional deps: `tui`, `web`, `tokens`, `cover`, `dev`
- Static files (`style.css`, `app.js`) served via FastAPI `StaticFiles` mount at `/static`
- Single version source of truth: `pyproject.toml` → `importlib.metadata` → `__version__`
- `.gitignore` with standard Python exclusions, `quillan_data/`, `quillan.env`

### Tests

699 tests across 30+ test files. `asyncio_mode = auto`. All async.

---

[1.0.0]: https://github.com/yourorg/quillan/releases/tag/v1.0.0
