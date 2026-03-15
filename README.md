# Quillan2

**AI-assisted story generation for writers.**

Quillan2 takes a short description of your story idea and uses AI to plan it
scene-by-scene, then draft prose for each scene. The result is a full
manuscript that you can export as a Word document, PDF, EPUB, or Markdown file.

Everything it produces — the plan, the outline, every drafted scene — is stored
as ordinary text files on your computer. You can read them, edit them, and pick
up where you left off at any time.

---

## What Quillan2 Does

1. **Plans your story.** From a one-paragraph idea, it builds a world bible,
   a chapter-and-scene outline, and detailed notes for each scene (called
   *beats*). You can review and edit all of these before any prose is written.

2. **Drafts the prose.** It writes each beat in order, carrying forward a
   continuity record (who is where, what has happened, what threads are open)
   so later scenes stay consistent with earlier ones.

3. **Exports the manuscript.** Assembles the scenes into a single document —
   Markdown, Word, EPUB, or PDF.

---

## What You Need

### Python 3.10 or later

Quillan2 is a Python program. Download Python from
[python.org](https://www.python.org/downloads/) if you don't have it. Confirm
your version:

```
python3 --version
```

### AI API keys

Quillan2 uses AI services from three providers. You need accounts and API keys:

| Provider | Used for | Where to get a key |
|---|---|---|
| **OpenAI** | Story planning | [platform.openai.com](https://platform.openai.com/api-keys) |
| **xAI (Grok)** | Drafting prose | [console.x.ai](https://console.x.ai/) |
| **Google Gemini** | Quality checking | [aistudio.google.com](https://aistudio.google.com/) |

An API key is a long string of characters that looks something like
`sk-abc123...`. Think of it as a password that lets Quillan2 use the AI
service on your behalf. Using these services costs money based on the amount
of text generated — the defaults are set to use the cheapest models first.

**Using a local LLM instead?** Quillan2 also works with Ollama, vLLM, and
LM Studio. Point each pipeline stage at your local server's base URL:

```
QUILLAN_DRAFT_API_BASE=http://localhost:11434
QUILLAN_DRAFT_TIER0_MODEL=ollama/llama3
```

No cloud API keys are required when all stages use local base URLs.

### Optional tools for non-Markdown export

To export as Word, PDF, or EPUB you need
[Pandoc](https://pandoc.org/installing.html) installed. For PDF you also need
a LaTeX engine; [TeX Live](https://tug.org/texlive/) or
[MiKTeX](https://miktex.org/) both work. Markdown export works without any
extra tools.

---

## Installation

```bash
# 1. Create a virtual environment (keeps Quillan2 separate from other Python tools)
python3 -m venv quillan_env
source quillan_env/bin/activate      # macOS / Linux
# quillan_env\Scripts\activate       # Windows

# 2. Install Quillan2
pip install -e ".[tui,tokens]"
# Add [web] if you want the web server: pip install -e ".[tui,tokens,web]"

# 3. Verify the installation (no API keys needed for this step)
quillan selftest

# 4. Check system readiness (external tools, API keys, disk space)
quillan doctor
```

If all checks show `[PASS]` or `[WARN]`, you are ready to go. `[FAIL]` items
must be resolved before the affected features will work.

---

## Setting Up Your API Keys

A template configuration file called `quillan.env.example` is included with
Quillan2. Copy it to `quillan.env`, then open it in any text editor — it has
plain-English instructions for every setting. At minimum, fill in your three
API keys at the top of the file.

```bash
cp quillan.env.example quillan.env
```

The full format looks like this:

```
OPENAI_API_KEY=sk-your-openai-key-here
XAI_API_KEY=xai-your-xai-key-here
GEMINI_API_KEY=your-gemini-key-here
```

You can also set these as environment variables in your shell profile. The
`--config` flag lets you point to any `.env` file:

```bash
quillan --config /path/to/my-keys.env create my_idea.txt
```

---

## Quick Start: Your First Story

**Write your idea to a file, then run `publish`.**

```bash
# Write your idea
cat > farm_astronaut.txt <<EOF
A retired astronaut living on a small farm in Montana receives a
mysterious signal that only she can decode. It leads her back into
space — and into a conspiracy that began before she was born.
EOF

# One command: plan → draft → export
quillan --world scifi --config my-keys.env publish farm_astronaut.txt
```

`publish` runs the full pipeline automatically. The finished EPUB appears in:
```
quillan_data/worlds/scifi/.../stories/farm_astronaut/export/farm_astronaut.epub
```

To watch progress as each scene is drafted, add `--verbose`:
```bash
quillan --world scifi publish farm_astronaut.txt --verbose
```

**If your idea is vague** (under ~40 words), Quillan2 generates a
`Creative_Brief_Interview.md` and pauses. Fill in your answers, then re-run.
Or skip the interview entirely:
```bash
quillan publish vague_idea.txt --no-interview
```

---

## Step-by-Step Workflow (Review Between Stages)

Prefer to review the plan before prose is written? Use the three-step workflow:

**Step 1 — Create the story structure.**

```bash
quillan --world scifi --config my-keys.env create farm_astronaut.txt
```

This generates:
- A **world bible** (`Universe_Bible.md`) describing your story's universe
- A **story concept** (`Story_Concept.md`) expanding your idea
- An **outline** (`Outline.yaml`) listing every chapter and scene
- **Scene notes** (`beat_spec.yaml`) for each scene — what happens, who is
  present, what must be established

**Step 2 — Review the plan.**

Open the files and read them. Edit the YAML directly if you want to change the
outline, add a character, or adjust the ending. This is much easier than
editing prose later.

**Step 3 — Draft and export.**

```bash
quillan --world scifi --config my-keys.env draft farm_astronaut
quillan --world scifi --config my-keys.env export farm_astronaut --format docx
```

Draft in stages with `--beats 10` to review a chapter before continuing.

---

## Managing Your Stories

**Check progress on a story:**

```bash
quillan --world scifi status farm_astronaut
```

Shows which planning artifacts exist, beat coverage, export files, and the
estimated cost of the most recent API run.

**List all your stories:**

```bash
quillan list                         # all stories across all worlds
quillan list --world scifi           # filter by world
quillan list --series the_trilogy    # filter by series
```

**Regenerate beat specs** after editing the story spine or character arcs:

```bash
quillan --world scifi regen-specs farm_astronaut
```

**Lock a beat** to prevent it from being overwritten by future drafting runs —
even `--force` will not touch a locked beat:

```bash
quillan --world scifi lock-beat farm_astronaut C1-S1-B3    # lock one beat
quillan --world scifi unlock-beat farm_astronaut C1-S1-B3  # unlock it
quillan --world scifi lock-beat farm_astronaut --all        # lock every beat
```

Locked beats are marked 🔒 in the TUI beat list (press `l` to toggle) and in the web interface.

**Import an existing manuscript** and turn it into a Quillan2 story (automatic
beat splitting by chapter/word count):

```bash
quillan import-story my_novel.md --story my_novel
quillan import-story my_novel.docx --story my_novel --plan   # also run planning pipeline
```

**View past run costs:**

```bash
quillan runs               # table: duration, LLM calls, cache hits, tokens, cost
quillan runs --limit 5     # most recent 5 runs
quillan runs --run-id 20250312_141023_456789   # detail for one run
```

**View and restore draft versions** (every redraft is snapshotted automatically):

```bash
quillan --world scifi versions farm_astronaut C1-S1-B3
quillan --world scifi restore-beat farm_astronaut C1-S1-B3 20250312T141023Z
quillan --world scifi restore-beat farm_astronaut C1-S1-B3 20250312T141023Z --diff
```

---

## Editing Your Outline

After running `create`, you can inspect and modify the generated outline at any time:

```bash
quillan --world scifi show-outline farm_astronaut          # print outline as YAML
quillan --world scifi edit-outline farm_astronaut           # open outline in $EDITOR
quillan --world scifi add-beat farm_astronaut --chapter 2 --goal "Hero escapes the station"
```

`add-beat` inserts a new beat at the end of the chosen chapter, rebuilds the dependency map,
and regenerates the beat spec. Draft the new beat individually with
`draft farm_astronaut --beats C2-S1-B<new>`.

---

## Style Profiles

Give Quillan a set of prose samples to calibrate its voice:

```bash
quillan --world scifi add-sample farm_astronaut sample.md                 # register sample
quillan --world scifi add-sample farm_astronaut sample.md --extract-profile  # and fingerprint
```

The extracted profile is stored as `style_profile.yaml` and is injected into every beat's context
bundle, nudging the LLM toward your preferred sentence length, vocabulary, and rhythm.

---

## Character Voices

Generate a per-character dialogue fingerprint so every character speaks distinctively:

```bash
quillan --world scifi character-voice farm_astronaut "Commander Chen"
```

The voice profile is written to `dialogue/Commander_Chen.yaml` and included automatically in the
context bundle for beats where that character appears.

---

## Revising a Scene

Ask the LLM to improve a specific beat with targeted feedback:

```bash
quillan --world scifi revise farm_astronaut C1-S1-B3 --notes "More tension, less exposition"
```

The current draft is snapshotted before revision so the action is undoable with `restore-beat`.

---

## Checking Continuity

Scan your drafted prose for continuity errors (character detail mismatches, dropped threads, etc.):

```bash
quillan --world scifi continuity-check farm_astronaut          # fast pure-Python pass
quillan --world scifi continuity-check farm_astronaut --llm    # plus LLM deep-check
```

Results are written to `continuity/drift_report.json` inside the story folder.

---

## Plugin Hooks

Run custom scripts at key points in the pipeline:

```bash
quillan --world scifi hooks farm_astronaut    # list installed hooks and their status
```

Hooks are shell scripts or Python files placed in one of three directories (all matching hooks run,
searched in order):

1. `~/.config/quillan/hooks/` — user-global hooks
2. `<data_dir>/worlds/<world>/hooks/` — per-world hooks
3. `<data_dir>/worlds/.../stories/<story>/hooks/` — per-story hooks

Supported events: `pre_create`, `post_create`, `pre_draft`, `post_draft`, `pre_export`, `post_export`.

---

## All-in-One: Quickdraft

If you want to skip the review step and go straight from idea to draft (without
also exporting):

```bash
quillan --world scifi --config my-keys.env quickdraft farm_astronaut.txt
```

This runs `create` and `draft` back to back. Useful for getting a quick
first draft to react to.

---

## Organising Multiple Stories

Stories are stored in a hierarchy: **world → canon → series → story**.

- A **world** is a shared universe. Stories in the same world share world-building
  documents (the universe bible, rules, axioms), so you don't have to re-explain
  your setting from scratch for every story.
- A **canon** is an alternate timeline or continuity within a world. Useful if
  you want to write stories where the events of one don't affect another.
- A **series** is a group of stories within a canon — think of it as a book
  series or story arc.

For a single standalone story, you don't need to think about this at all —
the defaults (`--world default --canon default --series default`) work fine.

```bash
# A trilogy in a shared world
quillan --world my_fantasy_world --series the_trilogy create book1.txt
quillan --world my_fantasy_world --series the_trilogy create book2.txt

# An alternate-universe spin-off
quillan --world my_fantasy_world --canon mirror_universe create spinoff.txt
```

---

## Interactive Terminal Workspace

If you have installed the optional TUI extras (`pip install quillan[tui]`),
you can write, edit, review, and redraft your story interactively in the terminal:

```bash
quillan --world scifi tui farm_astronaut
```

The workspace has three panels: the beat list on the left, draft text in the centre,
and a context panel on the right showing the current beat's goal, tone, active
characters, and open narrative threads.

| Key | Action |
|---|---|
| `j` / `k` | Next / previous beat |
| `e` | Toggle edit mode — edit the draft in-app; saves on exit |
| `h` | Toggle author mode — like edit mode, but `Ctrl+S` also runs state extraction and updates continuity automatically |
| `Ctrl+S` | Save draft in place (author mode: also syncs story state) |
| `E` | Open draft in `$EDITOR` (external editor) |
| `s` | Open beat spec YAML in `$EDITOR` |
| `r` | Force-redraft the current beat using the LLM in the background |
| `l` | Toggle beat lock — prevents this beat from being overwritten by future draft runs |
| `p` | Open the planning review screen — tabbed editor for Brief, Outline, Spine, Arcs, Subplots, Conflicts |
| `a` | Toggle Story Spine arc view (per-beat tension curve) in the context panel |
| `q` | Quit |

**Author mode** (`h`) is designed for human writers: every save triggers an AI pass
that extracts what happened in your prose and updates the continuity record
(character positions, open threads, world state). The context panel refreshes so
you can see which threads you just opened or resolved.

---

## Audiobook and Kindle Export

```bash
# Narrated M4B audiobook via OpenAI TTS (chapter-by-chapter audio assembly)
quillan --world scifi export farm_astronaut --format audiobook

# Kindle formats (requires Calibre's ebook-convert)
quillan --world scifi export farm_astronaut --format mobi
quillan --world scifi export farm_astronaut --format azw3
```

Set the TTS voice in your config file: `QUILLAN_TTS_VOICE=nova`
(choices: `alloy`, `echo`, `fable`, `onyx`, `nova`, `shimmer`).

---

## Cost Estimate Before Drafting

Before spending API credits on a long story, check what it will cost:

```bash
quillan --world scifi estimate farm_astronaut
```

Prints an optimistic and pessimistic USD range based on the story's beat specs
and the current model pricing table. No API calls are made.

---

## Web Interface

Quillan2 includes an optional web server with a browser-based editor:

```bash
pip install "quillan[web]"
export QUILLAN_JWT_SECRET=$(openssl rand -hex 32)
quillan serve
# Open http://localhost:8000 in your browser
```

The web interface supports multiple user accounts, a public story library
(mark your story as public and other users can browse or fork it), real-time
draft progress, and all export formats.

---

## Tips for Better Results

- **Be specific in your idea file.** The more detail you give about genre,
  tone, themes, and character types, the more accurately the AI will plan.

- **Edit the outline before drafting.** The outline stage is your best
  opportunity to shape the story. Moving a scene, cutting a subplot, or
  clarifying a character's motivation is easy in YAML but hard to fix later.

- **Draft incrementally.** Use `--beats 10` to draft a chapter at a time.
  Read the output. If the AI is going in a direction you don't like, edit the
  remaining beat specs before continuing.

- **Reuse your world.** If you write a second story set in the same world,
  use the same `--world` name. Quillan2 will reuse the universe bible instead
  of generating a new one, keeping your universe consistent.

- **Keep your `.env` file safe.** Your API keys give access to paid services.
  Don't share the `.env` file or commit it to version control.

---

## Configuration Reference

All settings can be provided in a `.env` file or as environment variables.
The most commonly used ones:

| Setting | What it does | Default |
|---|---|---|
| `QUILLAN_DATA_DIR` | Where story files are stored | `./quillan_data` |
| `QUILLAN_MAX_PARALLEL` | How many scenes to draft at once | `3` |
| `QUILLAN_LLM_CACHE` | Cache AI responses to save money on reruns | `true` |
| `QUILLAN_DISTILL_CONTINUITY` | Use AI to compress the continuity record | `false` |
| `QUILLAN_MAX_PROMPT_TOKENS` | Token budget per AI call (controls cost) | `32768` |
| `QUILLAN_DRAFT_API_BASE` | Local LLM base URL for draft stage (Ollama/vLLM) | _(cloud)_ |
| `QUILLAN_PLANNING_API_BASE` | Local LLM base URL for planning stage | _(cloud)_ |
| `QUILLAN_FORENSIC_API_BASE` | Local LLM base URL for forensic/audit stage | _(cloud)_ |

---

## Troubleshooting

**"selftest" or "doctor" reports a FAIL**
Re-install: `pip install -e ".[tui,tokens]"` and try again. If a specific
module fails, check that Python 3.10+ is active. Run `quillan doctor` for a
detailed breakdown of what is and isn't working.

**API errors / "no API key"**
Make sure you are passing `--config your-keys.env` and that the file contains
the correct variable names (`OPENAI_API_KEY`, not `OPENAI_KEY`, etc.).

**Export produces Markdown instead of Word/PDF**
Pandoc is not installed. Install it from [pandoc.org](https://pandoc.org/installing.html)
and try again.

**Drafting is slow**
Each scene requires at least one AI call. A 40-beat story may take 10–30
minutes depending on your internet connection and the AI providers' response
times. Increasing `QUILLAN_MAX_PARALLEL` (e.g., to `5`) can help, but may
increase costs and trigger rate limits.

---

## Getting Help

Run any command with `--help` for a full description of its options:

```bash
quillan --help
quillan create --help
quillan draft --help
quillan export --help
quillan doctor --help
quillan runs --help
quillan lock-beat --help
quillan import-story --help
```

---

*Quillan2 is open-source software. All story files it produces belong to you.*
