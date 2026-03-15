"""Tests for F7 — Revision Workflow (quillan/draft/revise.py)."""

from __future__ import annotations

import pytest
import yaml
from click.testing import CliRunner


# ── Helpers ───────────────────────────────────────────────────────────────────

BEAT_ID = "C1-S1-B1"
ORIGINAL_PROSE = (
    "She entered the tavern and ordered a whisky. "
    "The barman poured without looking up. "
    "Outside, rain hammered the cobblestones."
)
REVISED_PROSE = (
    "She entered the tavern and ordered a bourbon. "
    "The barman poured without looking up. "
    "Outside, rain hammered the cobblestones."
)


def _write_draft(paths, world, canon, series, story, text=ORIGINAL_PROSE):
    draft = paths.beat_draft(world, canon, series, story, BEAT_ID)
    paths.ensure(draft)
    draft.write_text(text, encoding="utf-8")
    return draft


def _write_spec(paths, world, canon, series, story):
    spec = paths.beat_spec(world, canon, series, story, BEAT_ID)
    paths.ensure(spec)
    spec.write_text(
        yaml.dump({"beat_id": BEAT_ID, "goal": "Open scene", "word_count_target": 300}),
        encoding="utf-8",
    )


class _StreamLLM:
    """Stub LLM: streams revised prose as a single chunk, fakes has_api_keys."""

    class settings:
        has_api_keys = True

    def __init__(self, response: str = REVISED_PROSE):
        self._response = response

    async def call_stream(self, stage, system, user):
        yield self._response


class _FailLLM:
    class settings:
        has_api_keys = True

    async def call_stream(self, *args, **kwargs):
        from quillan.llm import LLMError
        raise LLMError("timeout")
        yield  # pragma: no cover — makes this an async generator


class _OfflineLLM:
    class settings:
        has_api_keys = False

    async def call_stream(self, *args, **kwargs):
        yield ""


# ── revise_beat: core behaviour ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_revise_writes_revised_prose(paths, world, canon, series, story, settings):
    """revise_beat overwrites Beat_Draft.md with the LLM's response."""
    _write_draft(paths, world, canon, series, story)
    llm = _StreamLLM(REVISED_PROSE)

    from quillan.draft.revise import revise_beat
    ok = await revise_beat(
        paths, world, canon, series, story, BEAT_ID, "Change whisky to bourbon.", llm, settings
    )

    assert ok is True
    content = paths.beat_draft(world, canon, series, story, BEAT_ID).read_text()
    assert "bourbon" in content


@pytest.mark.asyncio
async def test_revise_snapshots_original_first(paths, world, canon, series, story, settings):
    """The original draft is snapshotted to versions/ before overwriting."""
    _write_draft(paths, world, canon, series, story)
    llm = _StreamLLM(REVISED_PROSE)

    from quillan.draft.revise import revise_beat
    await revise_beat(
        paths, world, canon, series, story, BEAT_ID, "Change whisky to bourbon.", llm, settings
    )

    versions_dir = paths.beat_versions_dir(world, canon, series, story, BEAT_ID)
    snapshots = list(versions_dir.glob("*.md"))
    assert len(snapshots) == 1
    # Snapshot must contain the ORIGINAL prose
    assert "whisky" in snapshots[0].read_text()


@pytest.mark.asyncio
async def test_revise_returns_false_when_no_draft(paths, world, canon, series, story, settings):
    """revise_beat returns False when Beat_Draft.md doesn't exist."""
    from quillan.draft.revise import revise_beat
    llm = _StreamLLM()
    ok = await revise_beat(
        paths, world, canon, series, story, BEAT_ID, "Some notes.", llm, settings
    )
    assert ok is False


@pytest.mark.asyncio
async def test_revise_returns_false_on_llm_error(paths, world, canon, series, story, settings):
    """revise_beat returns False when the LLM raises LLMError."""
    _write_draft(paths, world, canon, series, story)

    from quillan.draft.revise import revise_beat
    ok = await revise_beat(
        paths, world, canon, series, story, BEAT_ID, "Some notes.", _FailLLM(), settings
    )
    assert ok is False


@pytest.mark.asyncio
async def test_revise_offline_stub_prepends_notes(paths, world, canon, series, story, settings):
    """Without API keys, revise_beat writes a stub with the notes prepended."""
    _write_draft(paths, world, canon, series, story)

    from quillan.draft.revise import revise_beat
    ok = await revise_beat(
        paths, world, canon, series, story, BEAT_ID, "Change whisky to gin.", _OfflineLLM(), settings
    )

    assert ok is True
    content = paths.beat_draft(world, canon, series, story, BEAT_ID).read_text()
    assert "REVISION NOTES" in content
    assert "Change whisky to gin." in content
    assert ORIGINAL_PROSE in content


