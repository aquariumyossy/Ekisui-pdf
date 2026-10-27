from __future__ import annotations

from pathlib import Path

from ekisui_pdf.core.table import ReplacementTable, load_table, save_table


def test_same_term_keeps_one_pseudonym_and_roundtrips(tmp_path: Path):
    table = ReplacementTable()
    table.upsert("山田太郎", "被告A")
    table.upsert("山田太郎", "被告A")
    table.upsert("株式会社ＡＢＣ", "会社A")
    assert table.pseudonym_for("山田太郎") == "被告A"
    assert table.pseudonym_for_core("山田　太郎") == "被告A"
    assert len(table.entries) == 2

    json_path = tmp_path / "table.json"
    csv_path = tmp_path / "table.csv"
    save_table(json_path, table)
    save_table(csv_path, table)
    assert load_table(json_path).pseudonym_for("株式会社ＡＢＣ") == "会社A"
    assert load_table(csv_path).pseudonym_for("山田太郎") == "被告A"
    assert "ekisui-pdf-replacement-table" in json_path.read_text(encoding="utf-8")
