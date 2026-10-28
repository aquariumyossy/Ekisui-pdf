from __future__ import annotations

import re
from dataclasses import dataclass, replace

from ekisui.domain.address import find_addresses, load_address_excludes
from ekisui.domain.index import bbox_of, line_ids_of, parts_of, surface_of, wrap_pairs
from ekisui.domain.match import search_pages
from ekisui.domain.normalize import ConfusableTable, fold_digits, strict_text
from ekisui.paths import resource_path
from ekisui.domain.types import (
    Action,
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
    action: Action | None = None


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
    excludes = load_address_excludes()
    spans: list[Span] = []
    for page in pages:
        spans.extend(_page_spans(page, person_re, ordered_surnames))
        spans.extend(_address_spans(page, prefectures, excludes))
        spans.extend(_title_person_spans(page))
    spans.extend(_wrap_candidate_spans(pages, person_re, ordered_surnames))
    spans = _resolve_overlaps(spans)
    spans.sort(key=lambda span: (-(span.end - span.start), _PRIORITY.get(span.category, 9), span.page_index, span.start))
    used: list[tuple[int, object]] = []
    groups: list[AutoGroup] = []
    for span in spans:
        if any(
            box_page == span.page_index and any(iou(rect, box) > 0.5 for rect in (span.parts or (span.bbox,)))
            for box_page, box in used
        ):
            continue
        # Each prefecture span is already complete. Searching its text would also
        # hit the same characters at the start of a longer address and drop that one.
        if span.category == Category.ADDRESS:
            kept = [_hit_from_span(span)]
        else:
            found = search_pages(pages, span.surface, settings, table)
            kept = [hit for hit in found if hit.kind == MatchKind.EXACT or hit.ocr_like]
            if not any(
                hit.page_index == span.page_index
                and any(iou(rect, other) > 0.5 for rect in _hit_rects(hit) for other in (span.parts or (span.bbox,)))
                for hit in kept
            ):
                kept.insert(0, _hit_from_span(span))
        if not span.checked:
            kept = [replace(hit, checked=False) for hit in kept]
        deduped: list[Hit] = []
        for hit in kept:
            if any(
                hit.page_index == other.page_index
                and any(iou(rect, other_rect) > 0.8 for rect in _hit_rects(hit) for other_rect in _hit_rects(other))
                for other in deduped
            ):
                continue
            deduped.append(hit)
        for hit in deduped:
            for rect in _hit_rects(hit):
                used.append((hit.page_index, rect))
        groups.append(AutoGroup(span.category, span.surface, tuple(deduped), span.action))
    return groups


def _person_re(surnames: tuple[str, ...]) -> re.Pattern[str]:
    ordered = tuple(sorted(set(surnames), key=len, reverse=True))
    body = "|".join(re.escape(name) for name in ordered)
    return re.compile(rf"(?:{body})[\u4E00-\u9FFF\u30A0-\u30FF]{{1,3}}")


_TITLES = (
    "裁判所書記官",
    "書記官",
    "裁判官",
    "訴訟代理人",
    "代理人",
    "申立人",
    "相手方",
    "弁護士",
)


def _page_spans(
    page: PageIndex,
    person_re: re.Pattern[str],
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


def _address_spans(page: PageIndex, prefectures: tuple[str, ...], excludes: tuple[str, ...]) -> list[Span]:
    found: list[Span] = []
    for line_id, start, end in _line_groups(page):
        line = page.lines[line_id]
        for text_start, text_end, kind in find_addresses(line.text, prefectures, excludes):
            glyphs = [glyph for glyph in page.glyphs[start:end] if text_start <= glyph.src_index < text_end]
            action = Action.REPLACE if kind == "place" else Action.BLACKOUT
            span = _span_from_glyphs(page, glyphs, Category.ADDRESS, True, action)
            if span is not None:
                found.append(span)
    return found


def _title_person_spans(page: PageIndex) -> list[Span]:
    """Names after a role, including a short seal-noise gap or the next short line."""
    found: list[Span] = []
    groups = _line_groups(page)
    titles = tuple(sorted(_TITLES, key=len, reverse=True))
    for index, (line_id, start, end) in enumerate(groups):
        line = page.lines[line_id]
        cursor = 0
        while cursor < len(line.text):
            title = next((name for name in titles if line.text.startswith(name, cursor)), None)
            if title is None:
                cursor += 1
                continue
            name = _scan_name(line.text, cursor + len(title))
            cursor += len(title)
            if name is None:
                continue
            name_start, name_end = name
            glyphs = [glyph for glyph in page.glyphs[start:end] if name_start <= glyph.src_index < name_end]
            if _one_token(line.text[name_start:name_end]) and index + 1 < len(groups):
                next_id, next_start, next_end = groups[index + 1]
                given = _leading_given(page.lines[next_id].text)
                if given is not None:
                    given_start, given_end = given
                    glyphs.extend(
                        glyph
                        for glyph in page.glyphs[next_start:next_end]
                        if given_start <= glyph.src_index < given_end
                    )
            span = _span_from_glyphs(page, glyphs, Category.PERSON, True)
            if span is not None:
                found.append(span)
    return found


def _line_groups(page: PageIndex) -> list[tuple[str, int, int]]:
    groups: list[tuple[str, int, int]] = []
    cursor = 0
    glyphs = page.glyphs
    while cursor < len(glyphs):
        line_id = glyphs[cursor].line_id
        end = cursor + 1
        while end < len(glyphs) and glyphs[end].line_id == line_id:
            end += 1
        groups.append((line_id, cursor, end))
        cursor = end
    return groups


def _span_from_glyphs(
    page: PageIndex,
    glyphs: list,
    category: Category,
    checked: bool,
    action: Action | None = None,
) -> Span | None:
    if len(glyphs) < 2:
        return None
    chosen = {id(glyph) for glyph in glyphs}
    positions = [index for index, glyph in enumerate(page.glyphs) if id(glyph) in chosen]
    if not positions:
        return None
    return Span(
        page_index=page.page_index,
        start=min(positions),
        end=max(positions) + 1,
        surface=surface_of(glyphs, page.lines),
        bbox=bbox_of(glyphs),
        line_ids=line_ids_of(glyphs),
        category=category,
        checked=checked,
        action=action,
        indexes=tuple(positions),
        parts=parts_of(glyphs),
    )


def _is_name_char(char: str) -> bool:
    code = ord(char)
    if 0x4E00 <= code <= 0x9FFF:
        return True
    return 0x30A0 <= code <= 0x30FF and char not in "・･"


def _scan_name(text: str, start: int) -> tuple[int, int] | None:
    index = start
    limit = len(text)
    while index < limit and text[index].isspace():
        index += 1
    name_start = index
    tokens = 0
    name_end = index
    while tokens < 3 and index < limit:
        while index < limit and text[index].isspace():
            index += 1
        if index >= limit:
            break
        if not _is_name_char(text[index]):
            if tokens == 0:
                break
            probe = index
            noise = 0
            while (
                probe < limit
                and noise < 2
                and not text[probe].isspace()
                and not _is_name_char(text[probe])
                and text[probe] not in "、。，．）)"
            ):
                probe += 1
                noise += 1
            if noise == 0 or probe >= limit or not (_is_name_char(text[probe]) or text[probe].isspace()):
                break
            index = probe
            continue
        probe = index
        while probe < limit and _is_name_char(text[probe]):
            probe += 1
        if probe - index > 6:
            if tokens == 0:
                return None
            break
        tokens += 1
        name_end = probe
        index = probe
    if name_end < len(text) and "ぁ" <= text[name_end] <= "ん" and not _particle_at(text, name_end):
        return None
    count = sum(1 for char in text[name_start:name_end] if _is_name_char(char))
    if count < 1:
        return None
    return name_start, name_end


_PARTICLES = (
    "です", "ます", "した", "して", "から", "まで", "より", "こと", "もの", "ため", "さん",
    "は", "の", "に", "を", "が", "で", "と", "も", "へ", "や",
)


def _particle_at(text: str, index: int) -> bool:
    rest = text[index:]
    return any(rest.startswith(particle) for particle in _PARTICLES)


def _one_token(text: str) -> bool:
    if " " in text or "\u3000" in text:
        return False
    count = sum(1 for char in text if _is_name_char(char))
    return 1 <= count <= 3


def _leading_given(text: str) -> tuple[int, int] | None:
    index = 0
    noise = 0
    while index < len(text) and (text[index].isspace() or (noise < 2 and not _is_name_char(text[index]))):
        if not text[index].isspace():
            if text[index] in "、。，．）)":
                return None
            noise += 1
        index += 1
    if index >= len(text) or not _is_name_char(text[index]):
        return None
    end = index
    while end < len(text) and _is_name_char(text[end]):
        end += 1
    if not 1 <= end - index <= 4 or text[index:end] in {"以上", "記", "殿", "御中", "様"}:
        return None
    rest = text[end:].strip()
    if rest and rest[0] not in "…・、。）)" and any(_is_name_char(char) for char in rest):
        return None
    return index, end


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
        parts=parts_of(glyphs),
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
        checked=span.checked,
        parts=span.parts,
    )


def _hit_rects(hit: Hit) -> tuple[Rect, ...]:
    return hit.parts or (hit.bbox,)


def _wrap_candidate_spans(
    pages: tuple[PageIndex, ...] | list[PageIndex],
    person_re: re.Pattern[str],
    surnames: tuple[str, ...],
) -> list[Span]:
    """Patterns that start on one line and end on the next wrapped line."""
    spans: list[Span] = []
    for left, right in wrap_pairs(pages):
        spans.extend(_spans_across_wrap(left, right, person_re, surnames))
    return spans


def _spans_across_wrap(
    left: tuple[PageIndex, int, int],
    right: tuple[PageIndex, int, int],
    person_re: re.Pattern[str],
    surnames: tuple[str, ...],
) -> list[Span]:
    left_page, left_start, left_stop = left
    right_page, right_start, right_stop = right
    cut = max(left_start, left_stop - 40)
    stop = min(right_stop, right_start + 40)
    if cut >= left_stop or right_start >= stop:
        return []
    join = left_stop - cut
    text = left_page.strict[cut:left_stop] + right_page.strict[right_start:stop]
    folded = fold_digits(text)
    found: list[Span] = []

    def add(local_start: int, local_end: int, category: Category, pattern: re.Pattern[str], haystack: str) -> None:
        if local_end <= join or local_start >= join or local_end <= local_start:
            return
        # A finished token followed by 被告 or a particle is the next phrase.
        # 山田太 / 郎 and 株式会社サンプル / 商事 still cross.
        left = haystack[local_start:join]
        right = haystack[join:local_end]
        done = pattern.match(left)
        if done is not None and done.end() == len(left) and not _wrap_continues(right):
            return
        surface = text[local_start:local_end]
        if left_page.page_index == right_page.page_index and left_stop == right_start:
            pieces = ((left_page, cut + local_start, right_start + (local_end - join)),)
        else:
            pieces = (
                (left_page, cut + local_start, left_stop),
                (right_page, right_start, right_start + (local_end - join)),
            )
        for page, start, end in pieces:
            span = _piece_span(page, start, end, category, surface)
            if span is not None:
                found.append(span)

    for pattern, category in (
        (_EMAIL_RE, Category.EMAIL),
        (_ALNUM_RE, Category.ALNUM),
        *((pattern, Category.COMPANY) for pattern in _COMPANY_RES),
    ):
        for match in pattern.finditer(text):
            add(match.start(), match.end(), category, pattern, text)
    for match in _PHONE_RE.finditer(folded):
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) not in {10, 11} and not match.group(0).startswith("+81"):
            continue
        if match.group(0).startswith("+81") and not 10 <= len(digits) <= 13:
            continue
        add(match.start(), match.end(), Category.PHONE, _PHONE_RE, folded)
    for match in _POSTAL_RE.finditer(folded):
        add(match.start(), match.end(), Category.POSTAL, _POSTAL_RE, folded)
    for match in _ACCOUNT_RE.finditer(folded):
        add(match.start(1), match.end(1), Category.ACCOUNT, _ACCOUNT_RE, folded)
    for match in person_re.finditer(text):
        surface = match.group(0)
        given = surface
        for surname in surnames:
            if surface.startswith(surname):
                given = surface[len(surname) :]
                break
        if not given or given in _GIVEN_STOP or given[0] in "はをがにでとものへや":
            continue
        add(match.start(), match.end(), Category.PERSON, person_re, text)
    return found


