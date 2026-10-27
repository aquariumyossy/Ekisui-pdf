# -*- mode: python ; coding: utf-8 -*-
"""Windows bundle. Models are copied in; nothing is downloaded at runtime."""

from PyInstaller.utils.hooks import collect_all

datas = [
    ("models/ppocrv5", "models/ppocrv5"),
    ("src/ekisui/resources", "ekisui/resources"),
    ("LICENSE", "."),
    ("THIRD_PARTY_NOTICES.md", "."),
]
binaries = []
hidden = []
for package in ("PySide6", "onnxruntime", "pymupdf", "cv2", "numpy"):
    collected_datas, collected_binaries, collected_hidden = collect_all(package)
    datas += collected_datas
    binaries += collected_binaries
    hidden += collected_hidden

a = Analysis(
    ["src/ekisui/__main__.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden + ["ekisui.gui.window", "ekisui.pdf.ocr_engine", "ekisui.pdf.export"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ekisui-pdf",
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="ekisui-pdf",
)
