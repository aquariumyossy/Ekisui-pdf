from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from ekisui.domain.address import address_key
from ekisui.domain.adjust import bbox_of_range, bind_span, move_edge, snap_boundary
from ekisui.domain.candidates import AutoGroup, suggest
from ekisui.domain.index import _cells, build_document_index
from ekisui.domain.match import search_pages, text_in_rect
from ekisui.domain.normalize import ConfusableTable, load_confusables, loose_text, strict_text
from ekisui.domain.pseudonym import address_name, company_name, person_name, phrase_name
from ekisui.errors import EkisuiError
from ekisui.domain.types import (
    Action,
    Category,
    DEFAULT_ACTION,
    Document,
    Hit,
    MatchKind,
    Page,
    PageIndex,
    Rect,
    Settings,
    TextLine,
    TextSource,
)


@dataclass
class TrackedHit:
    id: str
    hit: Hit
    included: bool
    adjusted: bool = False
    original_hit: Hit | None = None
    line_id: str = ""
    start: int = -1
    end: int = -1
    original_start: int = -1
    original_end: int = -1
    needs_review: bool = False
    ocr_changed: bool = False
    # Pre-correction OCR text and the corrected reading. Leftover check searches both.
    prior_surface: str = ""
    corrected_surface: str = ""


@dataclass
class TermGroup:
    id: str
    canonical: str
    category: Category
    action: Action
    pseudonym: str | None
    hits: list[TrackedHit] = field(default_factory=list)
    origin: str = "auto"

    def included_hits(self) -> list[TrackedHit]:
        return [hit for hit in self.hits if hit.included]


