"""Confirm a Windows exe embeds the same icon images as ekisui.ico.

PyInstaller and Inno Setup store each ICO frame as an RT_ICON resource.
This compares those bytes with the file in the repository.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path


def ico_images(data: bytes) -> list[tuple[int, int, bytes]]:
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    if reserved != 0 or kind != 1 or count < 1:
        raise ValueError("ICO ではありません")
    images = []
    for index in range(count):
        width, height, _colors, _reserved, _planes, _bits, size, offset = struct.unpack_from(
            "<BBBBHHII", data, 6 + 16 * index
        )
        images.append((width or 256, height or 256, data[offset : offset + size]))
    return images


def _rva_to_offset(sections: list[tuple[int, int, int]], rva: int) -> int:
    for virtual, span, raw in sections:
        if virtual <= rva < virtual + span:
            return raw + (rva - virtual)
    raise ValueError(f"リソースの RVA が節にありません: {rva}")


def pe_icon_images(data: bytes) -> list[bytes]:
    if data[:2] != b"MZ":
        raise ValueError("PE ではありません")
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e_lfanew : e_lfanew + 4] != b"PE\0\0":
        raise ValueError("PE 署名がありません")
    coff = e_lfanew + 4
    _machine, sections_count, _t1, _t2, _t3, optional_size, _chars = struct.unpack_from("<HHIIIHH", data, coff)
    optional = coff + 20
    magic = struct.unpack_from("<H", data, optional)[0]
    directory = optional + (112 if magic == 0x20B else 96)
    resource_rva, _resource_size = struct.unpack_from("<II", data, directory + 8 * 2)
    section_table = optional + optional_size
    sections: list[tuple[int, int, int]] = []
    for index in range(sections_count):
        at = section_table + 40 * index
        virtual_size, virtual, raw_size, raw = struct.unpack_from("<IIII", data, at + 8)
        sections.append((virtual, max(virtual_size, raw_size), raw))
    root = _rva_to_offset(sections, resource_rva)
    blobs: list[bytes] = []

    def walk(offset: int, level: int, type_id: int) -> None:
        named, numbered = struct.unpack_from("<HH", data, offset + 12)
        for index in range(named + numbered):
            ident, relative = struct.unpack_from("<II", data, offset + 16 + 8 * index)
            target = root + (relative & 0x7FFFFFFF)
            if relative & 0x80000000:
                walk(target, level + 1, ident if level == 0 else type_id)
            elif type_id == 3:
                data_rva, size = struct.unpack_from("<II", data, target)
                start = _rva_to_offset(sections, data_rva)
                blobs.append(data[start : start + size])

    walk(root, 0, 0)
    return blobs


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: check_exe_icon.py <exe> <ekisui.ico>")
        return 2
    exe = Path(argv[1])
    ico = Path(argv[2])
    images = ico_images(ico.read_bytes())
    embedded = pe_icon_images(exe.read_bytes())
    expected = {blob for _w, _h, blob in images}
    found = set(embedded)
    sizes = ",".join(str(width) for width, _height, _blob in images)
    print(f"ICON_SIZES {sizes}")
    print(f"ICON_FRAMES {len(images)} EMBEDDED {len(embedded)}")
    missing = expected - found
    if missing or len(found & expected) != len(expected):
        print(f"ICON_MISMATCH missing={len(missing)}")
        return 1
    print("ICON_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
