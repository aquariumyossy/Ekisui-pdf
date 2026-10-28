from __future__ import annotations

from dataclasses import dataclass

import pymupdf

from ekisui.domain.index import build_document_index, parts_of, wrap_pairs
from ekisui.domain.match import search_pages
from ekisui.domain.normalize import ConfusableTable, strict_text
from ekisui.domain.session import TermGroup
from ekisui.domain.types import Document, MatchKind, Page, PageKind, Rect, Settings
from ekisui.pdf.document import extract_lines


@dataclass(frozen=True)
class Leftover:
    term: str
    page_index: int
    kind: MatchKind
    score: float
    bbox: Rect
    explanation: str


@dataclass(frozen=True)
class VerifyReport:
    clean: bool
    checked_terms: int
    checked_surfaces: int
    leftovers: tuple[Leftover, ...]
    metadata_clean: bool | None

    @property
    def passed(self) -> bool:
        metadata_ok = self.metadata_clean is not False
        return self.clean and metadata_ok


def verify_pdf(
    path: str,
    groups: list[TermGroup],
    settings: Settings,
    table: ConfusableTable,
    check_metadata: bool,
) -> VerifyReport:
    opened = pymupdf.open(path)
    try:
        pages = []
        for index, page in enumerate(opened):
            lines = tuple(extract_lines(page, index))
            rect = page.rect
            pages.append(
                Page(
                    index=index,
                    width=float(rect.width),
                    height=float(rect.height),
                    kind=PageKind.NATIVE,
                    lines=lines,
                    source_index=index,
                )
            )
        document = Document(source_path=path, pages=tuple(pages))
        index = build_document_index(document, table)
        leftovers: list[Leftover] = []
        seen: set[tuple[str, int, int]] = set()
        checked_terms = 0
        checked_surfaces = 0
        for group in groups:
            included = group.included_hits()
            if not included:
                continue
            queries = _queries_for(group)
            checked_terms += 1
            checked_surfaces += len(queries)
            for query in queries:
                for hit in search_pages(index, query, settings, table):
                    key = (strict_text(hit.surface), hit.page_index, int(hit.bbox.x0), int(hit.bbox.y0))
                    if key in seen:
                        continue
                    seen.add(key)
                    leftovers.append(
                        Leftover(
                            term=hit.surface,
                            page_index=hit.page_index,
                            kind=hit.kind,
                            score=hit.score,
                            bbox=hit.bbox,
                            explanation=hit.explanation,
                        )
                    )
                leftovers.extend(_fragment_leftovers(index, query, seen))
                leftovers.extend(_wrap_leftovers(index, query, seen))
            leftovers.extend(_tails_below_hits(index, group, seen))
        metadata_clean = metadata_is_clean(opened) if check_metadata else None
        return VerifyReport(
            clean=not leftovers,
            checked_terms=checked_terms,
            checked_surfaces=checked_surfaces,
            leftovers=tuple(leftovers),
            metadata_clean=metadata_clean,
        )
    finally:
        opened.close()


def _queries_for(group: TermGroup) -> list[str]:
    """Adjusted hits are checked at their current text, not the original canonical."""
    included = group.included_hits()
    queries: list[str] = []
    if any(not tracked.adjusted for tracked in included):
        queries.append(group.canonical)
    for tracked in included:
        surface = tracked.hit.surface
        if tracked.adjusted or strict_text(surface) != strict_text(group.canonical):
            if all(strict_text(surface) != strict_text(query) for query in queries):
                queries.append(surface)
        for extra in (tracked.prior_surface, tracked.corrected_surface):
            if extra and all(strict_text(extra) != strict_text(query) for query in queries):
                queries.append(extra)
    if not queries and included:
        queries.append(included[0].hit.surface)
    return queries


