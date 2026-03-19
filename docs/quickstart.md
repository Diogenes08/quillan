# Quillan — Quick Reference

*From idea to finished manuscript in four commands.*

---

## What It Does

You write one paragraph. Quillan writes the book.

It plans your world, outlines every scene, drafts the prose, tracks continuity
across 40+ scenes, and exports a finished Word document, EPUB, PDF, Kindle file,
or narrated audiobook.

All generated files are plain text on your computer. You can read, edit, or
ignore them at any point.

---

## The Four-Command Workflow

```bash
# 1. Write your idea
echo "A retired spy discovers her handler is still alive — and working for the other side" > idea.txt

# 2. Plan the story (generates outline, characters, world)
quillan --config keys.env create idea.txt

# 3. Review the plan, edit anything you like, then draft
quillan --config keys.env draft my_story --verbose

# 4. Export
quillan --config keys.env export my_story --format docx
```

Or collapse steps 2–4 into one:

```bash
quillan --config keys.env publish idea.txt
```

---

## Key Commands

| Command | What it does |
|---|---|
| `create idea.txt` | Build the story plan (no prose yet) |
| `draft my_story` | Write prose for every scene |
| `draft my_story --beats 10` | Draft 10 scenes, then pause to review |
| `draft my_story --cascade --beats C2-S1-B1` | Re-draft a scene and everything after it |
| `estimate my_story` | See the expected API cost before running |
| `export my_story --format epub` | Produce an EPUB e-book |
| `export my_story --format audiobook` | Produce a narrated M4B audiobook |
| `status my_story` | Check progress (no API calls) |
| `tui my_story` | Open the interactive terminal workspace |
| `publish idea.txt` | Plan + draft + export in one step |
| `import-story manuscript.docx` | Ingest an existing manuscript as a new story |
| `lock-beat my_story C1-S1-B1` | Protect a beat from being overwritten by `--force` |
| `unlock-beat my_story C1-S1-B1` | Remove the lock from a beat |
| `versions my_story C1-S1-B1` | List saved drafts for a beat |
| `restore-beat my_story C1-S1-B1 20260101T120000z` | Restore a previous draft version |
| `restore-state my_story` | Recover continuity state from a checkpoint |
| `runs` | Show cost and token summaries for recent runs |
| `doctor` | Check API keys, tools, and system readiness |
| `selftest` | Verify installation (no API keys needed) |
| `show-outline my_story` | Print the story outline as YAML |
| `edit-outline my_story` | Open the outline in `$EDITOR` |
| `add-beat my_story --chapter 2 --goal "..."` | Insert a new scene into a chapter |
| `add-sample my_story ref.md --extract-profile` | Register a style reference and extract a fingerprint |
| `character-voice my_story "Name"` | Generate a per-character dialogue voice profile |
| `revise my_story C1-S1-B3 --notes "..."` | Ask the LLM to revise a beat with specific feedback |
| `continuity-check my_story` | Scan for continuity errors in drafted prose |
| `hooks my_story` | List installed plugin hooks |

---

## TUI Workspace Keys

```
quillan tui my_story
```

| Key | Action |
|---|---|
| `j` / `k` | Next / previous scene |
| `e` | Edit the current scene in-app |
| `h` | Author mode — saves and syncs story state on Ctrl+S |
| `r` | AI-redraft the current scene |
| `l` | Lock / unlock the current scene (protect from `--force` re-draft) |
| `p` | Review and edit all planning documents |
| `a` | Arc view — tension curve across all scenes |
| `s` | Edit scene notes in external editor |
| `q` | Quit |

---

## Export Formats

| Format | Command | Extra tools needed |
|---|---|---|
| Markdown | `--format markdown` | None |
| Word (.docx) | `--format docx` | Pandoc |
| EPUB | `--format epub` | Pandoc |
| PDF | `--format pdf` | Pandoc + LaTeX |
| Kindle (.mobi) | `--format mobi` | Pandoc + Calibre |
| Kindle (.azw3) | `--format azw3` | Pandoc + Calibre |
| Audiobook (.m4b) | `--format audiobook` | OpenAI TTS API key |

---

## Story Organisation

Stories nest in a four-level hierarchy: **world → canon → series → story**.

For a standalone story you never need to think about this — the defaults work fine.
For a series or shared universe:

```bash
# Two books sharing a world
quillan --world my_world create book1.txt
quillan --world my_world create book2.txt
```

Stories in the same world share the Universe Bible, Canon Rules, and character
registry. Continuity is carried forward automatically from one story to the next.

---

## Cost

A 40-scene short story (approx. 12,000 words) typically costs $0.50–$3.00 in API
credits across the three default providers (OpenAI, xAI, Google Gemini).

Check cost before running:

```bash
quillan estimate my_story
```

LLM responses are cached — re-running after a change only charges for the changed
scenes.

---

## What You Need

- Python 3.10+
- API keys: `OPENAI_API_KEY`, `XAI_API_KEY`, `GEMINI_API_KEY`
- For Word/EPUB/PDF: [pandoc.org](https://pandoc.org)
- For Kindle: [calibre-ebook.com](https://calibre-ebook.com)
- For audiobook: OpenAI API key (same as planning key)

Full installation instructions: see `docs/user-guide.md` or the project README.
