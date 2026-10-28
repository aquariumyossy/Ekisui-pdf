"""The window icon carries every size stored in ekisui.ico."""

import importlib.util
import os
import struct

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtWidgets import QApplication

from ekisui.gui.icon import load_app_icon
from ekisui.paths import icon_file

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("check_exe_icon", ROOT / "tools" / "check_exe_icon.py")
assert _spec and _spec.loader
check_exe_icon = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_exe_icon)


def test_ico_lists_the_approved_sizes():
    data = (ROOT / "assets" / "icon" / "ekisui.ico").read_bytes()
    _reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    assert kind == 1
    sizes = []
    for index in range(count):
        width, height = struct.unpack_from("<BB", data, 6 + 16 * index)
        sizes.append((width or 256, height or 256))
    assert sizes == [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def _assemble_pe(blobs: list[bytes]) -> bytes:
    """PE32+ whose only resources are the given RT_ICON payloads."""
    count = len(blobs)
    root = 16 + 8
    type_dir = 16 + 8 * count
    name_dirs = count * (16 + 8)
    lang_dirs = count * (16 + 8)
    data_entries = count * 16
    header_size = root + type_dir + name_dirs + lang_dirs + data_entries
    payload_at = header_size
    rva_base = 0x1000
    cursor = payload_at
    payload_rvas = []
    payload = bytearray()
    for blob in blobs:
        payload_rvas.append(rva_base + cursor)
        payload += blob
        cursor += len(blob)
    # directories
    out = bytearray()

    def directory(named: int, ids: int) -> bytes:
        return struct.pack("<IIHHHH", 0, 0, 0, 0, named, ids)

    # root at 0: one ID entry, type 3, subdirectory at `root` (16+8=24)
    out += directory(0, 1)
    type_dir_at = 24
    out += struct.pack("<II", 3, 0x80000000 | type_dir_at)
    # type dir: count name entries
    name_base = type_dir_at + 16 + 8 * count
    out += directory(0, count)
    for index in range(count):
        name_at = name_base + index * (16 + 8)
        out += struct.pack("<II", index + 1, 0x80000000 | name_at)
    lang_base = name_base + count * (16 + 8)
    for index in range(count):
        out += directory(0, 1)
        lang_at = lang_base + index * (16 + 8)
        out += struct.pack("<II", 0x0409, 0x80000000 | lang_at)
    data_base = lang_base + count * (16 + 8)
    for index in range(count):
        out += directory(0, 1)
        data_at = data_base + index * 16
        out += struct.pack("<II", 0, data_at)  # data entry, not a directory
    assert len(out) == data_base
    for index, blob in enumerate(blobs):
        out += struct.pack("<IIII", payload_rvas[index], len(blob), 0, 0)
    assert len(out) == header_size
    out += payload
    resource = bytes(out)

    # PE headers
    section_raw = 0x200
    optional_size = 240  # 112 + 16*8 directories
    # COFF 20 + optional
    pe = bytearray(section_raw)
    pe[0:2] = b"MZ"
    e_lfanew = 0x80
    struct.pack_into("<I", pe, 0x3C, e_lfanew)
    pe[e_lfanew : e_lfanew + 4] = b"PE\0\0"
    coff = e_lfanew + 4
    struct.pack_into("<HHIIIHH", pe, coff, 0x8664, 1, 0, 0, 0, optional_size, 0x22)
    optional = coff + 20
    pe[optional : optional + 2] = struct.pack("<H", 0x20B)
    # NumberOfRvaAndSizes at optional+108
    struct.pack_into("<I", pe, optional + 108, 16)
    # Resource data directory is index 2, at optional+112+16
    struct.pack_into("<II", pe, optional + 112 + 16, rva_base, len(resource))
    section = optional + optional_size
    name = b".rsrc\0\0\0"
    pe[section : section + 8] = name
    struct.pack_into("<IIII", pe, section + 8, len(resource), rva_base, len(resource), section_raw)
    blob = bytes(pe[:section_raw]) + resource
    return blob


def test_checker_matches_icon_bytes_inside_a_pe(tmp_path):
    ico = (ROOT / "assets" / "icon" / "ekisui.ico").read_bytes()
    images = check_exe_icon.ico_images(ico)
    fake = _assemble_pe([blob for _w, _h, blob in images])
    exe = tmp_path / "ekisui-pdf.exe"
    exe.write_bytes(fake)
    assert check_exe_icon.main(["check_exe_icon.py", str(exe), str(ROOT / "assets" / "icon" / "ekisui.ico")]) == 0


def test_window_icon_keeps_every_frame():
    app = QApplication.instance() or QApplication([])
    icon = load_app_icon()
    assert icon_file().is_file()
    loaded = {(size.width(), size.height()) for size in icon.availableSizes()}
    assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= loaded
    app.processEvents()
