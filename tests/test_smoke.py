from pathlib import Path

from ekisui.smoke import run


def test_smoke_covers_born_digital_and_fax_header_scan(tmp_path: Path) -> None:
    code = run(tmp_path / "out")
    log = (tmp_path / "out" / "smoke.log").read_text(encoding="utf-8")
    assert code == 0, log
    assert "NATIVE_EXTRACT" in log and "依頼者" in log and "山田太郎" in log
    assert "NATIVE_SEARCH" in log
    assert "FAX_KEPT" in log
    assert "SCAN_NAME_REMOVED" in log
    assert "LEFTOVER_CHECK passed" in log
    assert "QT_PNG 4x4" in log
    assert "SMOKE_OK" in log
