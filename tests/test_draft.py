"""Tests for quillan.draft.draft — specifically the on_chunk callback."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from quillan.config import Settings
from quillan.paths import Paths
from quillan.telemetry import Telemetry


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path, llm_cache=False, telemetry=False)


def _telemetry(tmp_path: Path) -> Telemetry:
    return Telemetry(tmp_path / ".runs", enabled=False)


async def _fake_stream(*args, **kwargs):
    """Async generator yielding 3 known chunks."""
    for chunk in ("Hello ", "brave ", "world"):
        yield chunk


# ── on_chunk callback ──────────────────────────────────────────────────────────

async def test_draft_beat_on_chunk_callback(tmp_path: Path):
    """on_chunk is called once per streamed chunk with (beat_id, delta) pairs."""
    from quillan.draft.draft import draft_beat

    paths = Paths(tmp_path)
    world, canon, series, story, beat_id = "w", "c", "s", "st", "C1-S1-B1"

    # Minimal spec so draft_beat doesn't crash on missing file
    beat_dir = paths.beat(world, canon, series, story, beat_id)
    beat_dir.mkdir(parents=True, exist_ok=True)

    settings = _settings(tmp_path)
    llm = MagicMock()
    llm.settings = settings
    # has_api_keys must be True to reach the streaming branch
    settings_mock = MagicMock()
    settings_mock.has_api_keys = True
    llm.settings = settings_mock
    llm.call_stream = _fake_stream

    received: list[tuple[str, str]] = []

    def on_chunk(bid: str, text: str) -> None:
        received.append((bid, text))

    with patch("quillan.draft.bundle.assemble_bundle", new=AsyncMock()) as mock_bundle:
        # assemble_bundle returns a temp path; we need a real Path that has text
        bundle_path = tmp_path / "bundle.md"
        bundle_path.write_text("# context")
        mock_bundle.return_value = bundle_path

        ok = await draft_beat(
            paths, world, canon, series, story, beat_id,
            attempt=0, llm=llm, settings=settings,
            on_chunk=on_chunk,
        )

    assert ok is True
    assert len(received) == 3
    assert received[0] == (beat_id, "Hello ")
    assert received[1] == (beat_id, "brave ")
    assert received[2] == (beat_id, "world")


async def test_draft_beat_no_on_chunk_does_not_crash(tmp_path: Path):
    """Passing on_chunk=None (default) works without error."""
    from quillan.draft.draft import draft_beat

    paths = Paths(tmp_path)
    world, canon, series, story, beat_id = "w", "c", "s", "st2", "C1-S1-B1"

    beat_dir = paths.beat(world, canon, series, story, beat_id)
    beat_dir.mkdir(parents=True, exist_ok=True)

    settings = _settings(tmp_path)
    settings_mock = MagicMock()
    settings_mock.has_api_keys = True
    llm = MagicMock()
    llm.settings = settings_mock
    llm.call_stream = _fake_stream

    with patch("quillan.draft.bundle.assemble_bundle", new=AsyncMock()) as mock_bundle:
        bundle_path = tmp_path / "bundle2.md"
        bundle_path.write_text("# context")
        mock_bundle.return_value = bundle_path

        ok = await draft_beat(
            paths, world, canon, series, story, beat_id,
            attempt=0, llm=llm, settings=settings,
            # on_chunk omitted — defaults to None
        )

    assert ok is True


# ── Offline stub ───────────────────────────────────────────────────────────────


async def test_draft_beat_offline_stub(tmp_path: Path):
    """Without API keys, draft_beat writes an offline stub and returns True."""
    from quillan.draft.draft import draft_beat
    from unittest.mock import AsyncMock, MagicMock, patch

    paths = Paths(tmp_path)
    world, canon, series, story, beat_id = "w", "c", "s", "st_off", "C1-S1-B1"
    paths.beat(world, canon, series, story, beat_id).mkdir(parents=True, exist_ok=True)

    settings = _settings(tmp_path)
    llm = MagicMock()
    settings_mock = MagicMock()
    settings_mock.has_api_keys = False
    llm.settings = settings_mock

    with patch("quillan.draft.bundle.assemble_bundle", new=AsyncMock()) as mock_bundle:
        bundle_path = tmp_path / "bundle_off.md"
        bundle_path.write_text("# context")
        mock_bundle.return_value = bundle_path

        ok = await draft_beat(
            paths, world, canon, series, story, beat_id,
            attempt=0, llm=llm, settings=settings,
        )

    assert ok is True
    draft_path = paths.beat_draft(world, canon, series, story, beat_id)
    assert draft_path.exists()
    assert "offline stub" in draft_path.read_text(encoding="utf-8")


# ── YAML spec error fallback ───────────────────────────────────────────────────


async def test_draft_beat_bad_spec_yaml_uses_default_word_count(tmp_path: Path):
    """Corrupted spec.yaml doesn't crash draft_beat — falls back to 1500 words."""
    from quillan.draft.draft import draft_beat
    from unittest.mock import AsyncMock, MagicMock, patch

    paths = Paths(tmp_path)
    world, canon, series, story, beat_id = "w", "c", "s", "st_spec", "C1-S1-B1"
    beat_dir = paths.beat(world, canon, series, story, beat_id)
    beat_dir.mkdir(parents=True, exist_ok=True)
    # Write an invalid YAML spec
    paths.beat_spec(world, canon, series, story, beat_id).write_text(
        ": not: valid: yaml: {{{", encoding="utf-8"
    )

    settings = _settings(tmp_path)
    llm = MagicMock()
    settings_mock = MagicMock()
    settings_mock.has_api_keys = True
    llm.settings = settings_mock
    llm.call_stream = _fake_stream

    with patch("quillan.draft.bundle.assemble_bundle", new=AsyncMock()) as mock_bundle:
        bundle_path = tmp_path / "bundle_spec.md"
        bundle_path.write_text("# context")
        mock_bundle.return_value = bundle_path

        ok = await draft_beat(
            paths, world, canon, series, story, beat_id,
            attempt=0, llm=llm, settings=settings,
        )

    assert ok is True


