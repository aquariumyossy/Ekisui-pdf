# -*- mode: python ; coding: utf-8 -*-
"""Windows 向けの onedir ビルド。UPX は使わない（誤検知を増やしやすい）。"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).resolve().parent
datas = []
binaries = []
hiddenimports = []
for package in ("rapidocr", "onnxruntime", "cv2", "shapely", "pyclipper"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

models = root / "models"
datas += [(str(path), "models") for path in models.glob("*.onnx")]
datas.append((str(root / "LICENSE"), "."))
datas.append((str(root / "THIRD_PARTY_NOTICES.md"), "."))
datas += [(str(path), "licenses") for path in (root / "licenses").glob("*.txt")]

block_cipher = None
analysis = Analysis(
    [str(root / "ekisui_pdf" / "__main__.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["torch", "tensorflow", "matplotlib"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(analysis.pure, cipher=block_cipher)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="ekisui-pdf",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="ekisui-pdf",
)
