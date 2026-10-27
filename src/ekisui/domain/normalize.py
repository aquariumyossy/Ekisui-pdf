from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from ekisui.paths import resource_path


@dataclass(frozen=True)
class ConfusableTable:
    """Maps each confusable character to the first character of its group."""

    groups: tuple[str, ...]
    to_canonical: dict[str, str]

    def fold(self, ch: str) -> str:
        return self.to_canonical.get(ch, ch)

    def same(self, a: str, b: str) -> bool:
        return self.fold(a) == self.fold(b)


def load_confusables(path: Path | None = None) -> ConfusableTable:
    file = path or resource_path("confusables.json")
    raw = json.loads(file.read_text(encoding="utf-8"))
    groups = tuple(str(item) for item in raw["groups"])
    mapping: dict[str, str] = {}
    for group in groups:
        if not group:
            raise ValueError("空の読み違えグループがあります")
        canonical = group[0]
        for ch in group:
            if ch in mapping and mapping[ch] != canonical:
                raise ValueError(f"読み違え文字が複数の組に入っています: {ch}")
            mapping[ch] = canonical
    return ConfusableTable(groups=groups, to_canonical=mapping)


def strict_text(text: str) -> str:
    """NFKC, then drop spaces and line breaks. Hyphens stay."""
    normalized = unicodedata.normalize("NFKC", text)
    return "".join(ch for ch in normalized if not ch.isspace())


def loose_text(text: str, table: ConfusableTable) -> str:
    return "".join(table.fold(ch) for ch in strict_text(text))


def fold_digits(text: str) -> str:
    """Map OCR-confusable digits without touching kanji."""
    table = str.maketrans({
        "O": "0",
        "o": "0",
        "〇": "0",
        "○": "0",
        "Ⅰ": "1",
        "I": "1",
        "l": "1",
        "|": "1",
        "I": "1",
    })
    return text.translate(table)
