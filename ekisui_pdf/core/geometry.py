from __future__ import annotations

from ekisui_pdf.core.models import OcrLine, Rect


def union_rect(first: Rect, second: Rect) -> Rect:
    left = first.normalized()
    right = second.normalized()
    return Rect(
        min(left.x0, right.x0),
        min(left.y0, right.y0),
        max(left.x1, right.x1),
        max(left.y1, right.y1),
    )


def slice_rect(rect: Rect, text: str, start: int, end: int) -> Rect:
    """行矩形を文字位置で切る。横書きが基本で、縦長の行だけ縦に切る。"""
    rect = rect.normalized()
    count = max(len(text), 1)
    start = max(0, min(start, count))
    end = max(start, min(end, count))
    if end == start:
        return rect
    vertical = rect.height > rect.width * 1.2 and count >= 2
    if vertical:
        y0 = rect.y0 + rect.height * (start / count)
        y1 = rect.y0 + rect.height * (end / count)
        return Rect(rect.x0, y0, rect.x1, y1)
    x0 = rect.x0 + rect.width * (start / count)
    x1 = rect.x0 + rect.width * (end / count)
    return Rect(x0, rect.y0, x1, rect.y1)


def char_indexes_in_rect(line: OcrLine, rect: Rect) -> list[int]:
    if not line.text or not line.rect.intersects(rect):
        return []
    found: list[int] = []
    for index in range(len(line.text)):
        cell = slice_rect(line.rect, line.text, index, index + 1)
        if cell.intersects(rect):
            found.append(index)
    return found
