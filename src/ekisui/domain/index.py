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
        if previous is not None and _starts_new_block(previous, line):
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
        width=page.width,
        height=page.height,
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
    # Fullwidth space is east-asian width F. Weigh it before the narrow-space rule
    # so a following address does not slide left onto the previous character.
    kind = unicodedata.east_asian_width(ch)
    if kind in {"W", "F"}:
        return 1.0
    if ch.isspace():
        return 0.35
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


def parts_of(glyphs: tuple[Glyph, ...] | list[Glyph]) -> tuple[Rect, ...]:
    """Exact glyph bounds, one rectangle per line. No padding."""
    parts: list[Rect] = []
    index = 0
    while index < len(glyphs):
        line_id = glyphs[index].line_id
        end = index + 1
        while end < len(glyphs) and glyphs[end].line_id == line_id:
            end += 1
        rect = glyphs[index].bbox
        for glyph in glyphs[index + 1 : end]:
            rect = rect.union(glyph.bbox)
        parts.append(rect)
        index = end
    return tuple(parts)


def bbox_of(glyphs: tuple[Glyph, ...] | list[Glyph]) -> Rect:
    rect = glyphs[0].bbox
    for glyph in glyphs[1:]:
        rect = rect.union(glyph.bbox)
    return rect.pad(0.6, 0.4)


def line_runs(page: PageIndex) -> list[tuple[int, int]]:
    """Glyph ranges, one per line, in reading order."""
    runs: list[tuple[int, int]] = []
    cursor = 0
    glyphs = page.glyphs
    while cursor < len(glyphs):
        line_id = glyphs[cursor].line_id
        end = cursor + 1
        while end < len(glyphs) and glyphs[end].line_id == line_id:
            end += 1
        runs.append((cursor, end))
        cursor = end
    return runs


def _starts_new_block(previous: TextLine, line: TextLine) -> bool:
    """A new paragraph, or the other column of the same row.

    A scanned text layer is one glyph per cell. Those cells are far apart, but
    each piece is a single character of the same line. A column break needs a
    run of text on both sides.
    """
    gap = line.bbox.y0 - previous.bbox.y1
    vertical = gap >= max(6.0, previous.bbox.height * 0.65)
    if len(previous.text.strip()) < 2 or len(line.text.strip()) < 2:
        return vertical
    if abs(line.bbox.x0 - previous.bbox.x0) > max(48.0, previous.bbox.height * 2.5):
        return True
    overlap = min(previous.bbox.y1, line.bbox.y1) - max(previous.bbox.y0, line.bbox.y0)
    if overlap >= 0.4 * max(1.0, min(previous.bbox.height, line.bbox.height)):
        if line.bbox.x0 >= previous.bbox.x1 - 1:
            gutter = line.bbox.x0 - previous.bbox.x1
        elif previous.bbox.x0 >= line.bbox.x1 - 1:
            gutter = previous.bbox.x0 - line.bbox.x1
        else:
            gutter = 0.0
        if gutter > max(36.0, previous.bbox.height * 2):
            return True
    return vertical


def is_line_wrap(left: Rect, right: Rect) -> bool:
    """True when ``right`` is the next wrapped line, not a new paragraph or column."""
    gap = right.y0 - left.y1
    height = max(left.height, right.height, 1.0)
    # 22pt still covers a loosely leaded wrap. A blank line (the 24pt fixture) does not.
    if gap < -height * 0.35 or gap >= max(height * 1.25, 22.0):
        return False
    return abs(right.x0 - left.x0) <= max(72.0, height * 4)


def is_page_wrap(left: Rect, right: Rect) -> bool:
    """The first line of the next page continues the last line when the margins match."""
    height = max(left.height, right.height, 1.0)
    return abs(right.x0 - left.x0) <= max(72.0, height * 4)


def _body_runs(page: PageIndex) -> list[tuple[int, int]]:
    """Line runs that are not a header, footer, or page number."""
    runs = []
    for start, stop in line_runs(page):
        glyphs = page.glyphs[start:stop]
        if glyphs and not _furniture(page, glyphs):
            runs.append((start, stop))
    return runs or line_runs(page)


