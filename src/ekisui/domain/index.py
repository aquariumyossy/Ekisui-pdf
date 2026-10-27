from __future__ import annotations

import unicodedata

from ekisui.domain.normalize import ConfusableTable
from ekisui.domain.types import Document, Glyph, Page, PageIndex, Rect, TextLine


def build_document_index(doc: Document, table: ConfusableTable) -> tuple[PageIndex, ...]:
    return tuple(build_page_index(page, table) for page in doc.pages)


def build_page_index(page: Page, table: ConfusableTable) -> PageIndex:
    lines = tuple(sorted(page.lines, key=lambda line: (round(line.bbox.y0, 1), line.bbox.x0)))
    glyphs: list[Glyph] = []
    breaks = [0]
    previous: TextLine | None = None
    for line in lines:
        if previous is not None:
            gap = line.bbox.y0 - previous.bbox.y1
            if gap >= max(6.0, previous.bbox.height * 0.65):
                breaks.append(len(glyphs))
        glyphs.extend(_glyphs_for_line(line, table))
        previous = line
    breaks.append(len(glyphs))
    paragraphs = tuple(
        (breaks[i], breaks[i + 1])
        for i in range(len(breaks) - 1)
        if breaks[i + 1] > breaks[i]
    )
    return PageIndex(
        page_index=page.index,
        glyphs=tuple(glyphs),
        strict="".join(glyph.strict for glyph in glyphs),
        loose="".join(glyph.loose for glyph in glyphs),
        paragraphs=paragraphs,
        lines={line.id: line for line in page.lines},
    )


def _glyphs_for_line(line: TextLine, table: ConfusableTable) -> list[Glyph]:
    cells = _cells(line)
    glyphs: list[Glyph] = []
    for index, ch in enumerate(line.text):
        if ch.isspace():
            continue
        produced = [item for item in unicodedata.normalize("NFKC", ch) if not item.isspace()]
        if not produced:
            continue
        cell = cells[index]
        step = cell.width / len(produced)
        for offset, norm in enumerate(produced):
            glyphs.append(
                Glyph(
                    strict=norm,
                    loose=table.fold(norm),
                    page_index=line.page_index,
                    line_id=line.id,
                    bbox=Rect(cell.x0 + step * offset, cell.y0, cell.x0 + step * (offset + 1), cell.y1),
                    src_index=index,
                )
            )
    return glyphs


def _cells(line: TextLine) -> list[Rect]:
    if line.chars and len(line.chars) == len(line.text):
        return list(line.chars)
    weights = [_char_weight(ch) for ch in line.text] or [1.0]
    total = sum(weights) or 1.0
    cursor = line.bbox.x0
    cells: list[Rect] = []
    for weight in weights:
        width = line.bbox.width * weight / total
        cells.append(Rect(cursor, line.bbox.y0, cursor + width, line.bbox.y1))
        cursor += width
    return cells


def _char_weight(ch: str) -> float:
    if ch.isspace():
        return 0.35
    kind = unicodedata.east_asian_width(ch)
    if kind in {"W", "F"}:
        return 1.0
    if kind in {"Na", "H"}:
        return 0.5
    return 0.65


def surface_of(glyphs: tuple[Glyph, ...] | list[Glyph], lines: dict[str, TextLine]) -> str:
    parts: list[str] = []
    index = 0
    while index < len(glyphs):
        line_id = glyphs[index].line_id
        end = index + 1
        while end < len(glyphs) and glyphs[end].line_id == line_id:
            end += 1
        line = lines[line_id]
        start_at = min(glyph.src_index for glyph in glyphs[index:end])
        stop_at = max(glyph.src_index for glyph in glyphs[index:end])
        parts.append(line.text[start_at : stop_at + 1])
        index = end
    return "".join(parts)


def bbox_of(glyphs: tuple[Glyph, ...] | list[Glyph]) -> Rect:
    rect = glyphs[0].bbox
    for glyph in glyphs[1:]:
        rect = rect.union(glyph.bbox)
    return rect.pad(0.6, 0.4)


def line_ids_of(glyphs: tuple[Glyph, ...] | list[Glyph]) -> tuple[str, ...]:
    seen: list[str] = []
    for glyph in glyphs:
        if glyph.line_id not in seen:
            seen.append(glyph.line_id)
    return tuple(seen)
