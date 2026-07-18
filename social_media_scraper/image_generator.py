"""Generate 小紅書 post PNG assets from social_media_triggers.json using Pillow."""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any
from urllib.request import urlretrieve

from PIL import Image, ImageDraw, ImageFont

_PKG_ROOT = Path(__file__).resolve().parent
JSON_PATH = _PKG_ROOT / "output" / "social_media_triggers.json"
OUTPUT_DIR = _PKG_ROOT / "output" / "images"
ASSETS_DIR = _PKG_ROOT / "assets"
FONT_PATH = ASSETS_DIR / "NotoSansCJKtc-Bold.otf"
FONT_URL = (
    "https://github.com/googlefonts/noto-cjk/raw/main/Sans/OTF/"
    "TraditionalChinese/NotoSansCJKtc-Bold.otf"
)

CANVAS_SIZE = (1080, 1080)
MARGIN = 90
BG_COLOR = "#F5F2EE"
PRIMARY = "#1A1A1A"
SECONDARY = "#666666"
ACCENT = "#C41E3A"
MUTED = "#999999"
DIVIDER_COLOR = "#1A1A1A"

CONTENT_TYPE_LABELS = {
    "job": "最新招聘",
    "exam": "考試資訊",
    "announcement": "最新公告",
}

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

_font_cache: dict[int, ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


def ensure_font() -> None:
    """Download Noto Sans CJK TC Bold if missing."""
    if FONT_PATH.is_file():
        return
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        logger.info("Downloading font to %s", FONT_PATH)
        urlretrieve(FONT_URL, FONT_PATH)
    except Exception as exc:
        logger.warning("Font download failed (%s); using PIL default font", exc)


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if size in _font_cache:
        return _font_cache[size]
    if FONT_PATH.is_file():
        try:
            font = ImageFont.truetype(str(FONT_PATH), size)
            _font_cache[size] = font
            return font
        except Exception as exc:
            logger.warning("Failed to load %s: %s", FONT_PATH, exc)
    font = ImageFont.load_default()
    _font_cache[size] = font
    return font


def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    if not text:
        return 0
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def draw_text_spaced(
    draw: ImageDraw.ImageDraw,
    text: str,
    x: int,
    y: int,
    font: ImageFont.ImageFont,
    fill: str,
    spacing: int = 6,
) -> None:
    cursor = x
    for char in text:
        draw.text((cursor, y), char, font=font, fill=fill)
        cursor += text_width(draw, char, font) + spacing


def draw_text_wrapped(
    draw: ImageDraw.ImageDraw,
    text: str,
    x: int,
    y: int,
    max_width: int,
    font: ImageFont.ImageFont,
    fill: str,
    line_height: float,
    max_lines: int | None = None,
) -> int:
    """Wrap text at max_width; return final y after all lines."""
    if not text:
        return y
    lines: list[str] = []
    current = ""
    for char in text:
        trial = current + char
        if text_width(draw, trial, font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = char
    if current:
        lines.append(current)
    if max_lines is not None:
        lines = lines[:max_lines]

    lh = int(font.size * line_height)
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += lh
    return y


def draw_text_right(
    draw: ImageDraw.ImageDraw,
    text: str,
    y: int,
    font: ImageFont.ImageFont,
    fill: str,
    right_x: int = CANVAS_SIZE[0] - MARGIN,
) -> None:
    w = text_width(draw, text, font)
    draw.text((right_x - w, y), text, font=font, fill=fill)


def draw_divider(draw: ImageDraw.ImageDraw, y: int, margin: int = MARGIN, width: int = 1080) -> None:
    x1, x2 = margin, width - margin
    draw.line([(x1, y), (x2, y)], fill=DIVIDER_COLOR, width=1)


def draw_divider_centered(draw: ImageDraw.ImageDraw, y: int, line_width: int = 600) -> None:
    cx = CANVAS_SIZE[0] // 2
    half = line_width // 2
    draw.line([(cx - half, y), (cx + half, y)], fill=DIVIDER_COLOR, width=1)


def new_canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", CANVAS_SIZE, BG_COLOR)
    return img, ImageDraw.Draw(img)


def parse_summary_fields(summary: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for key, pattern in (
        ("department", r"部門:\s*([^;]+)"),
        ("salary", r"薪酬:\s*([^;]+)"),
        ("closing_date", r"截止:\s*([^;]+)"),
    ):
        match = re.search(pattern, summary)
        if match:
            fields[key] = match.group(1).strip()
    return fields


def format_closing_display(closing: str) -> tuple[str, str]:
    """Return (display_text, color) for closing date."""
    raw = (closing or "").strip()
    if raw in ("", "全年接受申請"):
        return "全年接受申請", SECONDARY
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if match:
        y, m, d = match.groups()
        return f"{y}年{int(m)}月{int(d)}日", ACCENT
    return raw, ACCENT


def format_closing_cover(closing: str) -> tuple[str, str]:
    text, color = format_closing_display(closing)
    if color == ACCENT:
        return f"截止 {text}", ACCENT
    return text, color


def content_type_label(item: dict[str, Any] | None) -> str:
    if not item:
        return "最新招聘"
    ctype = str(item.get("content_type") or "job")
    return CONTENT_TYPE_LABELS.get(ctype, "最新招聘")


def pick_cover_item(triggers: dict[str, Any]) -> dict[str, Any] | None:
    urgent = triggers.get("urgent_items") or []
    jobs = triggers.get("job_openings") or []
    if urgent:
        return urgent[0]
    if jobs:
        return jobs[0]
    return None


def truncate(text: str, max_len: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def load_triggers() -> dict[str, Any]:
    if not JSON_PATH.is_file():
        raise FileNotFoundError(f"Missing triggers file: {JSON_PATH}")
    with JSON_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def generate_cover(triggers: dict[str, Any]) -> None:
    item = pick_cover_item(triggers)
    if not item:
        raise ValueError("No cover item available")

    jobs = triggers.get("job_openings") or []
    label_item = jobs[0] if jobs else item
    fields = parse_summary_fields(str(item.get("summary", "")))
    closing_raw = fields.get("closing_date", "")
    closing_text, closing_color = format_closing_cover(closing_raw)

    img, draw = new_canvas()
    max_w = CANVAS_SIZE[0] - 2 * MARGIN

    draw_text_spaced(draw, "ACEGOVHK", MARGIN, 90, load_font(24), MUTED, spacing=8)

    draw.text((MARGIN, 160), content_type_label(label_item), font=load_font(28), fill=ACCENT)
    draw_divider(draw, 210)

    title = str(item.get("title") or "")
    draw_text_wrapped(
        draw, title, MARGIN, 240, max_w, load_font(72), PRIMARY, 1.6, max_lines=2
    )

    draw.text((MARGIN, 420), closing_text, font=load_font(40), fill=closing_color)
    draw_text_right(draw, "香港公務員備考｜同路人", 900, load_font(24), MUTED)

    img.save(OUTPUT_DIR / "cover.png")


def draw_job_slide(
    draw: ImageDraw.ImageDraw,
    section_label: str,
    item: dict[str, Any],
    title_size: int = 64,
) -> None:
    max_w = CANVAS_SIZE[0] - 2 * MARGIN
    fields = parse_summary_fields(str(item.get("summary", "")))
    department = fields.get("department", "—")
    salary = fields.get("salary", "—")
    closing_raw = fields.get("closing_date", "")
    closing_display, closing_color = format_closing_display(closing_raw)

    draw.text((MARGIN, 90), section_label, font=load_font(28), fill=ACCENT)
    draw_text_wrapped(
        draw,
        str(item.get("title") or ""),
        MARGIN,
        150,
        max_w,
        load_font(title_size),
        PRIMARY,
        1.6,
        max_lines=2,
    )
    draw_divider(draw, 310)

    row_y = 340
    row_lh = 52
    font_body = load_font(36)

    rows = [
        ("部門　　", department, PRIMARY),
        ("月薪　　", salary, PRIMARY),
        ("截止　　", closing_display, closing_color),
    ]
    for label, value, color in rows:
        draw.text((MARGIN, row_y), label + value, font=font_body, fill=color)
        row_y += row_lh

    draw_text_right(draw, "AceGovHK", 900, load_font(24), MUTED)


def generate_slide_1(triggers: dict[str, Any]) -> None:
    jobs = triggers.get("job_openings") or []
    if not jobs:
        raise ValueError("No job_openings for slide_1")
    img, draw = new_canvas()
    draw_job_slide(draw, "職位資訊", jobs[0])
    img.save(OUTPUT_DIR / "slide_1.png")


def generate_slide_2(triggers: dict[str, Any]) -> None:
    exams = triggers.get("exam_updates") or []
    jobs = triggers.get("job_openings") or []

    img, draw = new_canvas()

    if exams:
        item = exams[0]
        max_w = CANVAS_SIZE[0] - 2 * MARGIN
        summary = truncate(str(item.get("summary") or ""), 60)
        published = str(item.get("published_date") or "").strip() or "—"

        draw.text((MARGIN, 90), "考試資訊", font=load_font(28), fill=ACCENT)
        draw_text_wrapped(
            draw,
            str(item.get("title") or ""),
            MARGIN,
            150,
            max_w,
            load_font(64),
            PRIMARY,
            1.6,
            max_lines=2,
        )
        draw_divider(draw, 310)

        row_y = 340
        row_lh = 52
        font_body = load_font(36)
        for label, value, color in (
            ("摘要　　", summary, PRIMARY),
            ("日期　　", published, PRIMARY),
            ("來源　　", str(item.get("source_name") or "—"), PRIMARY),
        ):
            draw.text((MARGIN, row_y), label + value, font=font_body, fill=color)
            row_y += row_lh
        draw_text_right(draw, "AceGovHK", 900, load_font(24), MUTED)
    elif len(jobs) >= 2:
        draw_job_slide(draw, "職位資訊", jobs[1])
    else:
        raise ValueError("No exam_updates or second job for slide_2")

    img.save(OUTPUT_DIR / "slide_2.png")


def generate_slide_3() -> None:
    img, draw = new_canvas()
    cx = CANVAS_SIZE[0] // 2
    max_w = 900

    title_font = load_font(52)
    subtitle_font = load_font(38)
    footer_font = load_font(24)

    title = "想了解更多備考攻略？"
    title_lines: list[str] = []
    current = ""
    for char in title:
        trial = current + char
        if text_width(draw, trial, title_font) <= max_w:
            current = trial
        else:
            if current:
                title_lines.append(current)
            current = char
    if current:
        title_lines.append(current)

    line_h = int(title_font.size * 1.6)
    block_h = len(title_lines) * line_h
    subtitle_h = int(subtitle_font.size * 1.6)
    block_total = block_h + 60 + 1 + 40 + subtitle_h
    start_y = (CANVAS_SIZE[1] - block_total) // 2

    y = start_y
    for line in title_lines:
        w = text_width(draw, line, title_font)
        draw.text((cx - w // 2, y), line, font=title_font, fill=PRIMARY)
        y += line_h

    divider_y = y + 60
    draw_divider_centered(draw, divider_y, 600)

    sub = "留言「攻略」即獲免費備考資料"
    y = divider_y + 40
    w = text_width(draw, sub, subtitle_font)
    draw.text((cx - w // 2, y), sub, font=subtitle_font, fill=SECONDARY)

    footer = "AceGovHK｜香港公務員備考同路人"
    w = text_width(draw, footer, footer_font)
    draw.text((cx - w // 2, 900), footer, font=footer_font, fill=MUTED)

    img.save(OUTPUT_DIR / "slide_3.png")


def run_generators(triggers: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    generators = [
        ("cover", lambda: generate_cover(triggers["triggers"])),
        ("slide_1", lambda: generate_slide_1(triggers["triggers"])),
        ("slide_2", lambda: generate_slide_2(triggers["triggers"])),
        ("slide_3", lambda: generate_slide_3()),
    ]
    for name, fn in generators:
        try:
            fn()
            logger.info("Generated %s.png", name)
        except Exception as exc:
            logger.warning("Skipped %s: %s", name, exc)


def main() -> None:
    try:
        ensure_font()
        data = load_triggers()
        triggers = data.get("triggers")
        if not isinstance(triggers, dict):
            raise ValueError("Invalid JSON: missing or invalid 'triggers' object")
        run_generators(data)
        logger.info("Image generation complete -> %s", OUTPUT_DIR)
    except Exception as exc:
        logger.error("Image generation failed: %s", exc)
        sys.exit(0)


if __name__ == "__main__":
    main()
