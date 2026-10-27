"""Which files and modules stay in the Windows bundle.

PyInstaller is told to skip these before Analysis, and the spec drops anything
the Qt hooks add afterwards. The same rules are what the installer job checks
the frozen tree with, so a test on Linux covers the Windows filter.
"""

from __future__ import annotations

from pathlib import PurePosixPath

# PySide6 modules the app never imports. QtCore, QtGui, and QtWidgets stay.
_QT_MODULES = (
    "Qt3DAnimation",
    "Qt3DCore",
    "Qt3DExtras",
    "Qt3DInput",
    "Qt3DLogic",
    "Qt3DRender",
    "QtAxContainer",
    "QtBluetooth",
    "QtCharts",
    "QtConcurrent",
    "QtDBus",
    "QtDataVisualization",
    "QtDesigner",
    "QtGraphs",
    "QtGraphsWidgets",
    "QtHelp",
    "QtHttpServer",
    "QtLocation",
    "QtMultimedia",
    "QtMultimediaWidgets",
    "QtNetwork",
    "QtNetworkAuth",
    "QtNfc",
    "QtOpenGL",
    "QtOpenGLWidgets",
    "QtPdf",
    "QtPdfWidgets",
    "QtPositioning",
    "QtPrintSupport",
    "QtQml",
    "QtQuick",
    "QtQuick3D",
    "QtQuickControls2",
    "QtQuickWidgets",
    "QtRemoteObjects",
    "QtScxml",
    "QtSensors",
    "QtSerialBus",
    "QtSerialPort",
    "QtShaderTools",
    "QtSpatialAudio",
    "QtSql",
    "QtStateMachine",
    "QtSvg",
    "QtSvgWidgets",
    "QtTest",
    "QtTextToSpeech",
    "QtUiTools",
    "QtWebChannel",
    "QtWebEngineCore",
    "QtWebEngineQuick",
    "QtWebEngineWidgets",
    "QtWebSockets",
    "QtXml",
)

# Importing pymupdf runs ``import pymupdf.layout`` and that package loads its
# ONNX models immediately. Deleting only the model files leaves the import
# succeeding and then crashing. The whole module has to be absent so the
# existing ImportError handler skips it. get_text, search_for, and
# apply_redactions do not call the layout hook.
_EXCLUDED_PREFIXES = (
    "pymupdf.layout",
    "pymupdf4llm",
    "numpy.tests",
    "numpy.f2py",
    "onnxruntime.quantization",
    "onnxruntime.tools",
    "onnxruntime.transformers",
)

_KEEP_QT_DLLS = {"qt6core.dll", "qt6gui.dll", "qt6widgets.dll"}
_KEEP_QT_EXTENSIONS = {"qtcore", "qtgui", "qtwidgets"}
_PYSIDE_DEV_DIRS = {"include", "glue", "typesystems", "scripts", "doc", "examples"}
_MEDIA_DLLS = ("avcodec", "avformat", "avutil", "swscale", "swresample")


def analysis_excludes() -> list[str]:
    return [
        *_EXCLUDED_PREFIXES,
        *(f"PySide6.{name}" for name in _QT_MODULES),
    ]


def excluded_module(name: str) -> bool:
    """True when this import name must not be frozen into the app."""
    module = name.strip().lower()
    parts = [part for part in module.split(".") if part]
    # numpy.tests does not cover numpy.lib.tests. Those imports pull pytest in.
    if parts and parts[0] == "numpy" and ({"tests", "f2py", "conftest"} & set(parts[1:])):
        return True
    for prefix in _EXCLUDED_PREFIXES:
        if module == prefix or module.startswith(prefix + "."):
            return True
    if module.startswith("pyside6.qt"):
        rest = module.split(".", 1)[1]
        kept = rest == "qtcore" or rest == "qtgui" or rest == "qtwidgets"
        kept = kept or rest.startswith(("qtcore.", "qtgui.", "qtwidgets."))
        return not kept
    return False


