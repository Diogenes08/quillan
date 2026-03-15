"""Multi-provider TTS audiobook export for Quillan2.

Supported providers (set QUILLAN_TTS_PROVIDER):
  openai      — OpenAI TTS (tts-1 / tts-1-hd).  Requires OPENAI_API_KEY.
  elevenlabs  — ElevenLabs TTS.  Requires QUILLAN_ELEVENLABS_API_KEY.

Produces per-chapter MP3s, then assembles them into an M4B (with chapter
markers) if ffmpeg/ffprobe are available, or a ZIP of MP3s as fallback.

Requires: openai>=1.0 (transitively provided by litellm) for OpenAI provider.
          httpx for ElevenLabs provider (transitively provided by FastAPI).
Optional: ffmpeg + ffprobe for M4B assembly.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from quillan.config import Settings
    from quillan.paths import Paths

_MAX_CHUNK_CHARS = 4_096
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


# ── Text chunking ─────────────────────────────────────────────────────────────


def split_into_tts_chunks(text: str, max_chars: int = _MAX_CHUNK_CHARS) -> list[str]:
    """Split *text* into TTS-safe segments at sentence boundaries.

    Falls back to word-boundary splits when a sentence exceeds *max_chars*.
    """
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    sentences = _SENTENCE_END.split(text)
    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        candidate = (current + " " + sentence).strip() if current else sentence
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            if len(sentence) <= max_chars:
                current = sentence
            else:
                # Hard-split overlong sentence at word boundaries
                words = sentence.split()
                current = ""
                for word in words:
                    test = (current + " " + word).strip() if current else word
                    if len(test) <= max_chars:
                        current = test
                    else:
                        if current:
                            chunks.append(current)
                        current = word

    if current:
        chunks.append(current)
    return chunks


# ── TTS Provider interface + implementations ──────────────────────────────────


class _TTSProvider:
    """Base class for TTS providers.  Subclasses implement ``synthesize_chunk``."""

    async def synthesize_chunk(self, text: str) -> bytes:  # pragma: no cover
        raise NotImplementedError

    def check_credentials(self) -> None:
        """Raise RuntimeError with a helpful message if credentials are missing."""
        raise NotImplementedError


class _OpenAITTS(_TTSProvider):
    def __init__(self, settings: "Settings") -> None:
        self._settings = settings

    def check_credentials(self) -> None:
        if not self._settings.openai_api_key:
            raise RuntimeError(
                "OpenAI TTS requires OPENAI_API_KEY. "
                "Set it or switch to another provider via QUILLAN_TTS_PROVIDER."
            )

    async def synthesize_chunk(self, text: str) -> bytes:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=self._settings.openai_api_key)
        response = await client.audio.speech.create(
            model=self._settings.tts_model,
            voice=self._settings.tts_voice,  # type: ignore[arg-type]
            input=text,
            response_format="mp3",
        )
        return response.content


class _ElevenLabsTTS(_TTSProvider):
    _BASE = "https://api.elevenlabs.io/v1/text-to-speech"

    def __init__(self, settings: "Settings") -> None:
        self._settings = settings

    def check_credentials(self) -> None:
        if not self._settings.elevenlabs_api_key:
            raise RuntimeError(
                "ElevenLabs TTS requires QUILLAN_ELEVENLABS_API_KEY. "
                "Set it or switch to another provider via QUILLAN_TTS_PROVIDER."
            )

    async def synthesize_chunk(self, text: str) -> bytes:
        import httpx
        s = self._settings
        url = f"{self._BASE}/{s.elevenlabs_voice_id}"
        headers = {
            "xi-api-key": s.elevenlabs_api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload = {
            "text": text,
            "model_id": s.elevenlabs_model,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            return resp.content


def get_tts_provider(settings: "Settings") -> _TTSProvider:
    """Return the configured TTS provider instance."""
    provider_name = (settings.tts_provider or "openai").lower()
    if provider_name == "elevenlabs":
        return _ElevenLabsTTS(settings)
    return _OpenAITTS(settings)


# ── Audio assembly helpers ────────────────────────────────────────────────────


def _ffmpeg_available() -> bool:
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _ffprobe_available() -> bool:
    try:
        result = subprocess.run(
            ["ffprobe", "-version"], capture_output=True, timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _concat_mp3s(src_paths: list[Path], dest: Path) -> None:
    """Concatenate MP3s using ffmpeg concat demuxer."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        for p in src_paths:
            f.write(f"file '{p}'\n")
        list_path = f.name
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
             "-acodec", "copy", str(dest)],
            check=True, capture_output=True, timeout=300,
        )
    finally:
        os.unlink(list_path)


