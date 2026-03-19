"""Lulu print-on-demand bundle assembly for Quillan stories."""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger("quillan.structure.lulu")

if TYPE_CHECKING:
    from quillan.paths import Paths

# ── Constants ──────────────────────────────────────────────────────────────────

BLEED = 0.125               # inches, bleed margin on all four edges
DPI = 300
SPINE_PER_PAGE_BW = 0.002252     # inches/page, black-and-white interior
SPINE_PER_PAGE_COLOR = 0.002347  # inches/page, color interior
MIN_SPINE_WIDTH = 0.25      # minimum printable spine (inches)
WORDS_PER_PAGE = 250        # estimate for page count from word count

PAGE_SIZE_PRESETS: dict[str, tuple[float, float]] = {
    "6x9": (6.0, 9.0),
    "5x8": (5.0, 8.0),
    "8.5x11": (8.5, 11.0),
}

# Font search paths (Linux / Ubuntu)
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
    "/usr/share/fonts/truetype/noto/NotoSerif-Regular.ttf",
]


# ── Helper functions ───────────────────────────────────────────────────────────

def spine_width_inches(page_count: int, color: bool = False) -> float:
    """Return Lulu spine width in inches based on page count."""
    per_page = SPINE_PER_PAGE_COLOR if color else SPINE_PER_PAGE_BW
    return max(MIN_SPINE_WIDTH, page_count * per_page)


def estimate_page_count(beats_dir: Path) -> int:
    """Estimate page count by summing words in all Beat_Draft.md files."""
    total = 0
    if beats_dir.exists():
        for bid_dir in beats_dir.iterdir():
            draft = bid_dir / "Beat_Draft.md"
            if draft.exists():
                total += len(draft.read_text(encoding="utf-8", errors="replace").split())
    return max(1, round(total / WORDS_PER_PAGE))


def _load_font(size: int):
    """Try to load a truetype font; fall back to PIL default.

    Raises ImportError if Pillow is not installed.
    """
    from PIL import ImageFont  # ImportError propagates intentionally if Pillow absent
    try:
        for path in _FONT_CANDIDATES:
            if Path(path).exists():
                return ImageFont.truetype(path, size)
    except Exception as exc:
        logger.warning("Could not load TrueType font, using PIL default: %s", exc)
    return ImageFont.load_default()


def _draw_centered_text(draw, text: str, x_center: float, y: float, font, fill=(255, 255, 255)) -> None:
    """Draw text horizontally centered at x_center."""
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
    except AttributeError:
        text_w = len(text) * 8  # rough fallback
    draw.text((x_center - text_w / 2, y), text, font=font, fill=fill)


