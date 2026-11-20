"""Single-image classic TIFF / BigTIFF writer for enormous GeoStudio canvases.

An export is rasterized as small RGB tiles in the browser but written into
one TIFF page at exact offsets in a sparse temporary disk file. Unlike a
giant in-memory PIL image, memory remains bounded by one upload tile.
"""
from __future__ import annotations

import struct


def tiff_header(width: int, height: int, dpi: int) -> tuple[bytes, int, bool]:
    if (type(width) is not int or type(height) is not int or
            not 1 <= width <= 200_000 or not 1 <= height <= 200_000 or
            type(dpi) is not int or dpi not in (96, 150, 300, 600)):
        raise ValueError("Nieprawidłowy rozmiar lub DPI obrazu TIFF.")
    byte_count = width * height * 3
    big = byte_count + 180 > 0xFFFFFFFF
    entries = (
        (256, 4, 1, width),       # ImageWidth
        (257, 4, 1, height),      # ImageLength
        (258, 3, 3, (8, 8, 8)),  # BitsPerSample: RGB8
        (259, 3, 1, 1),           # Compression: none
        (262, 3, 1, 2),           # Photometric: RGB
        (273, 16 if big else 4, 1, 320 if big else 180),
        (277, 3, 1, 3),           # SamplesPerPixel
        (278, 4, 1, height),      # RowsPerStrip: one image-wide strip
        (279, 16 if big else 4, 1, byte_count),
        (282, 5, 1, (dpi, 1)),    # XResolution in inches
        (283, 5, 1, (dpi, 1)),    # YResolution in inches
        (296, 3, 1, 2),           # ResolutionUnit: inch
    )
    if big:
        # BigTIFF has 64-bit offsets and byte counts, needed beyond 4 GiB.
        data = bytearray(320)
        struct.pack_into("<2sHHHQ", data, 0, b"II", 43, 8, 0, 16)
        struct.pack_into("<Q", data, 16, len(entries))
        for index, (tag, typ, count, value) in enumerate(entries):
            at = 24 + index * 20
            struct.pack_into("<HHQ", data, at, tag, typ, count)
            if isinstance(value, tuple):
                if tag == 258:
                    struct.pack_into("<HHH", data, at + 12, *value)
                else:
                    struct.pack_into("<II", data, at + 12, *value)
            else:
                struct.pack_into("<Q", data, at + 12, value)
        struct.pack_into("<Q", data, 24 + len(entries) * 20, 0)
        return bytes(data), 320, True

    # Classic baseline TIFF: IFD at 8, auxiliary values at 158..179.
    data = bytearray(180)
    struct.pack_into("<2sHIH", data, 0, b"II", 42, 8, len(entries))
    for index, (tag, typ, count, value) in enumerate(entries):
        at = 10 + index * 12
        struct.pack_into("<HHI", data, at, tag, typ, count)
        if tag == 258:
            struct.pack_into("<I", data, at + 8, 158)
            struct.pack_into("<HHH", data, 158, *value)
        elif tag in (282, 283):
            position = 164 if tag == 282 else 172
            struct.pack_into("<I", data, at + 8, position)
            struct.pack_into("<II", data, position, *value)
        else:
            struct.pack_into("<I", data, at + 8, value)
    struct.pack_into("<I", data, 154, 0)
    return bytes(data), 180, False