def shipped_name(source: str, dest: str) -> str:
    """Destination relative path for a PyInstaller ``(source, dest_dir)`` pair."""
    dest_path = PurePosixPath(str(dest).replace("\\", "/"))
    source_name = PurePosixPath(str(source).replace("\\", "/")).name
    if not source_name or dest_path.name == source_name:
        return dest_path.as_posix()
    return (dest_path / source_name).as_posix()


def excluded_bundle_dest(path: str) -> bool:
    """True when a collected file should be left out of the frozen tree.

    ``path`` is a source path, a destination directory plus file name, or a
    TOC dest name. ``opengl32sw.dll`` and ``icudtl.dat`` are never excluded.
    """
    normal = str(path).replace("\\", "/").lower()
    if not normal or normal == ".":
        return False
    parts = [part for part in normal.split("/") if part and part != "."]
    if not parts:
        return False
    name = parts[-1]
    if name in {"opengl32sw.dll", "icudtl.dat"}:
        return False
    # pymupdf4llm imports pymupdf.layout and loads ONNX as soon as it imports.
    if "pymupdf4llm" in parts or _under(parts, "pymupdf", {"layout"}) or "mupdf-devel" in parts:
        return True
    if name.endswith(".lib"):
        return True
    if "opencv_videoio_ffmpeg" in name:
        return True
    if "pil" in parts and (name.startswith("_avif") or name.startswith("_webp")):
        return True
    if _numpy_tests(parts):
        return True
    if _under(parts, "onnxruntime", {"quantization", "tools", "transformers"}):
        return True
    if "pyside6" not in parts:
        return False
    plugin = _plugin_decision(parts)
    if plugin is not None:
        return plugin
    if "translations" in parts or "metatypes" in parts or "qml" in parts:
        return True
    if any(part in _PYSIDE_DEV_DIRS for part in parts):
        return True
    if name == "qmlls.exe" or name.endswith(".exe") or name.endswith(".qm") or name.endswith(".pak"):
        return True
    if name.startswith("v8_context_snapshot"):
        return True
    if "webengine" in name or any("webengine" in part for part in parts):
        return True
    if _unused_qt_binary(name):
        return True
    return any(name.startswith(prefix) for prefix in _MEDIA_DLLS)


def keep_toc_entry(entry: tuple) -> bool:
    """Keep a TOC row.

    Pure-module rows are judged by the import name. ``numpy.lib`` ends in
    ``.lib``, and a source path can sit under a folder named ``examples``, so
    the file rules must not see either of those. File rows are judged by the
    destination path only.
    """
    dest = str(entry[0])
    kind = str(entry[2]) if len(entry) > 2 else ""
    if kind.upper() == "PYMODULE":
        return not excluded_module(dest)
    return not excluded_bundle_dest(dest)


def _under(parts: list[str], package: str, markers: set[str]) -> bool:
    if package not in parts:
        return False
    index = parts.index(package)
    return any(part in markers for part in parts[index + 1 :])


def _numpy_tests(parts: list[str]) -> bool:
    if "numpy" not in parts:
        return False
    rest = parts[parts.index("numpy") + 1 :]
    return "tests" in rest or "f2py" in rest


def _unused_qt_binary(name: str) -> bool:
    if name in _KEEP_QT_DLLS:
        return False
    if name.startswith("qt6") and name.endswith(".dll"):
        return True
    stem = name.split(".", 1)[0]
    if stem in _KEEP_QT_EXTENSIONS:
        return False
    return stem.startswith("qt") and (
        name.endswith(".pyd") or name.endswith(".pyi") or ".pyd" in name or ".abi3.so" in name
    )


def _plugin_decision(parts: list[str]) -> bool | None:
    """False keeps the file, True drops it, None means this is not a plugin path."""
    if "plugins" not in parts:
        return None
    plugins_at = parts.index("plugins")
    if "pyside6" not in parts[:plugins_at]:
        return None
    rest = parts[plugins_at + 1 :]
    if not rest:
        return None
    kind = rest[0]
    if kind in {"platforms", "styles"}:
        return False
    # PNG is built into the Windows Qt6Gui, but keep qpng if a wheel still ships it.
    if kind == "imageformats" and rest[-1].startswith("qpng"):
        return False
    return True
