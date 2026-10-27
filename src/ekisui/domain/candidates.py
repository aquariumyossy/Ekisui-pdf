from __future__ import annotations

import re
from dataclasses import dataclass

from ekisui.domain.index import bbox_of, line_ids_of, surface_of
from ekisui.domain.match import search_pages
from ekisui.domain.normalize import ConfusableTable, fold_digits
from ekisui.paths import resource_path
from ekisui.domain.types import (
    Category,
    Hit,
    MatchKind,
    PageIndex,
    Settings,
    Span,
    iou,
)

_COMPANY_PREFIX = (
    "株式会社|有限会社|合同会社|合名会社|合資会社|"
    "一般社団法人|一般財団法人|公益社団法人|公益財団法人|"
    "社会福祉法人|医療法人|学校法人|弁護士法人|税理士法人|"
    "司法書士法人|行政書士法人|特定非営利活動法人"
)
_BODY = r"[0-9A-Za-z\u30A0-\u30FF\u4E00-\u9FFF]{1,18}"
_COMPANY_RES = (
    re.compile(rf"(?:{_COMPANY_PREFIX}){_BODY}"),
    re.compile(rf"{_BODY}(?:株式会社|有限会社|合同会社)"),
    re.compile(rf"\(株\){_BODY}"),
    re.compile(rf"{_BODY}\(株\)"),
)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(
    r"(?<![0-9])(?:\+81-?[0-9]{1,4}-?[0-9]{1,4}-?[0-9]{3,4}"
    r"|0[0-9]{1,4}-[0-9]{1,4}-[0-9]{3,4}"
    r"|0[0-9]{9,10})(?![0-9])"
)
_POSTAL_RE = re.compile(r"〒?[0-9]{3}-[0-9]{4}")
_ACCOUNT_RE = re.compile(r"(?:口座番号|口座)[:：]?([0-9]{5,8})")
_ALNUM_RE = re.compile(r"(?<![A-Za-z0-9])(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{3,}(?![A-Za-z0-9])")
_GIVEN_STOP = {
    "会社", "商事", "銀行", "工業", "事務所", "合同", "有限", "株式",
    "です", "ます", "した", "して", "から", "まで", "より", "こと", "もの", "ため", "さん",
}
_PRIORITY = {
    Category.COMPANY: 0,
    Category.ADDRESS: 1,
    Category.PERSON: 2,
    Category.EMAIL: 3,
    Category.PHONE: 4,
    Category.ACCOUNT: 5,
    Category.POSTAL: 6,
    Category.ALNUM: 7,
}


@dataclass(frozen=True)
class AutoGroup:
    category: Category
    canonical: str
    hits: tuple[Hit, ...]


def load_surnames() -> tuple[str, ...]:
    text = resource_path("surnames.txt").read_text(encoding="utf-8")
    names = []
    seen = set()
    for line in text.splitlines():
        name = line.strip()
        if not name or name.startswith("#") or name in seen:
            continue
        seen.add(name)
        names.append(name)
    names.sort(key=len, reverse=True)
    return tuple(names)


def load_prefectures() -> tuple[str, ...]:
    text = resource_path("prefectures.txt").read_text(encoding="utf-8")
    names = [line.strip() for line in text.splitlines() if line.strip()]
    names.sort(key=len, reverse=True)
    return tuple(names)


def suggest(
    pages: tuple[PageIndex, ...] | list[PageIndex],
    settings: Settings,
    table: ConfusableTable,
    surnames: tuple[str, ...] | None = None,
    prefectures: tuple[str, ...] | None = None,
) -> list[AutoGroup]:
    surnames = surnames if surnames is not None else load_surnames()
    prefectures = prefectures if prefectures is not None else load_prefectures()
    ordered_surnames = tuple(sorted(set(surnames), key=len, reverse=True))
    person_re = _person_re(ordered_surnames)
    address_re = _address_re(prefectures)
    spans: list[Span] = []
    for page in pages:
        spans.extend(_page_spans(page, person_re, address_re, ordered_surnames))
    spans = _resolve_overlaps(spans)
    spans.sort(key=lambda span: (-(span.end - span.start), _PRIORITY.get(span.category, 9), span.page_index, span.start))
    used: list[tuple[int, object]] = []
    groups: list[AutoGroup] = []
    for span in spans:
        if any(box_page == span.page_index and iou(span.bbox, box) > 0.5 for box_page, box in used):
            continue
        found = search_pages(pages, span.surface, settings, table)
        if span.category in {Category.PERSON, Category.COMPANY}:
            kept = [hit for hit in found if hit.kind == MatchKind.EXACT or hit.ocr_like]
        else:
            kept = [hit for hit in found if hit.kind == MatchKind.EXACT or hit.ocr_like]
        if not any(hit.page_index == span.page_index and iou(hit.bbox, span.bbox) > 0.5 for hit in kept):
            kept.insert(0, _hit_from_span(span))
        deduped: list[Hit] = []
        for hit in kept:
            if any(hit.page_index == other.page_index and iou(hit.bbox, other.bbox) > 0.8 for other in deduped):
                continue
            deduped.append(hit)
        for hit in deduped:
            used.append((hit.page_index, hit.bbox))
        groups.append(AutoGroup(span.category, span.surface, tuple(deduped)))
    return groups