class Session:
    """Single writer for the open document, the selection list, and pseudonyms."""

    def __init__(
        self,
        document: Document,
        settings: Settings | None = None,
        table: ConfusableTable | None = None,
    ) -> None:
        self.document = document
        self.settings = settings or Settings()
        self.table = table or load_confusables()
        self.groups: list[TermGroup] = []
        self._index: tuple[PageIndex, ...] | None = None
        self._seq = 0
        self.confirmed = False
        # Hits whose pixels and text have already been burned into the page.
        # They are not editable and are not cleared when a new range is added.
        self.committed: list[TermGroup] = []
        # Rectangles actually burned, so the log does not recompute them later.
        self.burned_boxes: list = []

    def index(self) -> tuple[PageIndex, ...]:
        if self._index is None:
            self._index = build_document_index(self.document, self.table)
        return self._index

    def set_settings(self, settings: Settings) -> None:
        self.settings = settings

    def suggest(self) -> None:
        autos = suggest(self.index(), self.settings, self.table)
        plain = [auto for auto in autos if auto.category != Category.ADDRESS]
        addresses = sorted(
            (auto for auto in autos if auto.category == Category.ADDRESS),
            key=lambda auto: (auto.hits[0].page_index, auto.hits[0].bbox.y0, auto.hits[0].bbox.x0),
        )
        existing = {_group_key(group.canonical, group.category) for group in self.groups}
        for auto in [*plain, *addresses]:
            key = _group_key(auto.canonical, auto.category)
            if key in existing:
                self._merge_hits(auto)
                continue
            self._add_group(
                auto.category, auto.canonical, auto.hits, origin="auto", action=auto.action
            )
            existing.add(key)
        self.confirmed = False

    def add_phrase(self, phrase: str) -> TermGroup | None:
        text = phrase.strip()
        if len(strict_text(text)) < 2:
            return None
        hits = search_pages(self.index(), text, self.settings, self.table)
        if not hits:
            return None
        category = _category_of_phrase(text)
        group = self._group_for_canonical(text, category)
        if group is None:
            group = self._add_group(category, text, hits, origin="search", include_fuzzy=False)
        else:
            self._append_hits(group, hits, include_fuzzy=False)
        self.confirmed = False
        return group

    def add_region(self, page_index: int, rect: Rect) -> TermGroup | None:
        page = self.index()[page_index]
        text = text_in_rect(page, rect).strip()
        if len(strict_text(text)) < 2:
            hit = Hit(
                page_index,
                "（範囲）",
                rect,
                MatchKind.EXACT,
                1.0,
                "ドラッグした範囲",
                (),
                False,
            )
            group = self._add_group(Category.REGION, "（範囲）", [hit], origin="region")
            self.confirmed = False
            return group
        hits = search_pages(self.index(), text, self.settings, self.table)
        if not hits:
            hits = []
        group = self._group_for_canonical(text, Category.REGION)
        if group is None:
            group = self._add_group(Category.REGION, text, hits, origin="region", include_fuzzy=False)
        else:
            self._append_hits(group, hits, include_fuzzy=False)
        self.confirmed = False
        return group

    def page_is_confirmed(self, page_index: int) -> bool:
        """A page whose pixels were burned can no longer be corrected."""
        for group in self.committed:
            for tracked in group.hits:
                if tracked.hit.page_index == page_index:
                    return True
        return False

    def unreviewed_ocr(self) -> bool:
        return any(tracked.needs_review for group in self.groups for tracked in group.hits)

    def acknowledge_review(self, hit_id: str) -> None:
        self._hit(hit_id).needs_review = False

    def correct_line(self, line_id: str, new_text: str) -> None:
        line = self._line(line_id)
        if self.page_is_confirmed(line.page_index):
            raise EkisuiError("このページは確定済みです。画像と文字を消したので、OCR修正はできません。")
        old_text = line.text
        pages: list[Page] = []
        for page in self.document.pages:
            lines: list[TextLine] = []
            for item in page.lines:
                if item.id == line_id:
                    lines.append(replace(item, text=new_text, confidence=1.0, source=TextSource.CORRECTED))
                else:
                    lines.append(item)
            pages.append(replace(page, lines=tuple(lines)))
        self.document = replace(self.document, pages=tuple(pages))
        self._index = None
        if strict_text(old_text) != strict_text(new_text):
            self._relink_ocr_line(line_id, old_text)
        self.confirmed = False

    def _relink_ocr_line(self, line_id: str, old_text: str) -> None:
        """Keep the pre-correction box, and add unchecked hits for the new reading."""
        line = self._line(line_id)
        kept = self._hits_touching(line_id, line.bbox)
        for tracked in kept:
            tracked.needs_review = True
            tracked.ocr_changed = True
            if not tracked.prior_surface:
                tracked.prior_surface = tracked.hit.surface or old_text
        known = {tracked.id for group in self.groups for tracked in group.hits}
        for auto in self._suggest_line(line):
            fresh = [hit for hit in auto.hits if line_id in hit.line_ids]
            if not fresh:
                continue
            group = self._group_for_normalized(auto.canonical, auto.category)
            flagged = tuple(replace(hit, checked=False) for hit in fresh)
            if group is None:
                self._add_group(
                    auto.category,
                    auto.canonical,
                    flagged,
                    origin="auto",
                    include_fuzzy=False,
                    action=auto.action,
                    overlap="surface",
                )
            else:
                self._append_hits(group, flagged, include_fuzzy=False, included=False, overlap="surface")
        self.groups = [group for group in self.groups if group.hits]
        original = next((tracked.prior_surface or tracked.hit.surface for tracked in kept if tracked.hit.surface), "")
        new_surfaces = []
        for group in self.groups:
            for tracked in group.hits:
                if tracked.id in known or line_id not in tracked.hit.line_ids:
                    continue
                tracked.included = False
                tracked.needs_review = True
                tracked.ocr_changed = True
                tracked.prior_surface = original or tracked.hit.surface
                tracked.corrected_surface = tracked.hit.surface
                new_surfaces.append(tracked.hit.surface)
        for tracked in kept:
            if new_surfaces:
                tracked.corrected_surface = new_surfaces[-1]

    def _suggest_line(self, line: TextLine):
        from ekisui.domain.candidates import suggest
        from ekisui.domain.index import build_page_index

        page = self.document.pages[line.page_index]
        solo = replace(page, lines=(line,))
        return suggest((build_page_index(solo, self.table),), self.settings, self.table)

    def _hits_touching(self, line_id: str, bbox: Rect) -> list[TrackedHit]:
        page_index = self._line(line_id).page_index
        found: list[TrackedHit] = []
        for group in self.groups:
            for tracked in group.hits:
                if line_id in tracked.hit.line_ids or tracked.line_id == line_id:
                    found.append(tracked)
                    continue
                center = tracked.hit.bbox.center()
                if tracked.hit.page_index == page_index and bbox.contains(*center):
                    found.append(tracked)
        return found

    def _group_for_normalized(self, text: str, category: Category) -> TermGroup | None:
        group = self._group_for_canonical(text, category)
        if group is not None:
            return group
        folded = loose_text(text, self.table)
        if category == Category.ADDRESS:
            return None
        for item in self.groups:
            if item.category == category and loose_text(item.canonical, self.table) == folded and folded:
                return item
        return None

    def rescan(self) -> None:
        manual = [group for group in self.groups if group.origin in {"search", "region", "table"}]
        sticky = [
            (group, [hit for hit in group.hits if hit.ocr_changed])
            for group in self.groups
            if any(hit.ocr_changed for hit in group.hits)
        ]
        self.groups = []
        self._index = None
        self.suggest()
        for group in manual:
            if group.origin == "region" and group.canonical == "（範囲）":
                revived = self._add_group(
                    group.category,
                    group.canonical,
                    [],
                    origin=group.origin,
                    action=group.action,
                    pseudonym=group.pseudonym,
                )
                for tracked in group.hits:
                    self._append_hits(revived, [tracked.hit], include_fuzzy=False, included=tracked.included)
                continue
            hits = search_pages(self.index(), group.canonical, self.settings, self.table)
            revived = self._add_group(
                group.category,
                group.canonical,
                hits,
                origin=group.origin,
                include_fuzzy=True,
                action=group.action,
                pseudonym=group.pseudonym,
            )
            for old in group.hits:
                if strict_text(old.hit.surface) == strict_text(group.canonical):
                    continue
                extra = search_pages(self.index(), old.hit.surface, self.settings, self.table)
                self._append_hits(revived, extra, include_fuzzy=True, included=old.included)
        for group, hits in sticky:
            target = self._group_for_normalized(group.canonical, group.category)
            if target is None:
                target = self._add_group(
                    group.category,
                    group.canonical,
                    [],
                    origin=group.origin,
                    action=group.action,
                    pseudonym=group.pseudonym,
                    overlap="surface",
                )
            for tracked in hits:
                if _occupied(self.groups, target, tracked.hit, "surface"):
                    continue
                target.hits.append(tracked)
        self.groups = [group for group in self.groups if group.hits]
        self.confirmed = False

    def rebind_after_ocr(self, previous: Document) -> None:
        """Move selections onto a document whose scanned pages were just read.

        Pages that were not rebuilt keep their boxes, including a dragged
        rectangle on a text page. Text on a rebuilt page is searched again.
        A dragged rectangle on a rebuilt page is moved with the image.
        """
        from ekisui.pdf.deskew import map_page_rect

        old_pages = {page.index: page for page in previous.pages}
        new_pages = {page.index: page for page in self.document.pages}
        changed = {
            index
            for index, page in new_pages.items()
            if _page_was_rebuilt(old_pages.get(index), page)
        }
        self._index = None
        if not changed:
            return
        # OCR rebuilds pages. It does not extract masking candidates.
        # マスキング実行 calls rescan() afterwards when the user asked for both.
        pending: list[tuple[TermGroup, list[TrackedHit]]] = []
        kept: list[TermGroup] = []
        for group in self.groups:
            stale = [hit for hit in group.hits if hit.hit.page_index in changed]
            group.hits = [hit for hit in group.hits if hit.hit.page_index not in changed]
            if group.origin == "auto":
                if group.hits:
                    kept.append(group)
                continue
            kept.append(group)
            if stale:
                pending.append((group, stale))
        self.groups = kept
        for group, stale in pending:
            if group.origin == "region":
                for tracked in stale:
                    old_page = old_pages.get(tracked.hit.page_index)
                    new_page = new_pages.get(tracked.hit.page_index)
                    if old_page is None or new_page is None:
                        continue
                    mapped = map_page_rect(old_page, new_page, tracked.hit.bbox)
                    mapped_parts = tuple(
                        map_page_rect(old_page, new_page, part) for part in tracked.hit.parts
                    )
                    self._append_hits(
                        group,
                        [replace(tracked.hit, bbox=mapped, line_ids=(), parts=mapped_parts)],
                        include_fuzzy=False,
                        included=tracked.included,
                    )
            if strict_text(group.canonical) and group.canonical != "（範囲）":
                found = search_pages(self.index(), group.canonical, self.settings, self.table)
                self._append_hits(group, found, include_fuzzy=group.origin != "region")
                for tracked in stale:
                    if strict_text(tracked.hit.surface) == strict_text(group.canonical):
                        continue
                    extra = search_pages(self.index(), tracked.hit.surface, self.settings, self.table)
                    self._append_hits(group, extra, include_fuzzy=True, included=tracked.included)
        self.groups = [group for group in self.groups if group.hits]
        self.confirmed = False

    def adjust_hit(self, hit_id: str, edge: str, page_x: float) -> None:
        tracked = self._hit(hit_id)
        # A name split across lines is one box. Snapping it onto the first line
        # would leave the rest of the name in the saved PDF.
        if len(tracked.hit.line_ids) > 1:
            return
        self._ensure_span(tracked)
        if tracked.start < 0 or not tracked.line_id:
            return
        line = self._line(tracked.line_id)
        cells = _cells(line)
        start, end = move_edge(
            tracked.start,
            tracked.end,
            edge,
            snap_boundary(cells, page_x),
            len(line.text),
        )
        self._apply_span(tracked, line, cells, start, end)

    def restore_hit(self, hit_id: str) -> None:
        tracked = self._hit(hit_id)
        if tracked.original_hit is None and not tracked.adjusted:
            return
        if tracked.original_hit is not None:
            tracked.hit = tracked.original_hit
        tracked.start = tracked.original_start
        tracked.end = tracked.original_end
        tracked.adjusted = False
        tracked.original_hit = None
        self.confirmed = False

    def _ensure_span(self, tracked: TrackedHit) -> None:
        if tracked.start >= 0 and tracked.line_id:
            return
        if not tracked.hit.line_ids:
            return
        line = self._line(tracked.hit.line_ids[0])
        start, end = bind_span(line, tracked.hit.bbox)
        if end <= start:
            return
        tracked.line_id = line.id
        tracked.start = start
        tracked.end = end
        tracked.original_start = start
        tracked.original_end = end

    def _apply_span(self, tracked: TrackedHit, line: TextLine, cells: list[Rect], start: int, end: int) -> None:
        if end <= start:
            return
        tracked.start = start
        tracked.end = end
        if start == tracked.original_start and end == tracked.original_end:
            if tracked.original_hit is not None:
                tracked.hit = tracked.original_hit
            tracked.adjusted = False
            tracked.original_hit = None
        else:
            if tracked.original_hit is None:
                tracked.original_hit = tracked.hit
            tracked.adjusted = True
            exact = cells[start]
            for cell in cells[start + 1 : end]:
                exact = exact.union(cell)
            tracked.hit = replace(
                tracked.hit,
                surface=line.text[start:end],
                bbox=bbox_of_range(cells, start, end),
                line_ids=(line.id,),
                parts=(exact,),
            )
        self.confirmed = False

    def _line(self, line_id: str) -> TextLine:
        for page in self.document.pages:
            for line in page.lines:
                if line.id == line_id:
                    return line
        raise KeyError(line_id)

    def set_included(self, hit_id: str, included: bool) -> None:
        hit = self._hit(hit_id)
        hit.included = included
        hit.needs_review = False
        self.confirmed = False

    def set_included_many(self, hit_ids: list[str], included: bool) -> None:
        for hit_id in hit_ids:
            self._hit(hit_id).included = included
        self.confirmed = False

    def set_action(self, group_id: str, action: Action) -> None:
        group = self._group(group_id)
        group.action = action
        if action == Action.REPLACE and not group.pseudonym:
            group.pseudonym = self._allocate(group.category)
        self.confirmed = False

    def set_action_many(self, group_ids: list[str], action: Action) -> None:
        for group_id in group_ids:
            self.set_action(group_id, action)

    def set_pseudonym(self, group_id: str, pseudonym: str) -> None:
        self._group(group_id).pseudonym = pseudonym.strip()
        self.confirmed = False

    def add_variant(self, group_id: str, text: str) -> int:
        group = self._group(group_id)
        hits = search_pages(self.index(), text.strip(), self.settings, self.table)
        before = len(group.hits)
        self._append_hits(group, hits, include_fuzzy=True, included=True)
        self.confirmed = False
        return len(group.hits) - before

    def remove_hit(self, hit_id: str) -> None:
        for group in self.groups:
            group.hits = [hit for hit in group.hits if hit.id != hit_id]
        self.groups = [group for group in self.groups if group.hits]
        self.confirmed = False

    def exclude_unchecked(self) -> None:
        for group in self.groups:
            group.hits = [hit for hit in group.hits if hit.included or hit.needs_review]
        self.groups = [group for group in self.groups if group.hits]
        self.confirmed = False

    def renumber(self) -> None:
        for group in self.groups:
            if group.action != Action.REPLACE:
                continue
            group.pseudonym = self._pinned_pseudonym(group.canonical, group.category)
        for group in self.groups:
            if group.action != Action.REPLACE or group.pseudonym:
                continue
            group.pseudonym = self._allocate(group.category)
        self.confirmed = False

    def commit_redactions(self, work_dir: str | Path, align_box_width: bool) -> None:
        """Burn every checked hit into the working PDF. This cannot be undone."""
        if self.unreviewed_ocr():
            raise EkisuiError("OCR修正で変わった候補が未確認です。一覧の「要確認」を確認してから確定してください。")
        pending: list[TermGroup] = []
        for group in self.groups:
            included = [hit for hit in group.hits if hit.included]
            if included:
                pending.append(replace(group, hits=list(included)))
        before = {line.id: line.text for page in self.document.pages for line in page.lines}
        if pending:
            from ekisui.pdf.export import bake_redactions

            self.document, boxes = bake_redactions(
                self.document,
                pending,
                self.settings,
                work_dir,
                align_box_width,
            )
            self.burned_boxes.extend(boxes)
            self._index = None
        after = {line.id: line.text for page in self.document.pages for line in page.lines}
        changed = {line_id for line_id, text in before.items() if after.get(line_id) != text}
        for group in self.groups:
            for tracked in group.hits:
                ids = {tracked.line_id, *tracked.hit.line_ids}
                if ids & changed:
                    tracked.line_id = ""
                    tracked.start = -1
                    tracked.end = -1
                    tracked.original_start = -1
                    tracked.original_end = -1
        for group in self.groups:
            group.hits = [hit for hit in group.hits if not hit.included]
        self.groups = [group for group in self.groups if group.hits]
        self.committed.extend(pending)
        self.confirmed = True

    def _pinned_pseudonym(self, canonical: str, category: Category) -> str | None:
        key = _group_key(canonical, category)
        for group in self.committed:
            if group.category == category and _group_key(group.canonical, category) == key and group.pseudonym:
                return group.pseudonym
        return None

    def import_rows(self, rows: list[tuple[str, str, str, str]]) -> None:
        """Rows are (category label, canonical, pseudonym, variants joined by |)."""
        from ekisui.domain.types import CATEGORY_LABEL

        reverse = {label: category for category, label in CATEGORY_LABEL.items()}
        for label, canonical, pseudonym, variants in rows:
            category = reverse.get(label, Category.PHRASE)
            hits = search_pages(self.index(), canonical, self.settings, self.table)
            group = self._group_for_canonical(canonical, category)
            if group is None:
                group = self._add_group(
                    category,
                    canonical,
                    hits,
                    origin="table",
                    include_fuzzy=True,
                    action=Action.REPLACE,
                    pseudonym=pseudonym or None,
                )
            else:
                self._append_hits(group, hits, include_fuzzy=True)
                group.action = Action.REPLACE
                if pseudonym:
                    group.pseudonym = pseudonym
            for variant in [part for part in variants.split("|") if part]:
                self.add_variant(group.id, variant)
        self.confirmed = False

    def _add_group(
        self,
        category: Category,
        canonical: str,
        hits: list[Hit] | tuple[Hit, ...],
        origin: str,
        include_fuzzy: bool = False,
        action: Action | None = None,
        pseudonym: str | None = None,
        overlap: str = "place",
    ) -> TermGroup:
        chosen = action or DEFAULT_ACTION[category]
        name = pseudonym or (self._pinned_pseudonym(canonical, category) if chosen == Action.REPLACE else None)
        if chosen == Action.REPLACE and not name:
            name = self._allocate(category)
        group = TermGroup(
            id=self._next("g"),
            canonical=canonical,
            category=category,
            action=chosen,
            pseudonym=name,
            origin=origin,
        )
        self.groups.append(group)
        self._append_hits(
            group,
            hits,
            include_fuzzy=include_fuzzy or origin != "auto",
            overlap=overlap,
        )
        return group

    def _append_hits(
        self,
        group: TermGroup,
        hits: list[Hit] | tuple[Hit, ...],
        include_fuzzy: bool,
        included: bool | None = None,
        overlap: str = "place",
    ) -> None:
        for hit in hits:
            if _occupied(self.groups, group, hit, overlap):
                continue
            flag = included
            if flag is None:
                flag = _default_included(group.category, hit, include_fuzzy)
            group.hits.append(TrackedHit(self._next("h"), hit, flag))

    def _merge_hits(self, auto: AutoGroup) -> None:
        group = self._group_for_canonical(auto.canonical, auto.category)
        if group is None:
            return
        self._append_hits(group, auto.hits, include_fuzzy=False)

    def _group_for_canonical(self, text: str, category: Category) -> TermGroup | None:
        key = _group_key(text, category)
        for group in self.groups:
            if group.category == category and _group_key(group.canonical, category) == key:
                return group
        return None

    def _allocate(self, category: Category) -> str:
        used = {group.pseudonym for group in (*self.groups, *self.committed) if group.pseudonym}
        index = 0
        while True:
            if category == Category.COMPANY:
                name = company_name(index)
            elif category == Category.PERSON:
                name = person_name(index)
            elif category == Category.ADDRESS:
                name = address_name(index)
            else:
                name = phrase_name(index)
            if name not in used:
                return name
            index += 1

    def _group(self, group_id: str) -> TermGroup:
        for group in self.groups:
            if group.id == group_id:
                return group
        raise KeyError(group_id)

    def _hit(self, hit_id: str) -> TrackedHit:
        for group in self.groups:
            for hit in group.hits:
                if hit.id == hit_id:
                    return hit
        raise KeyError(hit_id)

    def _next(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}{self._seq}"


