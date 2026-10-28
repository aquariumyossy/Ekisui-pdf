from __future__ import annotations

from dataclasses import dataclass

import pymupdf

from ekisui.domain.index import build_document_index, is_line_wrap, is_page_wrap, line_runs, parts_of
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
    runs: list[tuple] = []
    for page in index:
        for start, stop in line_runs(page):
            glyphs = page.glyphs[start:stop]
            if glyphs:
                runs.append((page, glyphs, "".join(glyph.strict for glyph in glyphs)))
    found: list[Leftover] = []
    for (left_page, _left_glyphs, left_text), (right_page, right_glyphs, right_text) in zip(runs, runs[1:]):
        left_box = left_page.lines[_left_glyphs[0].line_id].bbox
        right_box = right_page.lines[right_glyphs[0].line_id].bbox
        same_page = left_page.page_index == right_page.page_index
        if same_page:
            if not is_line_wrap(left_box, right_box):
                continue
        elif right_page.page_index != left_page.page_index + 1 or not is_page_wrap(left_box, right_box):
            continue
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
