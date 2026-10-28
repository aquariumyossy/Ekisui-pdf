"""Build the fictitious PDFs installed under samples/.

The scan is an image with no text layer, so OCR実行 has something to read.
Numbers and addresses are placeholders. example.com and example.jp are
documentation domains. Re-run this file to regenerate the PDFs.

    python tools/make_sample.py
"""

from __future__ import annotations

import io
import random
import re
import sys
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "samples"
SCAN_NAME = "架空契約_スキャン.pdf"
TEXT_NAME = "架空契約_テキスト.pdf"
FOOTER = "サンプル・架空のデータです"
DPI = 200
PAGE_W = 595.0
PAGE_H = 842.0
PIXEL_W = round(PAGE_W * DPI / 72)
PIXEL_H = round(PAGE_H * DPI / 72)
# Fixed clock so a second run writes the same PDF bytes.
_PDF_DATE = "D:20261028000000Z"

# Vertical gaps stay wider than a line wrap, so each fact is its own line.
PAGES: tuple[tuple[tuple[str, int, int], ...], ...] = (
    (
        ("業務委託契約書（架空）", 100, 58),
        ("この文書の人物と会社と番号は、すべて架空です。", 210, 36),
        ("甲　株式会社架空商事", 360, 46),
        ("代表者は山田太郎", 510, 46),
        ("住所は東京都千代田区架空町1丁目2番3号", 660, 46),
        ("電話03-5555-0000", 810, 46),
        ("メール taro.yamada@example.jp", 960, 46),
        ("乙　株式会社架空工業", 1140, 46),
        ("担当は佐藤花子", 1290, 46),
        ("住所は東京都千代田区架空町1-2-3", 1440, 46),
        ("郵便番号〒000-0000", 1590, 46),
    ),
    (
        ("株式会社架空銀行", 180, 64),
        ("口座番号5555555", 360, 48),
        ("hanako.kaku@example.com", 540, 46),
        ("電話090-5555-0001", 720, 48),
        ("大阪府架空市架空町1丁目4番5号", 900, 60),
        ("大阪府架空市架空町1-4-5", 1080, 56),
    ),
)


def build(directory: Path) -> None:
    font_path = _cjk_font()
    directory.mkdir(parents=True, exist_ok=True)
    images = [_render(font_path, lines, page_index) for page_index, lines in enumerate(PAGES)]
    _write_scan(directory / SCAN_NAME, images)
    _write_text(directory / TEXT_NAME)


def main() -> None:
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT
    build(dest)
    for path in (dest / SCAN_NAME, dest / TEXT_NAME):
        print(f"{path.name} {path.stat().st_size}")


def _cjk_font() -> str:
    candidates = (
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "C:/Windows/Fonts/YuGothM.ttc",
        "C:/Windows/Fonts/YuGothR.ttc",
        "C:/Windows/Fonts/meiryo.ttc",
        "C:/Windows/Fonts/msgothic.ttc",
        "C:/Windows/Fonts/msmincho.ttc",
    )
    for path in candidates:
        if Path(path).is_file():
            return path
    raise FileNotFoundError("日本語フォントが見つかりません")


def _render(font_path: str, lines: tuple[tuple[str, int, int], ...], page_index: int) -> Image.Image:
    image = Image.new("RGB", (PIXEL_W, PIXEL_H), "white")
    draw = ImageDraw.Draw(image)
    for text, top, size in lines:
        font = ImageFont.truetype(font_path, size)
        _draw_tracked(draw, (88, top), text, font, tracking=2)
    footer_font = ImageFont.truetype(font_path, 30)
    draw.text((88, PIXEL_H - 110), FOOTER, font=footer_font, fill=(30, 30, 30))
    return _scan_look(image, page_index)


def _draw_tracked(draw: ImageDraw.ImageDraw, origin: tuple[int, int], text: str, font: ImageFont.FreeTypeFont, tracking: int) -> None:
    x, y = origin
    for char in text:
        draw.text((x, y), char, font=font, fill=(15, 15, 15))
        box = font.getbbox(char)
        x += max(1, box[2] - box[0]) + tracking


def _scan_look(image: Image.Image, page_index: int) -> Image.Image:
    """A small fixed tilt and a few gray specks. The seed keeps the file stable."""
    tilted = image.rotate(0.35 if page_index == 0 else 0.2, resample=Image.Resampling.BICUBIC, fillcolor="white")
    rng = random.Random(20261028 + page_index)
    pixels = tilted.load()
    assert pixels is not None
    for _ in range(500):
        x = rng.randrange(PIXEL_W)
        y = rng.randrange(PIXEL_H)
        tone = rng.randint(170, 225)
        pixels[x, y] = (tone, tone, tone)
    return tilted


def _write_scan(path: Path, images: list[Image.Image]) -> None:
    doc = pymupdf.open()
    try:
        for image in images:
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=85, optimize=True)
            page = doc.new_page(width=PAGE_W, height=PAGE_H)
            page.insert_image(page.rect, stream=buffer.getvalue())
        _stamp_dates(doc)
        _save_stable(doc, path)
    finally:
        doc.close()


def _write_text(path: Path) -> None:
    doc = pymupdf.open()
    try:
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        y = 72
        page.insert_text((56, y), "業務委託契約書（架空）", fontname="japan", fontsize=16)
        y = 110
        for lines in PAGES:
            for text, _top, _size in lines:
                if text.startswith("業務委託契約書"):
                    continue
                page.insert_text((56, y), text, fontname="japan", fontsize=12)
                y += 28
            y += 16
        page.insert_text((56, 800), FOOTER, fontname="japan", fontsize=11)
        _stamp_dates(doc)
        _save_stable(doc, path)
    finally:
        doc.close()


def _save_stable(doc: pymupdf.Document, path: Path) -> None:
    buffer = io.BytesIO()
    doc.save(buffer, deflate=True, garbage=4)
    data = buffer.getvalue()
    ident = b"00112233445566778899AABBCCDDEEFF"
    pinned = b"/ID[<" + ident + b"><" + ident + b">]"
    # The trailer ID is the last one. Its spacing varies between saves.
    matches = list(re.finditer(rb"/ID\s*\[\s*<[0-9A-Fa-f \n\r]+>\s*<[0-9A-Fa-f \n\r]+>\s*\]", data))
    if not matches:
        tail = data[-240:]
        raise RuntimeError(f"PDF ID was not pinned: {tail!r}")
    match = matches[-1]
    path.write_bytes(data[: match.start()] + pinned + data[match.end() :])


def _stamp_dates(doc: pymupdf.Document) -> None:
    doc.set_metadata(
        {
            "format": "PDF 1.7",
            "title": "架空契約",
            "author": "",
            "subject": FOOTER,
            "keywords": "",
            "creator": "ekisui-pdf sample",
            "producer": "ekisui-pdf sample",
            "creationDate": _PDF_DATE,
            "modDate": _PDF_DATE,
        }
    )


if __name__ == "__main__":
    main()