def _category_of_phrase(text: str) -> Category:
    from ekisui.domain.candidates import _COMPANY_RES, load_surnames, _person_re

    folded = strict_text(text)
    for pattern in _COMPANY_RES:
        match = pattern.fullmatch(folded)
        if match:
            return Category.COMPANY
    person = _person_re(load_surnames())
    if person.fullmatch(folded):
        return Category.PERSON
    return Category.PHRASE


def _group_key(text: str, category: Category) -> str:
    if category == Category.ADDRESS:
        return address_key(text)
    return strict_text(text)


def _default_included(category: Category, hit: Hit, include_fuzzy: bool) -> bool:
    if not hit.checked:
        return False
    if category == Category.ALNUM:
        return False
    if hit.kind.name == "EXACT" or hit.ocr_like:
        return True
    return include_fuzzy


def _occupied(groups: list[TermGroup], group: TermGroup, hit: Hit, overlap: str) -> bool:
    pool = [existing for existing in group.hits]
    pool.extend(existing for other in groups if other is not group for existing in other.hits)
    for existing in pool:
        if not _same_place(existing.hit, hit):
            continue
        if overlap == "surface" and strict_text(existing.hit.surface) != strict_text(hit.surface):
            continue
        return True
    return False


def _same_place(left: Hit, right: Hit) -> bool:
    if left.page_index != right.page_index:
        return False
    for one in left.parts or (left.bbox,):
        for other in right.parts or (right.bbox,):
            if one.intersects(other) and abs(one.x0 - other.x0) < 1.5 and abs(one.y0 - other.y0) < 1.5:
                return True
    return False


def _page_was_rebuilt(old: Page | None, new: Page) -> bool:
    if old is None:
        return True
    if (new.image_path or None) != (old.image_path or None):
        return True
    return abs(new.width - old.width) > 0.5 or abs(new.height - old.height) > 0.5
