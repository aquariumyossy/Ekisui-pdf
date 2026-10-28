from __future__ import annotations

from dataclasses import dataclass

from ekisui.domain.index import bbox_of, line_ids_of, parts_of, surface_of, wrap_pairs
from ekisui.domain.normalize import ConfusableTable, loose_text, strict_text
from ekisui.domain.types import Glyph, Hit, MatchKind, PageIndex, Rect, Settings


@dataclass(frozen=True)
class _Match:
    pieces: tuple[tuple[int, int, int], ...]
    kind: MatchKind
    score: float
    explanation: str
    ocr_like: bool

    def length(self) -> int:
        return sum(end - start for _page, start, end in self.pieces)


def search_pages(
    pages: tuple[PageIndex, ...] | list[PageIndex],
    term: str,
    settings: Settings,
    table: ConfusableTable,
) -> list[Hit]:
    needle_strict = strict_text(term)
    needle_loose = loose_text(term, table)
    if len(needle_strict) < 2:
        return []
    found: list[_Match] = []
    for page in pages:
        found.extend(_search_page(page, needle_strict, needle_loose, settings, table))
    found.extend(_search_wraps(pages, needle_strict, needle_loose, settings, table))
    hits: list[Hit] = []
    for match in _pick(found):
        hits.extend(_hits_for(pages, match))
    return _dedup(hits)


def text_in_rect(page: PageIndex, rect: Rect) -> str:
    chosen = [glyph for glyph in page.glyphs if rect.contains(*glyph.bbox.center())]
    if not chosen:
        return ""
    return surface_of(chosen, page.lines)


def _search_page(
    page: PageIndex,
    needle_strict: str,
    needle_loose: str,
    settings: Settings,
    table: ConfusableTable,
) -> list[_Match]:
    found: list[_Match] = []
    occupied: list[tuple[int, int]] = []
    for start, stop in page.paragraphs:
        strict = page.strict[start:stop]
        loose = page.loose[start:stop]
        for local_start, local_end, kind, score, explanation, ocr_like in _search_string(
            strict, loose, needle_strict, needle_loose, settings, table
        ):
            abs_start = start + local_start
            abs_end = start + local_end
            if any(abs_start < end and start_ < abs_end for start_, end in occupied):
                continue
            occupied.append((abs_start, abs_end))
            found.append(
                _Match(
                    ((page.page_index, abs_start, abs_end),),
                    kind,
                    score,
                    explanation,
                    ocr_like,
                )
            )
    return found


def _search_wraps(
    pages: tuple[PageIndex, ...] | list[PageIndex],
    needle_strict: str,
    needle_loose: str,
    settings: Settings,
    table: ConfusableTable,
) -> list[_Match]:
    """A term split by a line break or a page break is still one match."""
    if len(needle_strict) < 2:
        return []
    slack = _max_distance(len(needle_strict), settings.fuzzy_threshold)
    take = len(needle_strict) + slack
    found: list[_Match] = []
    for (left_page, left_start, left_stop), (right_page, right_start, right_stop) in wrap_pairs(pages):
        cut = max(left_start, left_stop - take)
        right_end = min(right_stop, right_start + take)
        left_count = left_stop - cut
        if left_count <= 0 or right_end <= right_start:
            continue
        strict = left_page.strict[cut:left_stop] + right_page.strict[right_start:right_end]
        loose = left_page.loose[cut:left_stop] + right_page.loose[right_start:right_end]
        for local_start, local_end, kind, score, explanation, ocr_like in _search_string(
            strict, loose, needle_strict, needle_loose, settings, table
        ):
            if local_start >= left_count or local_end <= left_count:
                continue
            left_from = cut + local_start
            right_to = right_start + (local_end - left_count)
            if left_page.page_index == right_page.page_index and left_stop == right_start:
                pieces = ((left_page.page_index, left_from, right_to),)
            else:
                pieces = (
                    (left_page.page_index, left_from, left_stop),
                    (right_page.page_index, right_start, right_to),
                )
            found.append(_Match(pieces, kind, score, explanation, ocr_like))
    return found


