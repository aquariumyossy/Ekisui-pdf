from __future__ import annotations

from ekisui_pdf.core.errors import EkisuiError, PseudonymMissing
from ekisui_pdf.core.geometry import span_rect, union_rect
from ekisui_pdf.core.variants import core_key
from ekisui_pdf.core.models import (
    Action,
    OcrLine,
    PagePlan,
    Rect,
    SaveOptions,
    Selection,
    TextInsert,
)
from ekisui_pdf.core.table import ReplacementTable


def resolve_pseudonym(selection: Selection, table: ReplacementTable) -> str:
    typed = selection.pseudonym.strip()
    if typed:
        return typed
    exact = table.pseudonym_for(selection.matched_text)
    if exact:
        return exact
    return table.pseudonym_for_core(selection.matched_text) or ""


def _base_rect(selection: Selection, lines: list[OcrLine]) -> Rect:
    rect = selection.rect.normalized()
    if selection.line_id and selection.char_start >= 0 and selection.char_end > selection.char_start:
        for line in lines:
            if line.page_index == selection.page_index and line.line_id == selection.line_id:
                return union_rect(rect, span_rect(line, selection.char_start, selection.char_end))
    return rect


def consistency_problems(selections: list[Selection], table: ReplacementTable) -> list[str]:
    """同じ語に別の仮名が付いていないか。表と選択の食い違いも含む。"""
    problems: list[str] = []
    by_key: dict[str, set[str]] = {}
    for selection in selections:
        if selection.action != Action.PSEUDONYM:
            continue
        typed = selection.pseudonym.strip()
        exact = (table.pseudonym_for(selection.matched_text) or "").strip()
        if typed and exact and typed != exact:
            problems.append(f"{selection.matched_text}: 選択は「{typed}」、表は「{exact}」")
        name = resolve_pseudonym(selection, table)
        key = core_key(selection.matched_text) or selection.matched_text.strip()
        if key and name:
            by_key.setdefault(key, set()).add(name)
    for key, names in by_key.items():
        if len(names) > 1:
            problems.append(key + ": " + " / ".join(sorted(names)))
    return problems


def forbidden_terms(selections: list[Selection]) -> list[str]:
    terms: list[str] = []
    for selection in selections:
        text = selection.matched_text.strip()
        if text and text not in terms:
            terms.append(text)
    return terms


def plan_pages(
    lines: list[OcrLine],
    selections: list[Selection],
    table: ReplacementTable,
    options: SaveOptions,
    page_sizes: list[tuple[float, float]],
) -> list[PagePlan]:
    missing = [
        selection.matched_text or "(文字なし)"
        for selection in selections
        if selection.action == Action.PSEUDONYM and not resolve_pseudonym(selection, table)
    ]
    if missing:
        raise PseudonymMissing(missing)

    same_as_original = [
        selection.matched_text
        for selection in selections
        if selection.action == Action.PSEUDONYM
        and resolve_pseudonym(selection, table) == selection.matched_text.strip()
    ]
    if same_as_original:
        raise EkisuiError("仮名が元の文字列と同じです: " + "、".join(same_as_original))
    conflicts = consistency_problems(selections, table)
    if conflicts:
        raise EkisuiError("同じ語に別の仮名があります: " + "、".join(conflicts[:6]))

    applied_width: float | None = None
    if options.fixed_width and selections:
        applied_width = max(options.fixed_width_pt, *(selection.rect.width for selection in selections))
        applied_width = max(applied_width, *(_base_rect(selection, lines).width for selection in selections))

    plans: list[PagePlan] = []
    for page_index, (page_width, page_height) in enumerate(page_sizes):
        bounds = Rect(0, 0, page_width, page_height)
        page_selections = [selection for selection in selections if selection.page_index == page_index]
        redactions: list[Rect] = []
        for selection in page_selections:
            rect = _base_rect(selection, lines)
            if applied_width is not None:
                rect = rect.with_width(applied_width, page_width)
            rect = rect.clamp(bounds)
            redactions.append(rect)

        inserts: list[TextInsert] = []
        for line in lines:
            if line.page_index != page_index or not line.text:
                continue
            covered = [False] * len(line.text)
            if line.line_id:
                for selection in page_selections:
                    if selection.line_id == line.line_id and selection.char_start >= 0:
                        start = max(0, selection.char_start)
                        end = min(len(line.text), selection.char_end)
                        for index in range(start, end):
                            covered[index] = True
            for index in range(len(line.text)):
                if covered[index]:
                    continue
                cell = span_rect(line, index, index + 1)
                if any(cell.intersects(rect) for rect in redactions):
                    covered[index] = True
            cursor = 0
            while cursor < len(line.text):
                if covered[cursor]:
                    cursor += 1
                    continue
                end = cursor
                while end < len(line.text) and not covered[end]:
                    end += 1
                fragment = line.text[cursor:end]
                if fragment.strip():
                    inserts.append(
                        TextInsert(
                            rect=span_rect(line, cursor, end),
                            text=fragment,
                            visible=False,
                        )
                    )
                cursor = end

        for selection, rect in zip(page_selections, redactions, strict=True):
            if selection.action != Action.PSEUDONYM:
                continue
            pseudonym = resolve_pseudonym(selection, table)
            inserts.append(TextInsert(rect=rect, text=pseudonym, visible=True))

        plans.append(PagePlan(redactions=tuple(redactions), inserts=tuple(inserts)))
    return plans


def applied_box_width(plans: list[PagePlan], options: SaveOptions) -> float | None:
    if not options.fixed_width:
        return None
    widths = [rect.width for plan in plans for rect in plan.redactions]
    if not widths:
        return None
    return max(widths)