def _furniture(page: PageIndex, glyphs: tuple[Glyph, ...] | list[Glyph]) -> bool:
    """A page number or a short running header. A wrapped tail in the body is kept."""
    text = "".join(glyph.strict for glyph in glyphs)
    if not text:
        return False
    box = page.lines[glyphs[0].line_id].bbox
    in_margin = page.height > 0 and (box.y0 < 56 or box.y0 > page.height - 72)
    digits = len(text) <= 8 and all(ch.isdigit() or ch in "-－–—‐−" for ch in text)
    if digits:
        return in_margin
    if not in_margin or len(text) > 24 or text[:1] in "ーｰ々ゝゞ":
        return False
    return True


def _same_column(left: Rect, right: Rect) -> bool:
    return abs(right.x0 - left.x0) <= max(48.0, left.height * 2.5)


def _column_wraps(page: PageIndex) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """Pair each full line with the next line in the same column, then a short tail."""
    infos: list[tuple[int, int, Rect, int]] = []
    for start, stop in _body_runs(page):
        glyphs = page.glyphs[start:stop]
        if not glyphs:
            continue
        box = page.lines[glyphs[0].line_id].bbox
        infos.append((start, stop, box, stop - start))
    if len(infos) < 2:
        return []
    edges: list[list[float]] = []
    for _, _, box, _ in infos:
        for edge in edges:
            if abs(edge[0] - box.x0) <= max(48.0, box.height * 2.5):
                edge[1] = max(edge[1], box.x1)
                break
        else:
            edges.append([box.x0, box.x1])

    def reaches(box: Rect) -> bool:
        right = box.x1
        for origin, far in edges:
            if abs(origin - box.x0) <= max(48.0, box.height * 2.5):
                right = max(right, far)
        return box.x1 >= right - max(48.0, box.height * 3.0)

    def next_below(index: int) -> int | None:
        _, _, box, _ = infos[index]
        best: int | None = None
        best_y: float | None = None
        for other, (_, _, below, _) in enumerate(infos):
            if other == index or below.y0 < box.y1 - 2:
                continue
            if not _same_column(box, below):
                continue
            if best_y is None or below.y0 < best_y:
                best = other
                best_y = below.y0
        return best

    successors: dict[int, int] = {}
    for index, (_, _, box, _) in enumerate(infos):
        nxt = next_below(index)
        if nxt is None:
            continue
        if is_line_wrap(box, infos[nxt][2]) and reaches(box):
            successors[index] = nxt
    # A short middle piece (イザ) continues onto the following line.
    growing = True
    while growing:
        growing = False
        for index, nxt in list(successors.items()):
            if nxt in successors:
                continue
            further = next_below(nxt)
            if further is None:
                continue
            if infos[nxt][3] <= 12 and is_line_wrap(infos[nxt][2], infos[further][2]):
                successors[nxt] = further
                growing = True
    return [((infos[index][0], infos[index][1]), (infos[nxt][0], infos[nxt][1])) for index, nxt in successors.items()]


def wrap_pairs(
    pages: tuple[PageIndex, ...] | list[PageIndex],
) -> list[tuple[tuple[PageIndex, int, int], tuple[PageIndex, int, int]]]:
    """Line pairs whose text should be read as one wrapped line."""
    pairs: list[tuple[tuple[PageIndex, int, int], tuple[PageIndex, int, int]]] = []
    for page in pages:
        for left, right in _column_wraps(page):
            pairs.append(((page, left[0], left[1]), (page, right[0], right[1])))
    for previous, nxt in zip(pages, pages[1:]):
        if not previous.glyphs or not nxt.glyphs:
            continue
        last = _body_runs(previous)[-1]
        first = _body_runs(nxt)[0]
        left = previous.lines[previous.glyphs[last[0]].line_id].bbox
        right = nxt.lines[nxt.glyphs[first[0]].line_id].bbox
        if is_page_wrap(left, right):
            pairs.append(((previous, last[0], last[1]), (nxt, first[0], first[1])))
    return pairs


def line_ids_of(glyphs: tuple[Glyph, ...] | list[Glyph]) -> tuple[str, ...]:
    seen: list[str] = []
    for glyph in glyphs:
        if glyph.line_id not in seen:
            seen.append(glyph.line_id)
    return tuple(seen)