def _search_string(
    strict: str,
    loose: str,
    needle_strict: str,
    needle_loose: str,
    settings: Settings,
    table: ConfusableTable,
) -> list[tuple[int, int, MatchKind, float, str, bool]]:
    n = len(needle_strict)
    if n == 0 or len(strict) < 2:
        return []
    raw: list[tuple[int, int, MatchKind, float, str, bool, int]] = []
    position = 0
    while True:
        found = strict.find(needle_strict, position)
        if found < 0:
            break
        raw.append((found, found + n, MatchKind.EXACT, 1.0, "", False, 0))
        position = found + max(n, 1)

    threshold = settings.fuzzy_threshold
    max_distance = _max_distance(n, threshold)
    if n <= 3:
        windows = (n,)
    else:
        low = max(2, n - max_distance)
        high = min(len(strict), n + max_distance)
        windows = tuple(range(low, high + 1))

    covered = [(item[0], item[1]) for item in raw]
    for width in windows:
        if width <= 0 or width > len(strict):
            continue
        limit = len(strict) - width + 1
        for index in range(limit):
            if any(index < end and start < index + width for start, end in covered):
                continue
            window = strict[index : index + width]
            loose_window = loose[index : index + width]
            if window == needle_strict:
                continue
            ocr_like = _ocr_like(window, needle_strict, table)
            loose_equal = loose_window == needle_loose
            if n <= 3:
                if not (loose_equal or _one_confusable(window, needle_strict, table)):
                    continue
                score = 1.0 - (_hamming(window, needle_strict) / n)
            else:
                if not loose_equal and abs(len(window) - n) > max_distance:
                    continue
                distance = _levenshtein_at_most(
                    window, needle_strict, max(n, width) if loose_equal else max_distance
                )
                if distance is None:
                    continue
                score = 1.0 - (distance / max(n, width))
                if score + 1e-9 < threshold and not loose_equal:
                    continue
            explanation = _explain(needle_strict, window)
            raw.append((index, index + width, MatchKind.FUZZY, score, explanation, ocr_like, 1))

    raw.sort(key=lambda item: (-item[3], item[6], item[0], -(item[1] - item[0])))
    chosen: list[tuple[int, int, MatchKind, float, str, bool]] = []
    taken: list[tuple[int, int]] = []
    for start, end, kind, score, explanation, ocr_like, _rank in raw:
        if any(start < stop and begin < end for begin, stop in taken):
            continue
        taken.append((start, end))
        chosen.append((start, end, kind, score, explanation, ocr_like))
    chosen.sort(key=lambda item: item[0])
    return chosen


def _max_distance(length: int, threshold: float) -> int:
    if length <= 3:
        return 1
    return max(int((1.0 - threshold) * max(length, 1) + 1e-9), 1)


def _pick(matches: list[_Match]) -> list[_Match]:
    ranked = sorted(
        matches,
        key=lambda item: (
            item.kind != MatchKind.EXACT,
            -item.score,
            -item.length(),
            item.pieces[0][0],
            item.pieces[0][1],
        ),
    )
    taken: set[tuple[int, int]] = set()
    kept: list[_Match] = []
    for match in ranked:
        cells = [
            (page, index)
            for page, start, end in match.pieces
            for index in range(start, end)
        ]
        if any(cell in taken for cell in cells):
            continue
        taken.update(cells)
        kept.append(match)
    kept.sort(key=lambda item: (item.pieces[0][0], item.pieces[0][1]))
    return kept


def _hits_for(pages: tuple[PageIndex, ...] | list[PageIndex], match: _Match) -> list[Hit]:
    by_index = {page.page_index: page for page in pages}
    groups: list[tuple[PageIndex, list[Glyph]]] = []
    lines = {}
    all_glyphs: list[Glyph] = []
    for page_index, start, end in match.pieces:
        page = by_index[page_index]
        glyphs = list(page.glyphs[start:end])
        if not glyphs:
            continue
        groups.append((page, glyphs))
        all_glyphs.extend(glyphs)
        lines.update(page.lines)
    if not all_glyphs:
        return []
    surface = surface_of(all_glyphs, lines)
    hits: list[Hit] = []
    for page, glyphs in groups:
        parts = parts_of(glyphs)
        hits.append(
            Hit(
                page_index=page.page_index,
                surface=surface,
                bbox=bbox_of(glyphs) if len(parts) == 1 else parts[0],
                kind=match.kind,
                score=match.score,
                explanation=match.explanation,
                line_ids=line_ids_of(glyphs),
                ocr_like=match.ocr_like,
                parts=parts,
            )
        )
    return hits


def _ocr_like(window: str, needle: str, table: ConfusableTable) -> bool:
    if len(window) != len(needle) or window == needle:
        return False
    return all(left == right or table.same(left, right) for left, right in zip(window, needle))


def _one_confusable(window: str, needle: str, table: ConfusableTable) -> bool:
    if len(window) != len(needle):
        return False
    diffs = [(left, right) for left, right in zip(window, needle) if left != right]
    return len(diffs) == 1 and table.same(*diffs[0])


def _hamming(a: str, b: str) -> int:
    if len(a) != len(b):
        return max(len(a), len(b))
    return sum(left != right for left, right in zip(a, b))


def _explain(needle: str, window: str) -> str:
    if len(needle) == len(window):
        diffs = [(left, right) for left, right in zip(needle, window) if left != right]
        if len(diffs) == 1:
            left, right = diffs[0]
            return f"「{left}」→「{right}」が1字違い"
        if len(diffs) > 1:
            return f"{len(diffs)}字違い"
    distance = _levenshtein_at_most(window, needle, max(len(window), len(needle)))
    if distance:
        return f"{distance}字違い"
    return "表記ゆれ"


def _levenshtein_at_most(a: str, b: str, limit: int) -> int | None:
    if a == b:
        return 0
    if abs(len(a) - len(b)) > limit:
        return None
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        row_min = i
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            value = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            current.append(value)
            if value < row_min:
                row_min = value
        if row_min > limit:
            return None
        previous = current
    distance = previous[-1]
    if distance > limit:
        return None
    return distance


def _dedup(hits: list[Hit]) -> list[Hit]:
    kept: list[Hit] = []
    for hit in hits:
        if any(
            other.page_index == hit.page_index
            and other.surface == hit.surface
            and other.bbox.intersects(hit.bbox)
            and abs(other.bbox.x0 - hit.bbox.x0) < 2
            and abs(other.bbox.y0 - hit.bbox.y0) < 2
            for other in kept
        ):
            continue
        kept.append(hit)
    return kept
