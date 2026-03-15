"""System readiness checks, shared between CLI and web layer."""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DoctorItem:
    status: str   # "ok" | "warn" | "fail"
    category: str
    message: str


@dataclass
class DoctorResult:
    items: list[DoctorItem] = field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return sum(1 for i in self.items if i.status == "ok")

    @property
    def warn_count(self) -> int:
        return sum(1 for i in self.items if i.status == "warn")

    @property
    def fail_count(self) -> int:
        return sum(1 for i in self.items if i.status == "fail")

    @property
    def passed(self) -> bool:
        return self.fail_count == 0


def run_doctor_checks(data_dir: Path | None = None) -> DoctorResult:
    """Run all system readiness checks and return a structured result."""
    from quillan.config import Settings

    result = DoctorResult()

    def _ok(cat: str, msg: str) -> None:
        result.items.append(DoctorItem("ok", cat, msg))

    def _warn(cat: str, msg: str) -> None:
        result.items.append(DoctorItem("warn", cat, msg))

    def _fail(cat: str, msg: str) -> None:
        result.items.append(DoctorItem("fail", cat, msg))

    # ── Python version ────────────────────────────────────────────────────
    vi = sys.version_info
    if vi >= (3, 10):
        _ok("python", f"Python {vi.major}.{vi.minor}.{vi.micro} (≥ 3.10 required)")
    else:
        _fail("python", f"Python {vi.major}.{vi.minor}.{vi.micro} — 3.10+ required")

    # ── Required packages ─────────────────────────────────────────────────
    for pkg in ("litellm", "pydantic", "yaml", "click"):
        try:
            __import__(pkg)
            _ok("packages", pkg)
        except ImportError:
            _fail("packages", f"{pkg} — not installed")

    # ── Optional packages ─────────────────────────────────────────────────
    optional = {
        "textual": "TUI support",
        "fastapi": "web server",
        "tiktoken": "accurate token counting",
        "docx": "DOCX import/export (python-docx)",
    }
    for pkg, desc in optional.items():
        try:
            __import__(pkg)
            _ok("optional", f"{pkg} ({desc})")
        except ImportError:
            _warn("optional", f"{pkg} not installed — {desc} unavailable")

    # ── External tools ────────────────────────────────────────────────────
    tools = {
        "pandoc": "Markdown/EPUB/DOCX/PDF export",
        "ebook-convert": "MOBI/AZW3 export (Calibre)",
        "ffmpeg": "audiobook encoding",
    }
    for tool, desc in tools.items():
        if shutil.which(tool):
            _ok("tools", f"{tool} ({desc})")
        else:
            _warn("tools", f"{tool} not found — {desc} unavailable")

    # ── API keys ──────────────────────────────────────────────────────────
    settings = Settings(data_dir=data_dir) if data_dir else Settings()

    key_checks = [
        ("openai_api_key", "OpenAI"),
        ("xai_api_key", "xAI (Grok)"),
        ("gemini_api_key", "Google Gemini"),
        ("anthropic_api_key", "Anthropic Claude"),
        ("elevenlabs_api_key", "ElevenLabs TTS"),
    ]
    any_cloud_key = False
    for attr, label in key_checks:
        val = getattr(settings, attr, "")
        if val:
            _ok("api_keys", f"{label} key present")
            any_cloud_key = True
        else:
            _warn("api_keys", f"{label} key not set")

    local_bases = [
        ("planning_api_base", "planning"),
        ("draft_api_base", "draft"),
        ("forensic_api_base", "forensic"),
        ("struct_api_base", "struct"),
    ]
    any_local = False
    for attr, stage in local_bases:
        val = getattr(settings, attr, "")
        if val:
            any_local = True
            try:
                import urllib.request
                req = urllib.request.Request(val, method="HEAD")
                urllib.request.urlopen(req, timeout=2)
                _ok("api_keys", f"Local LLM ({stage}) reachable at {val}")
            except Exception:
                _warn("api_keys", f"Local LLM ({stage}) set to {val} but not reachable")

    if not any_cloud_key and not any_local:
        _fail("api_keys", "No API keys and no local LLM base URLs — LLM calls will fail")

    # ── Data directory ────────────────────────────────────────────────────
    effective_dir = data_dir or settings.data_dir
    try:
        effective_dir.mkdir(parents=True, exist_ok=True)
        test_file = effective_dir / ".doctor_write_test"
        test_file.write_text("ok")
        test_file.unlink()
        _ok("data_dir", f"{effective_dir} is writable")
    except Exception as exc:
        _fail("data_dir", f"{effective_dir} not writable: {exc}")

    # ── Disk space ────────────────────────────────────────────────────────
    try:
        usage = shutil.disk_usage(effective_dir)
        free_gb = usage.free / (1024 ** 3)
        if free_gb >= 1.0:
            _ok("disk", f"{free_gb:.1f} GB free")
        else:
            _warn("disk", f"Only {free_gb:.2f} GB free — less than 1 GB may cause issues")
    except Exception as exc:
        _warn("disk", f"Could not check disk space: {exc}")

    return result
