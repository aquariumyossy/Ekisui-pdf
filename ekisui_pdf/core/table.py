from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from ekisui_pdf.core.models import ReplacementEntry
from ekisui_pdf.core.variants import core_key

TABLE_KIND = "ekisui-pdf-replacement-table"


class ReplacementTable:
    def __init__(self, entries: list[ReplacementEntry] | None = None):
        self.entries: list[ReplacementEntry] = list(entries or [])

    def pseudonym_for(self, term: str) -> str | None:
        for entry in self.entries:
            if entry.term == term and entry.pseudonym.strip():
                return entry.pseudonym.strip()
        return None

    def pseudonym_for_core(self, term: str) -> str | None:
        key = core_key(term)
        if not key:
            return None
        found = [
            entry.pseudonym.strip()
            for entry in self.entries
            if entry.pseudonym.strip() and core_key(entry.term) == key
        ]
        if not found:
            return None
        return found[0]

    def conflicting_cores(self) -> list[str]:
        by_key: dict[str, set[str]] = {}
        for entry in self.entries:
            pseudonym = entry.pseudonym.strip()
            key = core_key(entry.term)
            if not pseudonym or not key:
                continue
            by_key.setdefault(key, set()).add(pseudonym)
        return [key for key, names in by_key.items() if len(names) > 1]

    def upsert(self, term: str, pseudonym: str) -> None:
        for entry in self.entries:
            if entry.term == term:
                entry.pseudonym = pseudonym
                return
        self.entries.append(ReplacementEntry(term=term, pseudonym=pseudonym))

    def remove_at(self, index: int) -> None:
        if 0 <= index < len(self.entries):
            del self.entries[index]

    def to_json(self) -> str:
        payload = {
            "kind": TABLE_KIND,
            "version": 1,
            "entries": [
                {"term": entry.term, "pseudonym": entry.pseudonym} for entry in self.entries
            ],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def to_csv(self) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["term", "pseudonym"])
        for entry in self.entries:
            writer.writerow([entry.term, entry.pseudonym])
        return buffer.getvalue()


def save_table(path: Path, table: ReplacementTable) -> None:
    path = Path(path)
    if path.suffix.lower() == ".csv":
        path.write_text(table.to_csv(), encoding="utf-8-sig")
        return
    path.write_text(table.to_json() + "\n", encoding="utf-8")


def load_table(path: Path) -> ReplacementTable:
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".csv":
        reader = csv.DictReader(io.StringIO(text))
        entries = [
            ReplacementEntry(term=row.get("term", ""), pseudonym=row.get("pseudonym", ""))
            for row in reader
            if (row.get("term") or "").strip()
        ]
        return ReplacementTable(entries)
    payload = json.loads(text)
    entries = [
        ReplacementEntry(term=item.get("term", ""), pseudonym=item.get("pseudonym", ""))
        for item in payload.get("entries", [])
        if str(item.get("term", "")).strip()
    ]
    return ReplacementTable(entries)
