"""Build tiny synthetic NEF (TIFF) files for tests."""

from __future__ import annotations

import struct
from pathlib import Path

TAG_DATETIME = 0x0132
TAG_EXIF_IFD = 0x8769
TAG_DATETIME_ORIGINAL = 0x9003
TAG_DATETIME_DIGITIZED = 0x9004


def build_nef(
    path: Path,
    original: str | None = "2026:07:25 14:32:10",
    digitized: str | None = None,
    ifd0_datetime: str | None = None,
    byte_order: str = "<",
    payload: bytes = b"RAWDATA",
) -> Path:
    """Write a minimal but structurally valid TIFF carrying the given dates."""
    exif_tags = [
        (tag, value)
        for tag, value in ((TAG_DATETIME_ORIGINAL, original),
                           (TAG_DATETIME_DIGITIZED, digitized))
        if value is not None
    ]
    ifd0_tags = [(TAG_DATETIME, ifd0_datetime)] if ifd0_datetime else []

    ifd0_count = len(ifd0_tags) + (1 if exif_tags else 0)
    ifd0_offset = 8
    ifd0_size = 2 + 12 * ifd0_count + 4
    exif_offset = ifd0_offset + ifd0_size
    exif_size = (2 + 12 * len(exif_tags) + 4) if exif_tags else 0
    strings_offset = exif_offset + exif_size

    strings = bytearray()
    string_offsets: dict[str, int] = {}

    def intern(text: str) -> tuple[int, int]:
        encoded = text.encode("ascii") + b"\x00"
        if text not in string_offsets:
            string_offsets[text] = strings_offset + len(strings)
            strings.extend(encoded)
        return string_offsets[text], len(encoded)

    def ascii_entry(tag: int, text: str) -> bytes:
        offset, length = intern(text)
        return struct.pack(byte_order + "HHI", tag, 2, length) + struct.pack(
            byte_order + "I", offset
        )

    def long_entry(tag: int, value: int) -> bytes:
        return struct.pack(byte_order + "HHI", tag, 4, 1) + struct.pack(
            byte_order + "I", value
        )

    ifd0 = bytearray(struct.pack(byte_order + "H", ifd0_count))
    for tag, value in ifd0_tags:
        ifd0.extend(ascii_entry(tag, value))
    if exif_tags:
        ifd0.extend(long_entry(TAG_EXIF_IFD, exif_offset))
    ifd0.extend(struct.pack(byte_order + "I", 0))

    exif = bytearray()
    if exif_tags:
        exif.extend(struct.pack(byte_order + "H", len(exif_tags)))
        for tag, value in exif_tags:
            exif.extend(ascii_entry(tag, value))
        exif.extend(struct.pack(byte_order + "I", 0))

    header = (b"II" if byte_order == "<" else b"MM") + struct.pack(
        byte_order + "HI", 42, ifd0_offset
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(header + ifd0 + exif + strings) + payload)
    return path