@pytest.mark.asyncio
async def test_revise_includes_spec_in_prompt(paths, world, canon, series, story, settings):
    """Beat spec content is passed into the user prompt."""
    _write_draft(paths, world, canon, series, story)
    _write_spec(paths, world, canon, series, story)

    captured_user: list[str] = []

    class _CaptureLLM:
        class settings:
            has_api_keys = True

        async def call_stream(self, stage, system, user):
            captured_user.append(user)
            yield REVISED_PROSE

    from quillan.draft.revise import revise_beat
    await revise_beat(
        paths, world, canon, series, story, BEAT_ID, "Make it shorter.", _CaptureLLM(), settings
    )

    assert captured_user
    assert "Open scene" in captured_user[0]   # from the spec
    assert ORIGINAL_PROSE in captured_user[0]  # existing draft
    assert "Make it shorter." in captured_user[0]  # revision notes


@pytest.mark.asyncio
async def test_revise_on_chunk_called(paths, world, canon, series, story, settings):
    """on_chunk callback receives each streamed chunk."""
    _write_draft(paths, world, canon, series, story)

    chunks_received: list[str] = []

    class _MultiChunkLLM:
        class settings:
            has_api_keys = True

        async def call_stream(self, *args, **kwargs):
            yield "First chunk. "
            yield "Second chunk."

    from quillan.draft.revise import revise_beat
    await revise_beat(
        paths, world, canon, series, story, BEAT_ID, "Improve it.",
        _MultiChunkLLM(), settings,
        on_chunk=lambda bid, chunk: chunks_received.append(chunk),
    )

    assert chunks_received == ["First chunk. ", "Second chunk."]


@pytest.mark.asyncio
async def test_revise_partial_file_removed_after_success(paths, world, canon, series, story, settings):
    """The .partial.md file is cleaned up after a successful revision."""
    _write_draft(paths, world, canon, series, story)
    llm = _StreamLLM(REVISED_PROSE)

    from quillan.draft.revise import revise_beat
    await revise_beat(
        paths, world, canon, series, story, BEAT_ID, "Edit.", llm, settings
    )

    draft_path = paths.beat_draft(world, canon, series, story, BEAT_ID)
    assert not draft_path.with_suffix(".partial.md").exists()


# ── CLI: revise command ───────────────────────────────────────────────────────

def _make_story(paths, world, canon, series, story):
    paths.story(world, canon, series, story).mkdir(parents=True, exist_ok=True)


def test_cli_revise_requires_notes_or_file(tmp_path):
    from quillan.cli import main
    from quillan.paths import Paths

    p = Paths(tmp_path)
    _make_story(p, "w", "c", "s", "s")

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--data-dir", str(tmp_path), "--world", "w", "--canon", "c",
         "--series", "s", "revise", "s", BEAT_ID],
    )
    assert result.exit_code == 1
    assert "notes" in result.output.lower() or "notes" in (result.output + result.stderr_bytes.decode() if hasattr(result, "stderr_bytes") else result.output)


def test_cli_revise_notes_and_file_mutually_exclusive(tmp_path):
    from quillan.cli import main

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--data-dir", str(tmp_path), "--world", "w", "--canon", "c",
         "--series", "s", "revise", "s", BEAT_ID,
         "--notes", "text", "--notes-file", str(tmp_path)],
    )
    assert result.exit_code != 0


def test_cli_revise_missing_draft_exits_1(tmp_path):
    from quillan.cli import main
    from quillan.paths import Paths

    p = Paths(tmp_path)
    _make_story(p, "w", "c", "s", "mystory")

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--data-dir", str(tmp_path), "--world", "w", "--canon", "c",
         "--series", "s", "revise", "mystory", BEAT_ID,
         "--notes", "Change something."],
    )
    assert result.exit_code == 1
    assert "no draft" in result.output.lower()


def test_cli_revise_reads_notes_from_file(tmp_path):
    from quillan.cli import main
    from quillan.paths import Paths

    p = Paths(tmp_path)
    _make_story(p, "w", "c", "s", "mystory")
    _write_draft(p, "w", "c", "s", "mystory")

    notes_file = tmp_path / "notes.txt"
    notes_file.write_text("Replace whisky with gin.", encoding="utf-8")

    # No API keys → offline stub path
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--data-dir", str(tmp_path), "--world", "w", "--canon", "c",
         "--series", "s", "revise", "mystory", BEAT_ID,
         "--notes-file", str(notes_file)],
    )
    # Offline stub: exit 0
    assert result.exit_code == 0
    content = p.beat_draft("w", "c", "s", "mystory", BEAT_ID).read_text()
    assert "Replace whisky with gin." in content
