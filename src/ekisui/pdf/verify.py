from __future__ import annotations

from dataclasses import dataclass

import pymupdf

from ekisui.domain.index import build_document_index
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
        if not tracked.adjusted and strict_text(surface) == strict_text(group.canonical):
            continue
        if all(strict_text(surface) != strict_text(query) for query in queries):
            queries.append(surface)
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
