# Quillan — Writer's Guide

*A complete guide for writers who want to tell their story, not wrestle with software.*

---

## What Is Quillan?

Quillan is a writing companion. You give it a story idea — a sentence, a paragraph,
or a page — and it works with you to turn that idea into a complete manuscript.

It does this in stages, the same way a novelist works:

1. **Planning** — it reads your idea and builds a world, an outline, and a scene-by-scene blueprint.
2. **Reviewing** — you read the plan. Change anything you want before a word of prose is written.
3. **Drafting** — it writes the prose, scene by scene, keeping track of who is where,
   what has happened, and what threads are still open.
4. **Finishing** — it assembles everything into a Word document, EPUB, PDF, or even a
   narrated audiobook.

Everything it produces is saved as ordinary text files. You can read them, edit them,
or ignore them and let Quillan do its work. You are always in control.

---

## Before You Begin

### What you need

**A computer running macOS, Windows, or Linux.** Quillan runs in a program window called
a *terminal* (also called *command prompt* on Windows). You will type short instructions
there. If you have never used a terminal before, that is fine — this guide walks through
every step.

**Python.** Quillan is built in Python, a free programming language. You only need it
installed; you do not need to know how to program. Download Python from
[python.org/downloads](https://www.python.org/downloads/) and install it as you would
any other program. Make sure to check *"Add Python to PATH"* during installation on Windows.

**API keys from three providers.** Quillan uses AI services to generate text. These
services are pay-as-you-go — you create an account, add a small amount of credit, and
are charged for what you use. A typical 40-scene short story costs between $0.50 and $3.00.

| Service | What it does | Where to sign up |
|---|---|---|
| OpenAI | Plans your world and story | platform.openai.com |
| xAI (Grok) | Writes the prose | console.x.ai |
| Google Gemini | Checks quality and continuity | aistudio.google.com |

Each service will give you an *API key* — a long string of letters and numbers. Keep
these private. Think of them like passwords.

---

## Installation

Open your terminal and type the following commands one at a time, pressing Enter after each.

```
python3 -m venv quillan_env
```
*(Creates a private workspace for Quillan so it does not interfere with anything else.)*

On macOS/Linux:
```
source quillan_env/bin/activate
```
On Windows:
```
quillan_env\Scripts\activate
```

Then:
```
pip install quillan[tui,tokens]
```
*(Downloads and installs Quillan. This may take a minute.)*

Finally, verify the installation:
```
quillan selftest
```

You should see a list of checks all marked `[PASS]`. If you see any `[FAIL]`, try
re-running the pip install command and checking that Python 3.10 or later is active.

---

## Setting Up Your Keys

Quillan ships with a template settings file called `quillan.env.example`. Copy it
to create your personal settings file:

```
cp quillan.env.example quillan.env
```

Open `quillan.env` in any text editor (Notepad, TextEdit, or whatever you prefer).
Near the top you will see:

```
OPENAI_API_KEY=
XAI_API_KEY=
GEMINI_API_KEY=
```

Paste your API keys after the `=` sign on each line:

```
OPENAI_API_KEY=sk-abcdefghijklmnop...
XAI_API_KEY=xai-abcdefghijklmnop...
GEMINI_API_KEY=AIzaSy...
```

Save the file. You will point Quillan to this file every time you run it.

### Checking your setup

After filling in your keys, run:

```
quillan --config quillan.env doctor
```

This checks that your Python version is supported, all required packages are
installed, external tools like Pandoc are available, and that each API key actually
reaches its provider. It exits with a summary of what passed and what needs
attention — a useful step before your first draft run.

---

## Your First Story

### Step 1 — Write your idea

Open a text editor and write your story idea. It can be one sentence or several
paragraphs. Save it as a plain text file — for example, `my_story.txt`.

A good idea file might look like this:

```
A retired lighthouse keeper on a remote Scottish island begins finding messages
in bottles that seem to be from her late husband — except the messages describe
events that haven't happened yet.
```

### Step 2 — Run the one-command version

The simplest way to get a finished manuscript is `publish`:

```
quillan --config quillan.env publish my_story.txt
```

Quillan will:
- Read your idea and build a detailed plan
- Write prose for every scene
- Assemble a finished EPUB file

The finished file appears in a folder called `quillan_data` inside your current directory.
The exact path is printed at the end of the run.

**This may take 15–40 minutes** for a full story. Quillan is making dozens of AI
calls, one for each scene. You will see progress printed as it works.

---

## The Careful Approach: Plan First, Then Write

Many writers prefer to review the plan before any prose is written. Here is how:

### Step 1 — Create the plan

```
quillan --config quillan.env create my_story.txt
```

Quillan generates a folder of planning documents. The most important ones are:

- **Universe_Bible.md** — your world's history, geography, and rules
- **Outline.yaml** — every chapter and scene, in order
- **Creative_Brief.yaml** — the voice, tone, and themes that will govern the prose

Open these files and read them. They are plain text — edit anything you like.

> **Tip:** The outline is the most valuable thing to get right. Moving a scene, cutting
> a subplot, or adjusting an ending is easy here. Fixing it after the prose is written
> is much harder.

### Step 2 — Draft the prose

When you are happy with the plan:

```
quillan --config quillan.env draft my_story
```

*(Note: `my_story` without `.txt` — Quillan knows to look for the already-created story.)*

You can draft in stages. To draft only the first ten scenes and read them before
continuing:

```
quillan --config quillan.env draft my_story --beats 10
```

Run the command again to continue from scene eleven. Already-drafted scenes are
automatically skipped.

### Step 3 — Export your manuscript

```
quillan --config quillan.env export my_story --format docx
```

This produces a Word document. Other formats:

| Command | What you get |
|---|---|
| `--format epub` | An e-book file (for Kindle, Kobo, etc.) |
| `--format pdf` | A PDF document |
| `--format mobi` | Kindle format (requires Calibre — see below) |
| `--format audiobook` | A narrated M4B audiobook |
| `--format markdown` | Plain text (the simplest, needs no extra tools) |

---

## Watching Your Story Take Shape

While Quillan is drafting, you can watch the prose appear in real time by adding `--stream`:

```
quillan --config quillan.env draft my_story --stream --verbose
```

A file called `my_story.live.md` will appear in your story folder and update after
each scene is written. Open it in any Markdown viewer — or just a text editor — while
the draft runs.

---

## Checking Progress

To see where you are at any point:

```
quillan --config quillan.env status my_story
```

This shows which planning documents exist, how many scenes have been drafted, and
what export files have been produced. No AI calls are made.

To see all your stories at once:

```
quillan list
```

---

## Checking Cost Before You Draft

Before committing to a long draft run, you can ask Quillan to estimate the cost:

```
quillan --config quillan.env estimate my_story
```

This reads your scene notes and prints an estimated cost range in US dollars.
No AI calls are made; nothing is written to disk.

---

## Writing Scenes Yourself

Quillan is not just for AI-generated prose. You can write any scene yourself and
let Quillan maintain the continuity record around your writing.

### The Terminal Writing Interface

If you enjoy writing in a focused, distraction-free terminal environment:

```
quillan --config quillan.env tui my_story
```

This opens a three-panel workspace:
- **Left panel** — your list of scenes, with a tick next to each drafted scene
- **Centre** — the draft text for the selected scene
- **Right panel** — context for the current scene: goal, tone, characters, open threads

**To write a scene yourself:**
1. Select it with `j` (down) or `k` (up)
2. Press `h` to enter *author mode*
3. Write your prose
4. Press `Ctrl+S` to save

When you save in author mode, Quillan reads your prose and updates its understanding
of the story — who is where, what threads are open, what has changed. This keeps
the continuity intact even when you are writing the scenes, not the AI.

**Other things you can do in the workspace:**

| What you want | Key |
|---|---|
| Review and edit the outline or character notes | `p` |
| Ask the AI to rewrite the current scene | `r` |
| Browse the story arc (tension curve by scene) | `a` |
| Edit the current scene in your favourite text editor | `E` |
| Edit the current scene's detailed notes | `s` |
| Return to browsing without saving | `e` (toggles edit mode off) |
| Quit | `q` |

---

## Importing an Existing Manuscript

If you have already written some or all of a story, you can bring it into Quillan
so it can manage continuity and help you continue writing:

```
quillan --config quillan.env import-story my_draft.docx
```

Quillan splits the manuscript into scenes, builds a stub outline, and creates a
beat spec for each scene. You can then continue drafting new scenes, re-draft
existing ones, or simply use the TUI to review what is there.

Pass `--plan` to also run the full planning pipeline and generate a Universe Bible,
Character Arcs, and other planning documents:

```
quillan --config quillan.env import-story my_draft.docx --plan
```

Supported formats: Markdown (`.md`), Word (`.docx`).

---

## Locking a Scene

Once you are happy with a scene and do not want Quillan to overwrite it — even when
you run `draft --force` — you can lock it:

```
quillan --config quillan.env lock-beat my_story C1-S1-B1
```

To remove the lock:

```
quillan --config quillan.env unlock-beat my_story C1-S1-B1
```

You can also lock and unlock scenes from inside the TUI by pressing `l`.

---

## Version History

Every time a scene is drafted or manually saved, the previous version is kept.
To list saved versions for a scene:

```
quillan --config quillan.env versions my_story C1-S1-B1
```

To restore an earlier version:

```
quillan --config quillan.env restore-beat my_story C1-S1-B1 20260101T120000z
```

Add `--diff` to preview the changes before restoring, or `--force` to skip the
confirmation prompt.

---

## Run History and Cost Tracking

After each draft run, Quillan records how many tokens were used and the estimated
cost. To see a summary of recent runs:

```
quillan runs
```

This prints a table with the date, story, total tokens, and estimated USD cost for
each run. Useful for keeping an eye on spending during a long project.

---

## Revising a Scene

Sometimes a scene is almost right but needs a targeted tweak. Rather than asking the LLM to
redraft from scratch, use `revise` to apply specific notes:

```bash
quillan revise my_story C2-S1-B3 --notes "Less exposition; show tension through dialogue"
```

Before the revision runs, the current draft is automatically snapshotted, so if you prefer the
original you can recover it with `restore-beat`.

---

## Checking Story Continuity

After drafting several scenes, it is worth checking whether anything has drifted — a character's
eye colour changed, a prop appeared before it was introduced, or a subplot thread was dropped.

Run a fast pure-Python scan:

```bash
quillan continuity-check my_story
```

For a deeper check that uses an LLM to reason about subtler inconsistencies:

```bash
quillan continuity-check my_story --llm
```

Results are saved to `continuity/drift_report.json` inside the story folder, so you can review
them and decide which issues to address.

---

## Editing Your Outline

You can inspect and modify the outline at any time after `create`:

```bash
quillan show-outline my_story          # print the full outline as YAML
quillan edit-outline my_story          # open it in $EDITOR for freeform edits
quillan add-beat my_story --chapter 2 --goal "Hero realises the map is forged"
```

`add-beat` inserts a new beat at the end of the chosen chapter and automatically regenerates its
beat spec and dependency map. You can then draft the new beat individually with
`draft my_story --beats C2-S1-B<new>`.

---

## Style Profiles

To steer the prose style, add reference samples — short passages written in the voice you want:

```bash
quillan add-sample my_story reference.md                    # add a sample without extracting
quillan add-sample my_story reference.md --extract-profile  # add and fingerprint immediately
```

The extracted `style_profile.yaml` encodes sentence-length distribution, lexical density, and
other prose characteristics. Quillan includes this profile in every beat's context bundle, nudging
the LLM toward your preferred writing style.

---

## Character Voices

For stories with distinct characters, you can generate a per-character dialogue fingerprint:

```bash
quillan character-voice my_story "Detective Raines"
```

This analyses how the character speaks across the drafted beats (or uses planning documents if
beats are not yet drafted) and writes a `dialogue/<character>.yaml` profile. Beat context bundles
for scenes featuring that character include the profile automatically.

---

## Plugin Hooks

Hooks let you run custom code at specific points in the pipeline — for instance, to validate
output, send a notification, or post-process files.

List the hooks installed for a story:

```bash
quillan hooks my_story
```

To create a hook, place a shell script or Python file named after the event in one of these
directories (checked in order, all matching hooks run):

| Directory | Scope |
|---|---|
| `~/.config/quillan/hooks/` | Every story on this machine |
| `<data_dir>/worlds/<world>/hooks/` | Every story in a world |
| `<data_dir>/worlds/.../stories/<story>/hooks/` | One specific story |

Supported events: `pre_create`, `post_create`, `pre_draft`, `post_draft`, `pre_export`, `post_export`.

---

## Multiple Stories in the Same World

If you are writing a series, or want two stories to share the same world-building:

```
quillan --world my_world --config quillan.env create book1.txt
quillan --world my_world --config quillan.env create book2.txt
```

The `--world` flag tells Quillan to reuse the Universe Bible, Canon Rules, and other
world documents instead of generating new ones. Each story still has its own outline,
scenes, and characters — they just share the same setting.

---

## Generating a Cover Image

Quillan can generate a cover image using DALL-E 3:

```
quillan --config quillan.env cover my_story
```

Or use your own image:

```
quillan cover my_story --image my_own_cover.png
```

---

## Audiobook Narration

If you want a narrated audiobook:

```
quillan --config quillan.env export my_story --format audiobook
```

This uses OpenAI's text-to-speech to narrate each chapter, then assembles them
into a single M4B file with chapter markers — the same format used by Audible and
Apple Books. You can choose from six voices in your `quillan.env` file:

```
QUILLAN_TTS_VOICE=nova
```

Voices: `alloy`, `echo`, `fable`, `onyx`, `nova`, `shimmer`.

If the assembly tools are not available, Quillan falls back to a ZIP of individual
chapter MP3 files.

---

## Kindle Export

Kindle's native formats (`.mobi` and `.azw3`) require
[Calibre](https://calibre-ebook.com/download) to be installed. Calibre is a free
e-book management program. Once installed:

```
quillan --config quillan.env export my_story --format mobi
```

---

## The Web Interface

If you would rather use a browser than a terminal for day-to-day writing:

```
pip install quillan[web]
quillan serve --dev
```

Then open [http://localhost:8000](http://localhost:8000) in your browser.

The web interface offers all the same features — planning, drafting, editing,
exporting — plus a public story library where you can share finished stories
and browse or *fork* (take a copy of) stories published by other writers.

---

## Using a Local LLM

Quillan can route any pipeline stage to a local model running via Ollama, LM Studio,
vLLM, or any OpenAI-compatible server. Set the API base URL in your `quillan.env`:

```
# Send all draft calls to a local Ollama server
QUILLAN_DRAFT_API_BASE=http://localhost:11434/v1

# Or send planning calls there too
QUILLAN_PLANNING_API_BASE=http://localhost:11434/v1
```

No API key is required when a local base URL is set. This is useful for offline
work, cost control, or experimenting with open-source models. The same LLM caching,
retry, and escalation logic applies.

---

## Per-Story Settings

You can override any setting for a specific story (or a whole world) without touching
your main `quillan.env`. Create a file called `quillan.yaml` inside the story folder:

```
quillan_data/worlds/my_world/canons/default/series/default/stories/my_story/quillan.yaml
```

Example — use a cheaper model and tighter context for one story:

```yaml
planning_tier0_model: gpt-4o-mini
max_prompt_tokens: 16384
draft_temperature: 0.9
```

You can also place a `quillan.yaml` at the world level to affect all stories in
that world:

```
quillan_data/worlds/my_world/quillan.yaml
```

World settings are applied first; story settings win over world settings. API keys
can never be set here — they must come from environment variables or `quillan.env`.

---

## When Something Goes Wrong

**"selftest" shows a FAIL**
Re-run the installation: `pip install quillan[tui,tokens]` and try `selftest` again.

**"No API key" error**
Make sure you are passing `--config quillan.env` and that the keys in the file
are filled in correctly. The variable names must be exact:
`OPENAI_API_KEY`, `XAI_API_KEY`, `GEMINI_API_KEY`.

**Drafting produces very short scenes**
Add more detail to your idea file, or edit the `Outline.yaml` to expand the goal
for each beat before drafting.

**Export produces Markdown instead of Word/PDF**
[Pandoc](https://pandoc.org/installing.html) is not installed. Install it and try again.
PDF additionally requires a LaTeX engine; [TeX Live](https://tug.org/texlive/)
or [MiKTeX](https://miktex.org/) both work.

**Drafting is slow**
Each scene requires at least one AI call. A 40-scene story may take 15–40 minutes.
You can increase the number of scenes drafted at the same time by adding
`QUILLAN_MAX_PARALLEL=5` to your `quillan.env` file — but note that this may
increase costs and may trigger rate limits with some providers.

---

## A Typical Day with Quillan

Here is what a productive session might look like:

1. Open your terminal and activate your Quillan environment.
2. Run `quillan status my_story` to see where you left off.
3. Open the TUI: `quillan tui my_story`
4. Press `p` to review your outline and make any changes.
5. Press `Escape` to return, then navigate to the first unwritten scene.
6. Press `h` to enter author mode and write the scene.
7. Press `Ctrl+S` to save (Quillan updates the continuity record automatically).
8. Press `r` on any scene that feels off — Quillan rewrites it.
9. When you are ready for a longer drafting run, quit the TUI and run
   `quillan draft my_story --beats 10 --verbose`.
10. Export when ready: `quillan export my_story --format docx`.

---

*Quillan is designed to stay out of your way. The words are yours.*
