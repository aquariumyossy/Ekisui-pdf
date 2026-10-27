from __future__ import annotations

from pathlib import Path

import pymupdf

from ekisui_pdf.core.models import Leftover, VerifyReport


def _term_in_bytes(raw: bytes, term: str) -> bool:
    utf16 = term.encode("utf-16-be")
    encoded = (
        term.encode("utf-8"),
        utf16,
        b"\xfe\xff" + utf16,
        term.encode("utf-16-le"),
        utf16.hex().encode("ascii"),
        (b"\xfe\xff" + utf16).hex().encode("ascii"),
    )
    lowered = raw.lower()
    return any(blob and (blob in raw or blob.lower() in lowered) for blob in encoded)


def _decode_pdf_string(value: str) -> str:
    text = str(value).strip()
    if len(text) >= 2 and text[0] == "<" and text[-1] == ">":
        try:
            raw = bytes.fromhex(text[1:-1])
        except ValueError:
            return text
        if raw.startswith(b"\xfe\xff"):
            return raw[2:].decode("utf-16-be", errors="replace")
        for encoding in ("utf-8", "utf-16-be"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
    return text


def _page_text(page: pymupdf.Page) -> str:
    flags = pymupdf.TEXTFLAGS_TEXT & ~pymupdf.TEXT_MEDIABOX_CLIP
    clip = pymupdf.INFINITE_RECT()
    return page.get_text("text", clip=clip, flags=flags) or ""


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
        clip = pymupdf.INFINITE_RECT()
        for page_index, page in enumerate(document):
            text = _page_text(page)
            notes = []
            for annot in page.annots() or []:
                info = annot.info or {}
                notes.append(str(info.get("content") or ""))
                notes.append(str(info.get("title") or ""))
            note_text = "\n".join(notes)
            for term in unique:
                if term in text or page.search_for(term, clip=clip):
                    leftovers.append(Leftover(term=term, page_index=page_index, where="text"))
                if term in note_text:
                    leftovers.append(Leftover(term=term, page_index=page_index, where="annot"))
        outline = "\n".join(str(item[1]) for item in document.get_toc() if len(item) > 1)
        meta = document.metadata or {}
        meta_text = "\n".join(str(value) for value in meta.values())
        meta_text += "\n" + (document.get_xml_metadata() or "")
        labels = "\n".join(
            _decode_pdf_string(str(item.get("prefix", ""))) for item in (document.get_page_labels() or [])
        )
        for term in unique:
            if term in outline:
                leftovers.append(Leftover(term=term, page_index=-1, where="outline"))
            if term in meta_text:
                leftovers.append(Leftover(term=term, page_index=-1, where="metadata"))
            if term in labels:
                leftovers.append(Leftover(term=term, page_index=-1, where="label"))
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
