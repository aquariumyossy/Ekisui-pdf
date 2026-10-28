from __future__ import annotations

import csv
import io

from ekisui.domain.normalize import strict_text
from ekisui.domain.session import TermGroup
from ekisui.domain.types import CATEGORY_LABEL, Action


def _cell(value: str) -> str:
    if value[:1] in "=+-@":
        return "'" + value
    return value


def groups_to_csv(groups: list[TermGroup]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["種類", "語句", "呼び名", "表記ゆれ"])
    for group in groups:
        if group.action != Action.REPLACE:
            continue
        variants: list[str] = []
        seen = {strict_text(group.canonical)}
        for tracked in group.hits:
            key = strict_text(tracked.hit.surface)
            if key in seen:
                continue
            seen.add(key)
            variants.append(tracked.hit.surface)
        writer.writerow(
            [
                _cell(CATEGORY_LABEL[group.category]),
                _cell(group.canonical),
                _cell(group.pseudonym or ""),
                _cell("|".join(variants)),
            ]
        )
    return buffer.getvalue()


def csv_to_rows(text: str) -> list[tuple[str, str, str, str]]:
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return []
    body = rows[1:] if rows[0][:1] == ["種類"] else rows
    parsed = []
    for row in body:
        if not row or not any(cell.strip() for cell in row):
            continue
        padded = (row + ["", "", "", ""])[:4]
        parsed.append(tuple(cell.strip() for cell in padded))  # type: ignore[arg-type]
    return parsed  # type: ignore[return-value]
