from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from ekisui_pdf.core.geometry import span_rect
from ekisui_pdf.core.models import OcrLine, Rect

# NFKC 後の表記。㈱ は NFKC で (株) になる。
_MARKERS = ("株式会社", "(株)", "有限会社", "合同会社")


@dataclass(frozen=True)
class TextHit:
    surface: str
    page_index: int
    line_id: str
    char_start: int
    char_end: int
    rect: Rect


def _compact(text: str) -> tuple[str, list[int]]:
    """空白を除いて NFKC にし、各文字が元のどの位置か返す。"""
    chars: list[str] = []
    origin: list[int] = []
    for index, char in enumerate(text):
        if char.isspace():
            continue
        for normalized in unicodedata.normalize("NFKC", char):
            chars.append(normalized)
            origin.append(index)
    return "".join(chars), origin


def core_key(text: str) -> str:
    """全角半角と空白、両端の会社種別を除いた照合キー。"""
    compact, _ = _compact(text)
    changed = True
    while changed and compact:
        changed = False
        for marker in _MARKERS:
            if compact.startswith(marker):
                compact = compact[len(marker) :]
                changed = True
            if compact.endswith(marker) and len(compact) > len(marker):
                compact = compact[: -len(marker)]
                changed = True
    return compact


def _hits_for_needle(lines: list[OcrLine], needle: str, *, expand_markers: bool) -> list[TextHit]:
    if not needle:
        return []
    hits: list[TextHit] = []
    for line in lines:
        compact, origin = _compact(line.text)
        cursor = 0
        while True:
            found = compact.find(needle, cursor)
            if found < 0:
                break
            end = found + len(needle)
            if expand_markers:
                grew = True
                while grew:
                    grew = False
                    for marker in _MARKERS:
                        if found >= len(marker) and compact.startswith(marker, found - len(marker)):
                            found -= len(marker)
                            grew = True
                            break
                grew = True
                while grew:
                    grew = False
                    for marker in _MARKERS:
                        if compact.startswith(marker, end):
                            end += len(marker)
                            grew = True
                            break
            char_start = origin[found]
            char_end = origin[end - 1] + 1
            surface = line.text[char_start:char_end]
            hits.append(
                TextHit(
                    surface=surface,
                    page_index=line.page_index,
                    line_id=line.line_id,
                    char_start=char_start,
                    char_end=char_end,
                    rect=span_rect(line, char_start, char_end),
                )
            )
            cursor = end
    return hits


def search_phrase(lines: list[OcrLine], query: str) -> list[TextHit]:
    """空白を無視し、全角と半角を同一視して語句を探す。"""
    needle, _ = _compact(query)
    return _hits_for_needle(lines, needle, expand_markers=False)


def find_variants(lines: list[OcrLine], term: str) -> list[TextHit]:
    """会社種別の有無を含む表記ゆれを探す。"""
    return _hits_for_needle(lines, core_key(term), expand_markers=True)


def group_surfaces(hits: list[TextHit]) -> list[tuple[str, list[TextHit]]]:
    groups: dict[str, list[TextHit]] = {}
    order: list[str] = []
    for hit in hits:
        if hit.surface not in groups:
            order.append(hit.surface)
            groups[hit.surface] = []
        groups[hit.surface].append(hit)
    return [(surface, groups[surface]) for surface in order]
