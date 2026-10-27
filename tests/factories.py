from __future__ import annotations

from pathlib import Path

import pymupdf

from ekisui_pdf.core.models import OcrLine, Rect


def scanned_pdf(path: Path, pages: list[list[str]], color: tuple[float, float, float] = (0.75, 0.05, 0.05)) -> list[OcrLine]:
    """文字を画像にしたPDFと、描画前の座標から作った行を返す。"""
    text_doc = pymupdf.open()
    pixmaps: list[pymupdf.Pixmap] = []
    lines: list[OcrLine] = []
    try:
        for page_index, page_lines in enumerate(pages):
            page = text_doc.new_page(width=595, height=842)
            y = 110.0
            for text in page_lines:
                page.insert_text(
                    (72, y),
                    text,
                    fontname="japan",
                    fontsize=16,
                    color=color,
                )
                y += 36
            pixmaps.append(page.get_pixmap(dpi=144, alpha=False))
            lines.extend(_lines_from_text_page(page, page_index))
        image_doc = pymupdf.open()
        try:
            for pixmap in pixmaps:
                page = image_doc.new_page(width=595, height=842)
                page.insert_image(page.rect, pixmap=pixmap)
            image_doc.save(path)
        finally:
            image_doc.close()
    finally:
        text_doc.close()
    return lines


def _lines_from_text_page(page: pymupdf.Page, page_index: int) -> list[OcrLine]:
    lines: list[OcrLine] = []
    raw = page.get_text("rawdict")
    line_index = 0
    for block in raw["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            chars = [char for span in line["spans"] for char in span.get("chars") or []]
            text = "".join(char["c"] for char in chars) or "".join(span["text"] for span in line["spans"])
            x0, y0, x1, y1 = line["bbox"]
            char_rects = ()
            if chars and "".join(char["c"] for char in chars) == text:
                char_rects = tuple(Rect(*char["bbox"]) for char in chars)
            lines.append(
                OcrLine(
                    page_index=page_index,
                    text=text,
                    rect=Rect(x0, y0, x1, y1),
                    confidence=1.0,
                    line_id=f"p{page_index}-l{line_index}",
                    char_rects=char_rects,
                )
            )
            line_index += 1
    return lines