def _fragment_leftovers(index, query: str, seen: set) -> list[Leftover]:
    """A clipped redaction can leave half a name. The full-term search misses that."""
    needle = strict_text(query)
    if len(needle) < 8:
        return []
    half = max(4, (len(needle) + 1) // 2)
    pieces = {needle[:half], needle[-half:]}
    found: list[Leftover] = []
    for page in index:
        for piece in pieces:
            if not piece or piece not in page.strict:
                continue
            key = (piece, page.page_index, 0, 0)
            if key in seen:
                continue
            seen.add(key)
            found.append(
                Leftover(
                    term=piece,
                    page_index=page.page_index,
                    kind=MatchKind.EXACT,
                    score=1.0,
                    bbox=Rect(0, 0, 8, 8),
                    explanation="語句の一部が残っています",
                )
            )
    return found


def _wrap_leftovers(index, query: str, seen: set) -> list[Leftover]:
    """A wrapped term can leave its tail, often 「ー」, at the start of the next line."""
    needle = strict_text(query)
    if len(needle) < 2:
        return []
    found: list[Leftover] = []
    for (left_page, left_start, left_stop), (right_page, right_start, right_stop) in wrap_pairs(index):
        left_text = left_page.strict[left_start:left_stop]
        right_text = right_page.strict[right_start:right_stop]
        right_glyphs = right_page.glyphs[right_start:right_stop]
        split = _suffix_at_start(needle, right_text)
        if split is None:
            continue
        prefix, suffix = needle[:split], needle[split:]
        if left_text.endswith(prefix):
            continue
        if len(suffix) < 2 and suffix[:1] not in "ーｰ々ゝゞ":
            continue
        chosen = []
        acc = ""
        for glyph in right_glyphs:
            chosen.append(glyph)
            acc += glyph.strict
            if len(acc) >= len(suffix):
                break
        if not acc.startswith(suffix):
            continue
        rect = parts_of(chosen)[0]
        key = (suffix, right_page.page_index, int(rect.x0), int(rect.y0))
        if key in seen:
            continue
        seen.add(key)
        found.append(
            Leftover(
                term=suffix,
                page_index=right_page.page_index,
                kind=MatchKind.EXACT,
                score=1.0,
                bbox=rect,
                explanation="行の先頭に語句の続きが残っています",
            )
        )
    return found


def _tails_below_hits(index, group: TermGroup, seen: set) -> list[Leftover]:
    """A burned prefix can leave ー on the next line after the line gap has grown."""
    needle = strict_text(group.canonical)
    found: list[Leftover] = []
    if len(needle) < 2:
        return found
    for tracked in group.included_hits():
        surface = strict_text(tracked.hit.surface)
        if len(surface) < 2 or not needle.startswith(surface) or len(surface) >= len(needle):
            continue
        missing = needle[len(surface) :]
        rects = tracked.hit.parts or (tracked.hit.bbox,)
        if not rects:
            continue
        bottom = max(rect.y1 for rect in rects)
        pages = []
        if 0 <= tracked.hit.page_index < len(index):
            pages.append(index[tracked.hit.page_index])
        if tracked.hit.page_index + 1 < len(index):
            pages.append(index[tracked.hit.page_index + 1])
        for page in pages:
            for line in page.lines.values():
                text = strict_text(line.text)
                if not text.startswith(missing):
                    continue
                same_page = page.page_index == tracked.hit.page_index
                if same_page and (line.bbox.y0 < bottom - 4 or line.bbox.y0 - bottom > 96):
                    continue
                if not same_page and line.bbox.y0 > 140:
                    continue
                key = (missing, page.page_index, int(line.bbox.x0), int(line.bbox.y0))
                if key in seen:
                    continue
                seen.add(key)
                found.append(
                    Leftover(
                        term=missing if len(missing) <= 8 else missing[:8],
                        page_index=page.page_index,
                        kind=MatchKind.EXACT,
                        score=1.0,
                        bbox=line.bbox,
                        explanation="行の先頭に語句の続きが残っています",
                    )
                )
    return found


def _suffix_at_start(needle: str, text: str) -> int | None:
    """Index where the longest proper suffix of ``needle`` begins, if ``text`` starts with it."""
    for split in range(1, len(needle)):
        if text.startswith(needle[split:]):
            return split
    return None


def metadata_is_clean(doc: pymupdf.Document) -> bool:
    meta = doc.metadata or {}
    for key in ("author", "title", "subject", "keywords", "creator", "producer"):
        if str(meta.get(key) or "").strip():
            return False
    try:
        xml = doc.get_xml_metadata() or ""
    except Exception:
        xml = ""
    if xml.strip():
        return False
    if doc.embfile_count():
        return False
    catalog = doc.pdf_catalog()
    for key in ("OpenAction", "AA"):
        kind, value = doc.xref_get_key(catalog, key)
        if kind != "null" and value not in {"null", ""}:
            return False
    return True