def _build_cover_pdf(
    cover_pdf_path: Path,
    cover_image_path: Path | None,
    page_w: float,
    page_h: float,
    spine_w: float,
    title: str,
    author: str,
    blurb: str,
) -> None:
    """Build a full-spread cover PDF using Pillow.

    Layout (left to right):
        BLEED | back cover | spine | front cover | BLEED

    Raises ImportError if Pillow is not installed.
    """
    from PIL import Image, ImageDraw, ImageOps  # type: ignore[import-untyped]

    px = DPI  # pixels per inch

    total_w = round((BLEED + page_w + spine_w + page_w + BLEED) * px)
    total_h = round((BLEED + page_h + BLEED) * px)

    # x-pixel offsets for each zone
    x_back  = round(BLEED * px)
    x_spine = round((BLEED + page_w) * px)
    x_front = round((BLEED + page_w + spine_w) * px)

    back_w   = round(page_w * px)
    spine_px = round(spine_w * px)
    front_w  = round(page_w * px)
    panel_h  = round(page_h * px)
    y_panel  = round(BLEED * px)

    # Dark background
    img = Image.new("RGB", (total_w, total_h), color=(20, 20, 30))
    draw = ImageDraw.Draw(img)

    # ── Back cover ────────────────────────────────────────────────────────
    back_region = (x_back, y_panel, x_back + back_w, y_panel + panel_h)
    draw.rectangle(back_region, fill=(25, 25, 40))

    # Blurb text
    if blurb:
        font_blurb = _load_font(28)
        # Wrap blurb to ~40 chars per line
        words = blurb.split()
        lines: list[str] = []
        current = ""
        for word in words:
            if len(current) + len(word) + 1 > 40:
                if current:
                    lines.append(current)
                current = word
            else:
                current = (current + " " + word).strip()
        if current:
            lines.append(current)
        blurb_y = y_panel + int(panel_h * 0.15)
        blurb_x_center = x_back + back_w // 2
        for line in lines[:12]:  # max 12 lines
            _draw_centered_text(draw, line, blurb_x_center, blurb_y, font_blurb)
            blurb_y += 38

    # Barcode placeholder (white rectangle, lower-right of back)
    bc_w, bc_h = 180, 120
    bc_x = x_back + back_w - bc_w - 30
    bc_y = y_panel + panel_h - bc_h - 30
    draw.rectangle((bc_x, bc_y, bc_x + bc_w, bc_y + bc_h), fill=(255, 255, 255))

    # ── Spine ─────────────────────────────────────────────────────────────
    spine_region = (x_spine, y_panel, x_spine + spine_px, y_panel + panel_h)
    draw.rectangle(spine_region, fill=(35, 35, 55))

    if spine_px >= 36:  # only if wide enough to draw text
        # Build a temporary image for the spine text (rotated 90°)
        spine_img = Image.new("RGBA", (panel_h, spine_px), (0, 0, 0, 0))
        spine_draw = ImageDraw.Draw(spine_img)

        font_spine_title = _load_font(max(20, spine_px - 10))
        font_spine_author = _load_font(max(14, spine_px - 20))

        y_title = spine_px // 2 - 20
        _draw_centered_text(spine_draw, title, panel_h // 2, y_title, font_spine_title)
        if author:
            _draw_centered_text(spine_draw, author, panel_h // 2, y_title + spine_px, font_spine_author)

        spine_rotated = spine_img.rotate(90, expand=True)
        img.paste(spine_rotated, (x_spine, y_panel), spine_rotated)

    # ── Front cover ───────────────────────────────────────────────────────
    front_region = (x_front, y_panel, x_front + front_w, y_panel + panel_h)

    if cover_image_path and cover_image_path.exists():
        try:
            cover_img = Image.open(str(cover_image_path)).convert("RGB")
            cover_img = ImageOps.fit(cover_img, (front_w, panel_h), method=Image.Resampling.LANCZOS)  # type: ignore[attr-defined]
            img.paste(cover_img, (x_front, y_panel))
        except Exception as exc:
            logger.warning("Could not load cover image %s, using solid fill: %s", cover_image_path, exc)
            draw.rectangle(front_region, fill=(40, 40, 65))
    else:
        draw.rectangle(front_region, fill=(40, 40, 65))

    # Title overlay in lower third of front cover
    font_title = _load_font(52)
    title_y = y_panel + int(panel_h * 0.72)
    title_x_center = x_front + front_w // 2
    _draw_centered_text(draw, title, title_x_center, title_y, font_title)

    if author:
        font_author = _load_font(34)
        _draw_centered_text(draw, author, title_x_center, title_y + 70, font_author)

    # Save as PDF
    img.save(str(cover_pdf_path), "PDF", resolution=DPI, save_all=False)


# ── Main bundle function ───────────────────────────────────────────────────────

def build_lulu_bundle(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    *,
    page_size: str = "6x9",
    author: str = "",
    color: bool = False,
) -> Path:
    """Assemble interior PDF + cover PDF + README into a zip bundle.

    Returns path to <story>_lulu_bundle.zip.
    Raises FileNotFoundError if interior PDF is missing.
    Raises ImportError if Pillow is not installed.
    Raises ValueError if page_size is not recognized.
    """
    # Validate Pillow is available (triggers ImportError with hint early)
    try:
        import PIL  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "Pillow is required for Lulu bundle assembly. "
            "Install with: pip install quillan[cover]"
        ) from exc

    if page_size not in PAGE_SIZE_PRESETS:
        raise ValueError(
            f"Unknown page_size {page_size!r}. "
            f"Valid options: {sorted(PAGE_SIZE_PRESETS)}"
        )

    export_dir = paths.story_export(world, canon, series, story)
    export_dir.mkdir(parents=True, exist_ok=True)

    # Locate interior PDF
    interior_pdf = export_dir / f"{story}_print.pdf"
    if not interior_pdf.exists():
        raise FileNotFoundError(
            f"Interior PDF not found: {interior_pdf}\n"
            "Run 'export --format print-pdf' first."
        )

    page_w, page_h = PAGE_SIZE_PRESETS[page_size]

    # Estimate page count
    beats_dir = paths.story_beats(world, canon, series, story)
    page_count = estimate_page_count(beats_dir)
    spine_w = spine_width_inches(page_count, color=color)

    # Read story metadata for cover
    import yaml
    outline_path = paths.outline(world, canon, series, story)
    outline_data: dict = {}
    if outline_path.exists():
        try:
            outline_data = yaml.safe_load(outline_path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            logger.warning("Failed to parse Outline.yaml for lulu bundle %s: %s", story, exc)

    title = outline_data.get("title", story.replace("_", " ").title())

    # Read blurb from creative brief
    blurb = ""
    brief_path = paths.creative_brief(world, canon, series, story)
    if brief_path.exists():
        try:
            brief_data = yaml.safe_load(brief_path.read_text(encoding="utf-8")) or {}
            blurb = str(brief_data.get("arc_intent", ""))
        except Exception as exc:
            logger.warning("Failed to parse creative brief for lulu bundle %s: %s", story, exc)

    # Cover image (optional)
    cover_image_path = paths.cover_image(world, canon, series, story)
    if not cover_image_path.exists():
        cover_image_path = None  # type: ignore[assignment]

    # Build cover PDF
    cover_pdf_path = export_dir / f"{story}_cover.pdf"
    _build_cover_pdf(
        cover_pdf_path,
        cover_image_path,
        page_w=page_w,
        page_h=page_h,
        spine_w=spine_w,
        title=title,
        author=author,
        blurb=blurb,
    )

    # Write README
    readme_path = export_dir / f"{story}_lulu_README.txt"
    readme_content = (
        f"Lulu Upload Instructions — {title}\n"
        f"{'=' * 60}\n\n"
        f"Book size:   {page_size} inches\n"
        f"Paper type:  {'Color' if color else 'Black & White'}\n"
        f"Page count:  ~{page_count} pages (estimated)\n"
        f"Spine width: {spine_w:.4f} inches\n\n"
        "Files in this bundle:\n"
        f"  {story}_interior.pdf  — interior manuscript\n"
        f"  {story}_cover.pdf     — full-spread cover (back + spine + front)\n"
        f"  {story}_lulu_README.txt  — this file\n\n"
        "Upload steps:\n"
        "  1. Log in to lulu.com and start a new project.\n"
        "  2. Select your book size (matches above).\n"
        "  3. Upload the interior PDF first.\n"
        "  4. Upload the cover PDF as a pre-made cover.\n"
        "  5. Review the proof — check spine text and bleed margins.\n"
        "  6. Order a proof copy before placing a full print run.\n\n"
        "Barcode note:\n"
        "  A white rectangle is reserved on the back cover for the ISBN\n"
        "  barcode. Lulu will place this automatically if you register an\n"
        "  ISBN, or you can add it manually in the cover design tool.\n"
    )
    readme_path.write_text(readme_content, encoding="utf-8")

    # Zip everything
    bundle_path = paths.lulu_bundle(world, canon, series, story)
    with zipfile.ZipFile(str(bundle_path), "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(str(interior_pdf), f"{story}_interior.pdf")
        zf.write(str(cover_pdf_path), f"{story}_cover.pdf")
        zf.write(str(readme_path), f"{story}_lulu_README.txt")

    return bundle_path
