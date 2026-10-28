"""The packaged version is 1.0.0 in every place the installer reads."""

import tomllib
from pathlib import Path

from ekisui import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_version_is_1_0_0() -> None:
    assert __version__ == "1.0.0"
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == "1.0.0"
    script = (ROOT / "installer" / "ekisui-pdf.iss").read_text(encoding="utf-8")
    assert '#define MyAppVersion "1.0.0"' in script
    assert "AppId={{E4B7A1C2-6D58-4F0E-9A31-7C2E8B6D4F10}" in script
    assert "OutputBaseFilename=ekisui-pdf-1.0.0-win64-setup" in script
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "ekisui-pdf-1.0.0-win64-setup" in workflow
    assert "0.1.0" not in workflow
    assert "0.1.0" not in (ROOT / "README.md").read_text(encoding="utf-8")
    assert "0.1.0" not in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
