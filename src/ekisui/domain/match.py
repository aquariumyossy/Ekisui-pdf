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
    """A term split by a line break, a third line, or a page break is still one match."""
    if len(needle_strict) < 2:
        return []
    take = len(needle_strict) + _max_distance(len(needle_strict), settings.fuzzy_threshold)
    by_index = {page.page_index: page for page in pages}
    found: list[_Match] = []
    for chain in _wrap_chains(wrap_pairs(pages)):
        for window in _windows_for(chain, by_index, take):
            found.extend(_matches_in_window(window, needle_strict, needle_loose, settings, table))
    return found


def _windows_for(
    chain: list[tuple[PageIndex, int, int]],
    by_index: dict[int, PageIndex],
    take: int,
) -> list[list[tuple[PageIndex, int, int]]]:
    windows = [_chain_window([left, right], by_index, take) for left, right in zip(chain, chain[1:])]
    short_middle = all(stop - start <= take for _, start, stop in chain[1:-1])
    if len(chain) > 2 and short_middle:
        windows.append(_chain_window(chain, by_index, take))
    return windows


def _matches_in_window(
    window: list[tuple[PageIndex, int, int]],
    needle_strict: str,
    needle_loose: str,
    settings: Settings,
    table: ConfusableTable,
) -> list[_Match]:
    if len(window) < 2:
        return []
    cursor: list[tuple[int, int]] = []
    strict_parts: list[str] = []
    loose_parts: list[str] = []
    boundaries: list[int] = []
    for page, start, stop in window:
        if stop <= start:
            continue
        boundaries.append(len(cursor))
        strict_parts.append(page.strict[start:stop])
        loose_parts.append(page.loose[start:stop])
        cursor.extend((page.page_index, index) for index in range(start, stop))
    if len(boundaries) < 2 or not cursor:
        return []
    first_end = boundaries[1]
    found: list[_Match] = []
    for local_start, local_end, kind, score, explanation, ocr_like in _search_string(
        "".join(strict_parts), "".join(loose_parts), needle_strict, needle_loose, settings, table
    ):
        if local_end <= first_end or local_start >= len(cursor):
            continue
        pieces = _pieces_from(cursor[local_start:local_end])
        if pieces:
            found.append(_Match(pieces, kind, score, explanation, ocr_like))
    return found


def _wrap_chains(
    pairs: list[tuple[tuple[PageIndex, int, int], tuple[PageIndex, int, int]]],
) -> list[list[tuple[PageIndex, int, int]]]:
    def key(node: tuple[PageIndex, int, int]) -> tuple[int, int, int]:
        return (node[0].page_index, node[1], node[2])

    nxt: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    node: dict[tuple[int, int, int], tuple[PageIndex, int, int]] = {}
    for left, right in pairs:
        nxt[key(left)] = key(right)
        node[key(left)] = left
        node[key(right)] = right
    heads = [item for item in nxt if item not in nxt.values()]
    chains: list[list[tuple[PageIndex, int, int]]] = []
    for head in heads:
        chain = [node[head]]
        seen = {head}
        cur = head
        while cur in nxt and nxt[cur] not in seen:
            cur = nxt[cur]
            seen.add(cur)
            chain.append(node[cur])
        if len(chain) >= 2:
            chains.append(chain)
    return chains


def _chain_window(
    chain: list[tuple[PageIndex, int, int]],
    by_index: dict[int, PageIndex],
    take: int,
) -> list[tuple[PageIndex, int, int]]:
    """Tail of the first line, short middle lines, and the head of the last line."""
    window: list[tuple[PageIndex, int, int]] = []
    page, start, stop = chain[0]
    window.append((by_index[page.page_index], max(start, stop - take), stop))
    for page, start, stop in chain[1:-1]:
        if stop - start > take:
            break
        window.append((by_index[page.page_index], start, stop))
    else:
        page, start, stop = chain[-1]
        window.append((by_index[page.page_index], start, min(stop, start + take)))
    return window


def _pieces_from(chosen: list[tuple[int, int]]) -> tuple[tuple[int, int, int], ...]:
    pieces: list[list[int]] = []
    for page_index, index in chosen:
        if pieces and pieces[-1][0] == page_index and pieces[-1][2] == index:
            pieces[-1][2] = index + 1
        else:
            pieces.append([page_index, index, index + 1])
    return tuple((item[0], item[1], item[2]) for item in pieces)


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
    grouped: dict[int, list[Glyph]] = {}
    lines = {}
    all_glyphs: list[Glyph] = []
    for page_index, start, end in match.pieces:
        page = by_index[page_index]
        glyphs = list(page.glyphs[start:end])
        if not glyphs:
            continue
        grouped.setdefault(page_index, []).extend(glyphs)
        all_glyphs.extend(glyphs)
        lines.update(page.lines)
    groups = [(by_index[page_index], glyphs) for page_index, glyphs in grouped.items()]
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
