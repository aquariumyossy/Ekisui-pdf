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


def span_rect(line: OcrLine, start: int, end: int) -> Rect:
    """文字矩形があればその和。無ければ行を等分した矩形。"""
    rects = line.char_rects
    if rects and len(rects) == len(line.text) and end > start:
        start = max(0, min(start, len(rects)))
        end = max(start, min(end, len(rects)))
        if end > start:
            acc = rects[start]
            for item in rects[start + 1 : end]:
                acc = union_rect(acc, item)
            return acc
    return slice_rect(line.rect, line.text, start, end)


def expand_char_boxes(rects: list[Rect], line: Rect) -> tuple[Rect, ...]:
    """認識モデルの列位置は字形より狭い。隣との中点まで広げ、境界は少し重ねる。"""
    if not rects:
        return ()
    line = line.normalized()
    vertical = line.height > line.width * 1.2 and len(rects) >= 2
    pad = max(1.5, (line.height if not vertical else line.width) * 0.08)
    if vertical:
        order = sorted(range(len(rects)), key=lambda index: rects[index].y0)
        bounds = [line.y0]
        for left, right in zip(order, order[1:]):
            bounds.append((rects[left].y1 + rects[right].y0) / 2)
        bounds.append(line.y1)
        built: list[Rect | None] = [None] * len(rects)
        for index, origin in enumerate(order):
            y0 = bounds[index] - (pad if index else 0.0)
            y1 = bounds[index + 1] + (pad if index + 1 < len(order) else 0.0)
            built[origin] = Rect(line.x0, y0, line.x1, y1).clamp(line)
        return tuple(item for item in built if item is not None)
    order = sorted(range(len(rects)), key=lambda index: rects[index].x0)
    bounds = [line.x0]
    for left, right in zip(order, order[1:]):
        bounds.append((rects[left].x1 + rects[right].x0) / 2)
    bounds.append(line.x1)
    built = [None] * len(rects)
    for index, origin in enumerate(order):
        x0 = bounds[index] - (pad if index else 0.0)
        x1 = bounds[index + 1] + (pad if index + 1 < len(order) else 0.0)
        built[origin] = Rect(x0, line.y0, x1, line.y1).clamp(line)
    return tuple(item for item in built if item is not None)


def char_indexes_in_rect(line: OcrLine, rect: Rect) -> list[int]:
    if not line.text or not line.rect.intersects(rect):
        return []
    found: list[int] = []
    for index in range(len(line.text)):
        cell = span_rect(line, index, index + 1)
        if cell.intersects(rect):
            found.append(index)
    return found