def _mp3_duration_ms(path: Path) -> int:
    """Return duration of MP3 in milliseconds via ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", str(path)],
        capture_output=True, timeout=30,
    )
    data = json.loads(result.stdout)
    return int(float(data["format"]["duration"]) * 1000)


def _build_m4b(
    chapter_mp3s: list[tuple[int, str, Path]],
    out_path: Path,
    story_title: str,
) -> None:
    """Assemble M4B with chapter marks from per-chapter MP3s.

    Requires both ffmpeg and ffprobe.
    """
    concat_tmp = out_path.with_suffix(".concat_tmp.mp3")
    meta_path: str | None = None
    list_path: str | None = None

    try:
        # Step 1: concat all chapter MP3s to a single audio file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            for _, _, p in chapter_mp3s:
                f.write(f"file '{p}'\n")
            list_path = f.name

        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
             "-acodec", "copy", str(concat_tmp)],
            check=True, capture_output=True, timeout=600,
        )

        # Step 2: measure each chapter's duration
        cumulative = 0
        chapter_ranges: list[tuple[int, int, str]] = []  # (start_ms, end_ms, title)
        for ch_num, ch_title, mp3_path in chapter_mp3s:
            start = cumulative
            cumulative += _mp3_duration_ms(mp3_path)
            chapter_ranges.append((start, cumulative, ch_title))

        # Step 3: write ffmpeg chapter metadata
        meta_lines = [";FFMETADATA1", f"title={story_title}", ""]
        for start, end, ch_title in chapter_ranges:
            meta_lines += [
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={start}",
                f"END={end}",
                f"title={ch_title}",
                "",
            ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("\n".join(meta_lines))
            meta_path = f.name

        # Step 4: re-encode to AAC M4B with chapter metadata
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(concat_tmp), "-i", meta_path,
             "-map_metadata", "1", "-c:a", "aac", "-b:a", "64k", str(out_path)],
            check=True, capture_output=True, timeout=600,
        )
    finally:
        if list_path:
            os.unlink(list_path)
        if meta_path:
            os.unlink(meta_path)
        if concat_tmp.exists():
            concat_tmp.unlink()


def _build_zip(chapter_mp3s: list[tuple[int, str, Path]], out_path: Path) -> None:
    """Bundle chapter MP3s into a ZIP archive."""
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_STORED) as zf:
        for ch_num, ch_title, mp3_path in chapter_mp3s:
            safe_title = re.sub(r"[^\w\s-]", "", ch_title).replace(" ", "_")
            zf.write(mp3_path, f"Chapter_{ch_num:02d}_{safe_title}.mp3")


# ── Chapter synthesis ─────────────────────────────────────────────────────────


async def synthesize_chapter(
    chapter_num: int,
    chapter_title: str,
    chapter_text: str,
    chunk_dir: Path,
    settings: "Settings",
    on_progress: Callable[[str], None] | None = None,
    *,
    provider: "_TTSProvider | None" = None,
) -> Path:
    """Synthesize one chapter to MP3.  Chunk files are cached on disk for resume.

    Returns path to the assembled chapter MP3.
    """
    if provider is None:
        provider = get_tts_provider(settings)

    chunks = split_into_tts_chunks(chapter_text)
    if not chunks:
        raise ValueError(f"Chapter {chapter_num} ({chapter_title!r}) has no text")

    chunk_dir.mkdir(parents=True, exist_ok=True)
    chunk_paths: list[Path] = []

    for i, chunk in enumerate(chunks):
        chunk_path = chunk_dir / f"chunk_{i:04d}.mp3"
        if not chunk_path.exists():
            if on_progress:
                on_progress(
                    f"  Synthesizing chapter {chapter_num} chunk {i + 1}/{len(chunks)}…"
                )
            audio = await provider.synthesize_chunk(chunk)
            chunk_path.write_bytes(audio)
        chunk_paths.append(chunk_path)

    chapter_mp3 = chunk_dir.parent / f"chapter_{chapter_num:03d}.mp3"

    if len(chunk_paths) == 1:
        shutil.copy2(chunk_paths[0], chapter_mp3)
    elif _ffmpeg_available():
        _concat_mp3s(chunk_paths, chapter_mp3)
    else:
        # No ffmpeg: use the first chunk only (best-effort)
        shutil.copy2(chunk_paths[0], chapter_mp3)

    return chapter_mp3


# ── Top-level export ──────────────────────────────────────────────────────────


async def export_audiobook(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    settings: "Settings",
    on_progress: Callable[[str], None] | None = None,
) -> Path:
    """Generate an audiobook from a story's drafted beats.

    Produces M4B (with chapter markers) if ffmpeg+ffprobe are available,
    otherwise a ZIP of per-chapter MP3s.

    Returns the path to the output file.
    """
    provider = get_tts_provider(settings)
    provider.check_credentials()

    outline_path = paths.outline(world, canon, series, story)
    if not outline_path.exists():
        raise FileNotFoundError(f"Outline.yaml not found: {outline_path}")

    outline_data = yaml.safe_load(outline_path.read_text(encoding="utf-8")) or {}
    chapters = outline_data.get("chapters", [])
    title = outline_data.get("title", story.replace("_", " ").title())

    if not chapters:
        raise ValueError("No chapters found in Outline.yaml")

    export_dir = paths.story_export(world, canon, series, story)
    audio_dir = export_dir / "audiobook"
    audio_dir.mkdir(parents=True, exist_ok=True)

    chapter_mp3s: list[tuple[int, str, Path]] = []

    for chapter in chapters:
        ch_num = chapter.get("chapter", 0)
        ch_title = chapter.get("title", f"Chapter {ch_num}")

        # Collect drafted beat prose for this chapter
        prose_parts: list[str] = []
        for beat in chapter.get("beats", []):
            beat_id = beat.get("beat_id")
            if not beat_id:
                continue
            draft_path = paths.beat_draft(world, canon, series, story, beat_id)
            if draft_path.exists():
                prose = draft_path.read_text(encoding="utf-8", errors="replace").strip()
                if prose:
                    prose_parts.append(prose)

        if not prose_parts:
            if on_progress:
                on_progress(f"  Skipping chapter {ch_num} (no drafted beats)")
            continue

        chapter_text = f"{ch_title}.\n\n" + "\n\n".join(prose_parts)
        if on_progress:
            on_progress(f"Synthesizing chapter {ch_num}: {ch_title}…")

        chunk_dir = audio_dir / f"ch{ch_num:03d}_chunks"
        try:
            mp3_path = await synthesize_chapter(
                ch_num, ch_title, chapter_text, chunk_dir, settings, on_progress,
                provider=provider,
            )
            chapter_mp3s.append((ch_num, ch_title, mp3_path))
        except Exception as exc:
            if on_progress:
                on_progress(f"  Warning: chapter {ch_num} failed: {exc}")

    if not chapter_mp3s:
        raise ValueError(
            "No chapters were synthesized. "
            "Make sure the story has drafted beats before exporting audiobook."
        )

    if on_progress:
        on_progress("Assembling final audiobook file…")

    if _ffmpeg_available() and _ffprobe_available():
        m4b_path = export_dir / f"{story}_audiobook.m4b"
        try:
            _build_m4b(chapter_mp3s, m4b_path, title)
            if on_progress:
                on_progress("Done — M4B audiobook ready.")
            return m4b_path
        except Exception as exc:
            if on_progress:
                on_progress(f"M4B assembly failed ({exc}), falling back to ZIP…")

    zip_path = export_dir / f"{story}_audiobook.zip"
    _build_zip(chapter_mp3s, zip_path)
    if on_progress:
        on_progress("Done — ZIP of chapter MP3s ready.")
    return zip_path
