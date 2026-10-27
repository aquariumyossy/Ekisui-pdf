from __future__ import annotations

from pathlib import Path

import pymupdf

from ekisui_pdf.core.models import Leftover, VerifyReport


def _term_in_bytes(raw: bytes, term: str) -> bool:
    encoded = (
        term.encode("utf-8"),
        term.encode("utf-16-be"),
        b"\xfe\xff" + term.encode("utf-16-be"),
        term.encode("utf-16-le"),
    )
    return any(blob and blob in raw for blob in encoded)


def verify_pdf(path: Path, terms: list[str]) -> VerifyReport:
    """保存し直したPDFを開き、元の文字列がテキストに残っていないか調べる。"""
    unique: list[str] = []
    for term in terms:
        cleaned = term.strip()
        if cleaned and cleaned not in unique:
            unique.append(cleaned)

    leftovers: list[Leftover] = []
    document = pymupdf.open(path)
    try:
        for page_index, page in enumerate(document):
            text = page.get_text("text") or ""
            for term in unique:
                if term in text or page.search_for(term):
                    leftovers.append(Leftover(term=term, page_index=page_index, where="text"))
    finally:
        document.close()

    raw = Path(path).read_bytes()
    for term in unique:
        if len(term) < 2:
            continue
        if _term_in_bytes(raw, term):
            leftovers.append(Leftover(term=term, page_index=-1, where="bytes"))

    deduped: list[Leftover] = []
    seen: set[tuple[str, int, str]] = set()
    for leftover in leftovers:
        key = (leftover.term, leftover.page_index, leftover.where)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(leftover)
    return VerifyReport(
        passed=not deduped,
        leftovers=tuple(deduped),
        checked_terms=tuple(unique),
    )
