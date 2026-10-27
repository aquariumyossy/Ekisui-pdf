from ekisui.bundle_filter import excluded_bundle_dest, excluded_module, keep_toc_entry, shipped_name


def test_shipped_name_joins_the_destination_directory():
    assert shipped_name(r"C:\wheels\Qt6Core.dll", "PySide6") == "PySide6/Qt6Core.dll"
    assert shipped_name("/opt/qpng.dll", "PySide6/plugins/imageformats") == (
        "PySide6/plugins/imageformats/qpng.dll"
    )


def test_filter_drops_unused_files_and_keeps_the_runtime():
    kept = [
        "PySide6/opengl32sw.dll",
        "_internal/PySide6/opengl32sw.dll",
        "PySide6/Qt6Core.dll",
        "PySide6/Qt6Gui.dll",
        "PySide6/Qt6Widgets.dll",
        "PySide6/QtCore.pyd",
        "PySide6/QtGui.pyd",
        "PySide6/QtWidgets.pyd",
        "PySide6/plugins/platforms/qwindows.dll",
        "PySide6/plugins/platforms/qoffscreen.dll",
        "PySide6/Qt/plugins/styles/qmodernwindowsstyle.dll",
        "PySide6/plugins/imageformats/qpng.dll",
        "PySide6/resources/icudtl.dat",
        "PySide6/d3dcompiler_47.dll",
        "PySide6/libEGL.dll",
        "numpy/testing/__init__.py",
        "numpy/core/_multiarray_umath.pyd",
        "onnxruntime/capi/onnxruntime.dll",
        "pymupdf/_mupdf.pyd",
        "pymupdf/mupdfcpp64.dll",
        "PIL/_imaging.pyd",
        "models/ppocrv5/ch_PP-OCRv5_det_mobile.onnx",
        "shiboken6/shiboken6.abi3.dll",
    ]
    dropped = [
        "PySide6/Qt6WebEngineCore.dll",
        "PySide6/QtWebEngineCore.pyd",
        "PySide6/Qt6Quick.dll",
        "PySide6/Qt6Qml.dll",
        "PySide6/Qt6OpenGL.dll",
        "PySide6/QtOpenGL.pyd",
        "PySide6/Qt6Pdf.dll",
        "PySide6/Qt6Network.dll",
        "PySide6/Qt6Svg.dll",
        "PySide6/Qt6Multimedia.dll",
        "PySide6/Qt6LabsStyleKit.dll",
        "PySide6/Qt63DQuick.dll",
        "PySide6/Qt6VirtualKeyboard.dll",
        "PySide6/assistant.exe",
        "PySide6/designer.exe",
        "PySide6/resources/v8_context_snapshot.debug.bin",
        "PySide6/include/PySide6/QtGui/pyside6_qtgui_python.h",
        "PySide6/avcodec-63.dll",
        "PySide6/translations/qt_ja.qm",
        "PySide6/metatypes/qt6core_metatypes.json",
        "PySide6/qml/QtQuick/qmldir",
        "PySide6/qmlls.exe",
        "PySide6/plugins/imageformats/qjpeg.dll",
        "PySide6/plugins/iconengines/qsvgicon.dll",
        "PySide6/plugins/generic/qtuiotouch.dll",
        "PySide6/resources/qtwebengine_devtools_resources.pak",
        "pymupdf/layout/resources/layout_rf2.4.1+imf1.onnx",
        "pymupdf/layout/__init__.py",
        "pymupdf/mupdf-devel/lib/mupdf.lib",
        "pymupdf/mupdfcpp64.lib",
        "cv2/opencv_videoio_ffmpeg500_64.dll",
        "PIL/_avif.pyd",
        "PIL/_webp.cp312-win_amd64.pyd",
        "numpy/tests/test_regression.py",
        "numpy/f2py/src/fortranobject.c",
        "numpy/random/tests/test_random.py",
        "onnxruntime/quantization/quantize.py",
        "onnxruntime/tools/check.py",
        "onnxruntime/transformers/optimizer.py",
    ]
    kept_hits = [path for path in kept if excluded_bundle_dest(path)]
    dropped_misses = [path for path in dropped if not excluded_bundle_dest(path)]
    assert kept_hits == []
    assert dropped_misses == []


def test_excluded_modules_leave_the_runtime_packages():
    assert excluded_module("pymupdf.layout")
    assert excluded_module("pymupdf.layout.onnx")
    assert excluded_module("pymupdf4llm")
    assert not excluded_module("pymupdf")
    assert excluded_module("numpy.tests")
    assert excluded_module("numpy.f2py")
    assert not excluded_module("numpy.testing")
    assert not excluded_module("numpy.testing.utils")
    assert excluded_module("onnxruntime.quantization.calibrate")
    assert excluded_module("PySide6.QtWebEngineCore")
    assert excluded_module("PySide6.QtNetwork")
    assert not excluded_module("PySide6.QtCore")
    assert not excluded_module("PySide6.QtGui")
    assert not excluded_module("PySide6.QtWidgets")
    assert not excluded_module("PySide6.support.deprecated")
    assert excluded_module("numpy.lib.tests.test_io")
    assert excluded_module("numpy.f2py.rules")
    assert not excluded_module("numpy.lib")
    assert not excluded_module("numpy.lib.stride_tricks")


def test_module_rows_are_not_judged_as_files():
    source = r"C:\Users\me\examples\ekisui\.venv\Lib\site-packages\numpy\lib\__init__.py"
    assert keep_toc_entry(("numpy.lib", source, "PYMODULE"))
    assert not keep_toc_entry(("numpy.lib.tests.test_io", source, "PYMODULE"))
    qt = r"C:\Users\me\examples\ekisui\.venv\Lib\site-packages\PySide6\Qt6Core.dll"
    assert keep_toc_entry(("PySide6/Qt6Core.dll", qt, "BINARY"))
    assert excluded_bundle_dest("pymupdf4llm/__init__.py")
    assert not keep_toc_entry(("pymupdf4llm/__init__.py", r"C:\wheels\pymupdf4llm\__init__.py", "DATA"))