def _wrap_continues(text: str) -> bool:
    if not text:
        return False
    return text[0] not in "はをがにでとものへや被原甲乙電連口管住第記以"


def _piece_span(
    page: PageIndex,
    start: int,
    end: int,
    category: Category,
    surface: str,
) -> Span | None:
    if start < 0 or end > len(page.glyphs) or start >= end:
        return None
    if len(strict_text(surface)) < 2 and end - start < 2 and category not in {Category.ALNUM}:
        return None
    glyphs = list(page.glyphs[start:end])
    if not glyphs:
        return None
    return Span(
        page_index=page.page_index,
        start=start,
        end=end,
        surface=surface,
        bbox=bbox_of(glyphs),
        line_ids=line_ids_of(glyphs),
        category=category,
        parts=parts_of(glyphs),
    )


def _covered(span: Span) -> set[int]:
    if span.indexes:
        return set(span.indexes)
    return set(range(span.start, span.end))


def _resolve_overlaps(spans: list[Span]) -> list[Span]:
    ordered = sorted(
        spans,
        key=lambda span: (-len(_covered(span)), _PRIORITY.get(span.category, 9), span.start),
    )
    kept: list[Span] = []
    for span in ordered:
        covered = _covered(span)
        if any(other.page_index == span.page_index and covered & _covered(other) for other in kept):
            continue
        kept.append(span)
    return kept
