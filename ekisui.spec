# -*- mode: python ; coding: utf-8 -*-
"""Windows bundle. Models are copied in; nothing is downloaded at runtime.

Qt comes from the PySide6 hooks for QtCore, QtGui, and QtWidgets, not from
collect_all("PySide6"). ekisui.bundle_filter then drops WebEngine, QML, extra
plugins, translations, PyMuPDF's layout package, and the other unused wheels
files. opengl32sw.dll stays so a machine without D3D11 can still draw.
"""

import sys
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(SPECPATH) / "src"))

from PyInstaller.utils.hooks import collect_all

from ekisui.bundle_filter import analysis_excludes, excluded_module, keep_toc_entry, shipped_name

datas = [
    ("models/ppocrv5", "models/ppocrv5"),
    ("src/ekisui/resources", "ekisui/resources"),
    ("LICENSE", "."),
    ("THIRD_PARTY_NOTICES.md", "."),
]
binaries = []
hidden = []
for package in ("onnxruntime", "pymupdf", "cv2", "numpy"):
    collected_datas, collected_binaries, collected_hidden = collect_all(package)
    datas += collected_datas
    binaries += collected_binaries
    hidden += collected_hidden


def _keep_pair(pair):
    source, dest = pair
    return keep_toc_entry((shipped_name(source, dest), source, ""))


datas = [pair for pair in datas if _keep_pair(pair)]
binaries = [pair for pair in binaries if _keep_pair(pair)]
hidden = [name for name in hidden if not excluded_module(name)]

_icon = Path(SPECPATH) / "assets" / "icon" / "ekisui.ico"
if _icon.is_file():
    datas.append((str(_icon), "assets/icon"))

if sys.platform == "win32":
    import PySide6

    qt_root = Path(PySide6.__file__).resolve().parent
    icu = qt_root / "resources" / "icudtl.dat"
    software_gl = qt_root / "opengl32sw.dll"
    if icu.is_file():
        datas.append((str(icu), "PySide6/resources"))
    if software_gl.is_file():
        binaries.append((str(software_gl), "PySide6"))

a = Analysis(
    ["src/ekisui/__main__.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden
    + [
        "ekisui.gui.window",
        "ekisui.pdf.ocr_engine",
        "ekisui.pdf.export",
        "ekisui.pdf.wordconvert",
        "ekisui.smoke",
    ]
    + (
        ["win32com", "win32com.client", "pythoncom", "pywintypes"]
        if sys.platform == "win32"
        else []
    ),
    excludes=analysis_excludes(),
    noarchive=False,
)


def _rewrite(toc):
    toc[:] = [entry for entry in toc if keep_toc_entry(entry)]


_rewrite(a.datas)
_rewrite(a.binaries)
_rewrite(a.pure)


def _toc_has(toc, filename):
    needle = filename.lower()
    for entry in toc:
        if str(entry[0]).replace("\\", "/").lower().endswith(needle):
            return True
    return False


if sys.platform == "win32":
    import PySide6

    qt_root = Path(PySide6.__file__).resolve().parent
    software_gl = qt_root / "opengl32sw.dll"
    icu = qt_root / "resources" / "icudtl.dat"
    if software_gl.is_file() and not _toc_has(a.binaries, "opengl32sw.dll"):
        a.binaries.append((str(PurePosixPath("PySide6") / "opengl32sw.dll"), str(software_gl), "BINARY"))
    if icu.is_file() and not _toc_has(a.datas, "icudtl.dat"):
        a.datas.append((str(PurePosixPath("PySide6/resources") / "icudtl.dat"), str(icu), "DATA"))

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ekisui-pdf",
    icon=str(_icon) if _icon.is_file() else None,
    console=False,
    # A crash dialog would block the installer job, which waits for this exe.
    disable_windowed_traceback=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="ekisui-pdf",
)