# ── LLMError fallback ──────────────────────────────────────────────────────────


async def test_draft_beat_llm_error_returns_false(tmp_path: Path):
    """When the LLM raises LLMError, draft_beat returns False."""
    from quillan.draft.draft import draft_beat
    from quillan.llm import LLMError
    from unittest.mock import AsyncMock, MagicMock, patch

    paths = Paths(tmp_path)
    world, canon, series, story, beat_id = "w", "c", "s", "st_err", "C1-S1-B1"
    paths.beat(world, canon, series, story, beat_id).mkdir(parents=True, exist_ok=True)

    settings = _settings(tmp_path)
    llm = MagicMock()
    settings_mock = MagicMock()
    settings_mock.has_api_keys = True
    llm.settings = settings_mock

    async def _error_stream(*args, **kwargs):
        raise LLMError("mock LLM failure")
        yield  # make it an async generator

    llm.call_stream = _error_stream

    with patch("quillan.draft.bundle.assemble_bundle", new=AsyncMock()) as mock_bundle:
        bundle_path = tmp_path / "bundle_err.md"
        bundle_path.write_text("# context")
        mock_bundle.return_value = bundle_path

        ok = await draft_beat(
            paths, world, canon, series, story, beat_id,
            attempt=0, llm=llm, settings=settings,
        )

    assert ok is False


# ── N9: buffered partial.md writes ────────────────────────────────────────────

async def test_partial_md_writes_buffered(tmp_path):
    """N9: partial.md is not written on every single chunk — writes are batched."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from quillan.draft.draft import draft_beat
    from quillan.paths import Paths
    import pathlib

    paths = Paths(tmp_path)
    world, canon, series, story, beat_id = "w", "c", "s", "st_buf", "C1-S1-B1"
    paths.beat(world, canon, series, story, beat_id).mkdir(parents=True, exist_ok=True)

    settings = _settings(tmp_path)
    llm = MagicMock()
    settings_mock = MagicMock()
    settings_mock.has_api_keys = True
    llm.settings = settings_mock

    chunk_count = 25  # 25 chunks → buffer-of-10 gives writes at 10, 20, +final = 3

    async def _chunked_stream(*args, **kwargs):
        for i in range(chunk_count):
            yield f"word{i} "

    llm.call_stream = _chunked_stream

    # Count how many times write_text is called on the partial path
    written_count: list[int] = []
    original_write_text = pathlib.Path.write_text

    def counting_write(self, content, **kwargs):
        partial_suffix = ".partial.md"
        if str(self).endswith(partial_suffix):
            written_count.append(1)
        return original_write_text(self, content, **kwargs)

    with (
        patch("quillan.draft.bundle.assemble_bundle", new=AsyncMock()) as mock_bundle,
        patch("quillan.draft.draft.snapshot_beat_draft"),
        patch("quillan.io.atomic_write"),
        patch.object(pathlib.Path, "write_text", counting_write),
    ):
        bundle_path = tmp_path / "bundle_buf.md"
        original_write_text(bundle_path, "# context")
        mock_bundle.return_value = bundle_path

        ok = await draft_beat(
            paths, world, canon, series, story, beat_id,
            attempt=0, llm=llm, settings=settings,
        )

    assert ok is True
    assert len(written_count) < chunk_count, (
        f"Expected fewer writes than chunks ({chunk_count}), got {len(written_count)}"
    )
