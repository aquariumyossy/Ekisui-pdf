from __future__ import annotations

from ekisui.domain.types import Document, Page, PageKind, Rect, TextLine, TextSource


def document_from_lines(pages: list[list[str]], gap: float = 28.0) -> Document:
    built: list[Page] = []
    for page_index, lines in enumerate(pages):
        text_lines: list[TextLine] = []
        y = 72.0
        for line_index, text in enumerate(lines):
            width = max(40.0, 14.0 * max(len(text), 1))
            text_lines.append(
                TextLine(
                    id=f"p{page_index}l{line_index}",
                    page_index=page_index,
                    text=text,
                    bbox=Rect(72.0, y, 72.0 + width, y + 16.0),
                    confidence=0.99,
                    source=TextSource.NATIVE,
                )
            )
            y += gap
        built.append(
            Page(
                index=page_index,
                width=600.0,
                height=840.0,
                kind=PageKind.NATIVE,
                lines=tuple(text_lines),
                source_index=page_index,
            )
        )
    return Document(source_path="memory.pdf", pages=tuple(built))