def _person_re(surnames: tuple[str, ...]) -> re.Pattern[str]:
    ordered = tuple(sorted(set(surnames), key=len, reverse=True))
    body = "|".join(re.escape(name) for name in ordered)
    return re.compile(rf"(?:{body})[\u4E00-\u9FFF\u30A0-\u30FF]{{1,3}}")


def _address_re(prefectures: tuple[str, ...]) -> re.Pattern[str]:
    body = "|".join(re.escape(name) for name in prefectures)
    return re.compile(
        rf"(?:{body})(?:[0-9A-Za-z\u30A0-\u30FF\u4E00-\u9FFF\-－]{{0,28}}?)"
        rf"[0-9]+(?:-[0-9]+)*(?:丁目|番地|番|号)?"
    )


def _page_spans(
    page: PageIndex,
    person_re: re.Pattern[str],
    address_re: re.Pattern[str],
    surnames: tuple[str, ...],
) -> list[Span]:
    spans: list[Span] = []
    cursor = 0
    glyphs = page.glyphs
    while cursor < len(glyphs):
        line_id = glyphs[cursor].line_id
        end = cursor + 1
        while end < len(glyphs) and glyphs[end].line_id == line_id:
            end += 1
        text = page.strict[cursor:end]
        folded = fold_digits(text)
        spans.extend(_regex_spans(page, cursor, text, _EMAIL_RE, Category.EMAIL))
        spans.extend(_phone_spans(page, cursor, folded))
        spans.extend(_regex_spans(page, cursor, folded, _POSTAL_RE, Category.POSTAL))
        spans.extend(_account_spans(page, cursor, folded))
        spans.extend(_regex_spans(page, cursor, text, _ALNUM_RE, Category.ALNUM))
        spans.extend(_regex_spans(page, cursor, text, address_re, Category.ADDRESS))
        for pattern in _COMPANY_RES:
            spans.extend(_regex_spans(page, cursor, text, pattern, Category.COMPANY))
        spans.extend(_person_spans(page, cursor, text, person_re, surnames))
        cursor = end
    return spans


def _regex_spans(page: PageIndex, offset: int, text: str, pattern: re.Pattern[str], category: Category) -> list[Span]:
    found = []
    for match in pattern.finditer(text):
        span = _make_span(page, offset + match.start(), offset + match.end(), category)
        if span is not None:
            found.append(span)
    return found


def _phone_spans(page: PageIndex, offset: int, text: str) -> list[Span]:
    found = []
    for match in _PHONE_RE.finditer(text):
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) not in {10, 11} and not match.group(0).startswith("+81"):
            continue
        if match.group(0).startswith("+81") and not 10 <= len(digits) <= 13:
            continue
        span = _make_span(page, offset + match.start(), offset + match.end(), Category.PHONE)
        if span is not None:
            found.append(span)
    return found


def _account_spans(page: PageIndex, offset: int, text: str) -> list[Span]:
    found = []
    for match in _ACCOUNT_RE.finditer(text):
        start, end = match.span(1)
        span = _make_span(page, offset + start, offset + end, Category.ACCOUNT)
        if span is not None:
            found.append(span)
    return found


def _person_spans(
    page: PageIndex,
    offset: int,
    text: str,
    pattern: re.Pattern[str],
    surnames: tuple[str, ...],
) -> list[Span]:
    found = []
    for match in pattern.finditer(text):
        surface = match.group(0)
        given = surface
        for surname in surnames:
            if surface.startswith(surname):
                given = surface[len(surname) :]
                break
        if not given or given in _GIVEN_STOP or given[0] in "はをがにでとものへや":
            continue
        span = _make_span(page, offset + match.start(), offset + match.end(), Category.PERSON)
        if span is not None:
            found.append(span)
    return found


def _make_span(page: PageIndex, start: int, end: int, category: Category) -> Span | None:
    if end - start < 2 and category not in {Category.ALNUM}:
        return None
    if start < 0 or end > len(page.glyphs) or start >= end:
        return None
    glyphs = page.glyphs[start:end]
    return Span(
        page_index=page.page_index,
        start=start,
        end=end,
        surface=surface_of(glyphs, page.lines),
        bbox=bbox_of(glyphs),
        line_ids=line_ids_of(glyphs),
        category=category,
    )


def _hit_from_span(span: Span) -> Hit:
    return Hit(
        page_index=span.page_index,
        surface=span.surface,
        bbox=span.bbox,
        kind=MatchKind.EXACT,
        score=1.0,
        explanation="",
        line_ids=span.line_ids,
        ocr_like=False,
    )


def _resolve_overlaps(spans: list[Span]) -> list[Span]:
    ordered = sorted(
        spans,
        key=lambda span: (-(span.end - span.start), _PRIORITY.get(span.category, 9), span.start),
    )
    kept: list[Span] = []
    for span in ordered:
        if any(
            other.page_index == span.page_index and other.start < span.end and span.start < other.end
            for other in kept
        ):
            continue
        kept.append(span)
    return kept
