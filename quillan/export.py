"""Manuscript assembly: Markdown / EPUB / DOCX / PDF / print-PDF / Lulu."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from quillan.validate import extract_beat_ids as _extract_beat_ids_ordered

if TYPE_CHECKING:
    from quillan.config import Settings
    from quillan.paths import Paths

SUPPORTED_FORMATS = ("markdown", "epub", "docx", "pdf", "print-pdf", "lulu", "mobi", "azw3")

# Path to the bundled LaTeX template
_TEMPLATE_PATH = Path(__file__).parent / "templates" / "print_interior.tex"


class ExportResult:
    """Wraps the output path and records whether the requested format was produced."""

    def __init__(self, path: Path, fmt: str, requested_fmt: str) -> None:
        self.path = path
        self.fmt = fmt                        # format actually produced
        self.requested_fmt = requested_fmt    # format originally requested
        self.degraded = fmt != requested_fmt  # True when format fell back

    def __str__(self) -> str:
        return str(self.path)

    def __fspath__(self) -> str:
        return str(self.path)

    def __getattr__(self, name: str):
        # Proxy unknown attributes to self.path so ExportResult behaves like a Path.
        return getattr(self.path, name)


def export_story(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    fmt: str = "markdown",
    settings: "Settings | None" = None,
    cover_path: Path | None = None,
) -> "ExportResult":
    """Assemble manuscript from beats.

    Reads Outline.yaml for beat order (never filesystem order).
    Assembles YAML front matter + beat prose.

    fmt: markdown (native) | epub | docx | pdf | print-pdf | lulu (via pandoc / Pillow).
    Degrades gracefully: epub/docx/pdf/print-pdf → markdown if pandoc missing.
    Returns an ExportResult; check ``.degraded`` to see if the format fell back.

    cover_path: optional path to a cover image (PNG/JPEG); used for epub and lulu.
    """
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported export format: {fmt!r}. Choose from {SUPPORTED_FORMATS}")

    export_dir = paths.story_export(world, canon, series, story)
    export_dir.mkdir(parents=True, exist_ok=True)

    # ── Validate Outline.yaml exists and is parseable ─────────────────────
    outline_path = paths.outline(world, canon, series, story)
    if not outline_path.exists():
        raise FileNotFoundError(f"Outline.yaml not found: {outline_path}")

    outline_text = outline_path.read_text(encoding="utf-8")
    outline_data = yaml.safe_load(outline_text) or {}

    # Validate expected keys
    chapters = outline_data.get("chapters")
    if chapters is None:
        raise ValueError(f"Outline.yaml missing 'chapters' key: {outline_path}")

    # ── Assemble beat prose in outline order ──────────────────────────────
    beat_ids = _extract_beat_ids_ordered(outline_data)
    if not beat_ids:
        raise ValueError(f"Outline.yaml has no beats: {outline_path}")

    title = outline_data.get("title", story.replace("_", " ").title())
    genre = outline_data.get("genre", "")
    theme = outline_data.get("theme", "")

    # Build YAML front matter
    front_matter_data: dict = {"title": title}
    if genre:
        front_matter_data["genre"] = genre
    if theme:
        front_matter_data["theme"] = theme

    front_matter = "---\n" + yaml.dump(front_matter_data, default_flow_style=False) + "---\n\n"

    # Collect prose sections
    chapter_sections: dict[int, list[str]] = {}
    chapter_titles: dict[int, str] = {}

    for chapter in chapters:
        ch_num = chapter.get("chapter", 0)
        ch_title = chapter.get("title", f"Chapter {ch_num}")
        chapter_titles[ch_num] = ch_title
        chapter_sections[ch_num] = []

        for beat in chapter.get("beats", []):
            beat_id = beat.get("beat_id")
            if not beat_id:
                continue

            draft_path = paths.beat_draft(world, canon, series, story, beat_id)
            if draft_path.exists():
                prose = draft_path.read_text(encoding="utf-8", errors="replace").strip()
                chapter_sections[ch_num].append(prose)

    # Assemble full document
    doc_parts = [front_matter]
    doc_parts.append(f"# {title}\n\n")

    for ch_num in sorted(chapter_sections.keys()):
        ch_title = chapter_titles.get(ch_num, f"Chapter {ch_num}")
        doc_parts.append(f"## {ch_title}\n\n")
        for prose in chapter_sections[ch_num]:
            if prose:
                doc_parts.append(prose + "\n\n")

    manuscript = "".join(doc_parts)

    # ── Write markdown output ─────────────────────────────────────────────
    md_path = export_dir / f"{story}.md"
    from quillan.io import atomic_write
    atomic_write(md_path, manuscript)

    if fmt == "markdown":
        return ExportResult(md_path, "markdown", fmt)

    # ── Kindle formats via calibre ────────────────────────────────────────
    if fmt in ("mobi", "azw3"):
        epub_path = export_dir / f"{story}.epub"
        # Ensure epub exists first
        if not epub_path.exists():
            if _pandoc_available():
                try:
                    _run_pandoc(md_path, epub_path, "epub", title, cover_path=cover_path)
                except subprocess.CalledProcessError:
                    return ExportResult(md_path, "markdown", fmt)
            else:
                return ExportResult(md_path, "markdown", fmt)
        if _calibre_available():
            out_path = export_dir / f"{story}.{fmt}"
            try:
                _run_calibre(epub_path, out_path)
                return ExportResult(out_path, fmt, fmt)
            except subprocess.CalledProcessError:
                pass
        # Degradation: return epub
        return ExportResult(epub_path, "epub", fmt)

    # ── Lulu bundle (calls print-pdf internally) ──────────────────────────
    if fmt == "lulu":
        lulu_path = _export_lulu(
            paths, world, canon, series, story, md_path, title, export_dir,
            cover_path=cover_path, settings=settings,
        )
        return ExportResult(lulu_path, "lulu", fmt)

    # ── Convert via pandoc ────────────────────────────────────────────────
    if not _pandoc_available():
        # Graceful degradation
        return ExportResult(md_path, "markdown", fmt)

    if fmt == "print-pdf":
        out_path = export_dir / f"{story}_print.pdf"
    else:
        out_path = export_dir / f"{story}.{fmt}"

    try:
        _run_pandoc(md_path, out_path, fmt, title, cover_path=cover_path)
        return ExportResult(out_path, fmt, fmt)
    except subprocess.CalledProcessError:
        # Degradation: return markdown
        return ExportResult(md_path, "markdown", fmt)


def _export_lulu(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    md_path: Path,
    title: str,
    export_dir: Path,
    *,
    cover_path: Path | None = None,
    settings: "Settings | None" = None,
) -> Path:
    """Run print-pdf first (if needed), then build the Lulu bundle."""
    from quillan.structure.lulu import build_lulu_bundle

    # Ensure interior PDF exists
    interior_pdf = export_dir / f"{story}_print.pdf"
    if not interior_pdf.exists():
        if _pandoc_available():
            try:
                _run_pandoc(md_path, interior_pdf, "print-pdf", title, cover_path=None)
            except subprocess.CalledProcessError:
                raise FileNotFoundError(
                    "print-pdf export failed; run 'export --format print-pdf' manually."
                )
        else:
            raise FileNotFoundError(
                "Interior PDF not found and pandoc is unavailable. "
                "Install pandoc + xelatex, then run 'export --format print-pdf' first."
            )

    return build_lulu_bundle(paths, world, canon, series, story)


def _pandoc_available() -> bool:
    """Return True if pandoc is installed and executable."""
    try:
        result = subprocess.run(
            ["pandoc", "--version"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _run_pandoc(
    src: Path,
    dest: Path,
    fmt: str,
    title: str,
    *,
    cover_path: Path | None = None,
) -> None:
    """Run pandoc to convert src markdown to dest format."""
    args = [
        "pandoc",
        str(src),
        "-o", str(dest),
        "--standalone",
        f"--metadata=title:{title}",
    ]

    if fmt == "pdf":
        args += ["--pdf-engine=xelatex"]
    elif fmt == "print-pdf":
        args += [
            "--pdf-engine=xelatex",
            f"--template={_TEMPLATE_PATH}",
            "--variable=geometry:true",
        ]
    elif fmt == "epub":
        if cover_path is not None:
            args += [f"--epub-cover-image={cover_path}"]

    subprocess.run(args, check=True, capture_output=True, timeout=120)


def _calibre_available() -> bool:
    """Return True if calibre's ebook-convert is installed."""
    try:
        result = subprocess.run(
            ["ebook-convert", "--version"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _run_calibre(src: Path, dest: Path) -> None:
    """Convert src (epub) to dest (mobi/azw3) via calibre ebook-convert."""
    subprocess.run(
        ["ebook-convert", str(src), str(dest)],
        check=True, capture_output=True, timeout=120,
    )
