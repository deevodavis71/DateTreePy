"""Minimal EXIF capture-date reader for Nikon NEF files.

A NEF is a TIFF container, so the capture date is reachable by walking the
TIFF IFD structure directly -- no third-party imaging library required.
Only the handful of bytes needed for the date tags are read, which matters
because raw files run 25-50MB each.
"""

from __future__ import annotations

import struct
from datetime import date, datetime
from pathlib import Path

# TIFF/EXIF tags we care about.
TAG_DATETIME = 0x0132  # IFD0, file-modification style date, used as a last resort
TAG_EXIF_IFD = 0x8769  # IFD0, pointer to the EXIF sub-IFD
TAG_DATETIME_ORIGINAL = 0x9003  # EXIF IFD, when the shutter fired
TAG_DATETIME_DIGITIZED = 0x9004  # EXIF IFD, when it was written to card

TYPE_SHORT = 3
TYPE_LONG = 4
TYPE_ASCII = 2

# Sanity limits: a corrupt or non-NEF file should raise, not make us read
# gigabytes or spin through a bogus entry count.
_MAX_IFD_ENTRIES = 512
_MAX_STRING_LEN = 64

DATE_SOURCE_EXIF = "exif"
DATE_SOURCE_MTIME = "mtime"


class ExifError(Exception):
    """Raised when a file is not a readable TIFF/NEF or lacks a usable date."""


class _Tiff:
    """Byte-level reader for the TIFF structure inside a NEF."""

    def __init__(self, fh):
        self._fh = fh
        header = self._read(0, 8)
        if header[:2] == b"II":
            self.byte_order = "<"
        elif header[:2] == b"MM":
            self.byte_order = ">"
        else:
            raise ExifError("not a TIFF/NEF file (bad byte-order mark)")
        magic, ifd0_offset = struct.unpack(self.byte_order + "HI", header[2:8])
        if magic != 42:
            raise ExifError(f"not a TIFF/NEF file (bad magic {magic})")
        self.ifd0_offset = ifd0_offset

    def _read(self, offset: int, length: int) -> bytes:
        if offset < 0 or length < 0:
            raise ExifError("negative offset or length")
        self._fh.seek(offset)
        data = self._fh.read(length)
        if len(data) != length:
            raise ExifError(f"truncated read at offset {offset}")
        return data

    def read_ifd(self, offset: int) -> dict[int, tuple[int, int, bytes]]:
        """Return {tag: (type, count, 4-byte value field)} for one IFD."""
        (count,) = struct.unpack(self.byte_order + "H", self._read(offset, 2))
        if count > _MAX_IFD_ENTRIES:
            raise ExifError(f"implausible IFD entry count {count}")
        buf = self._read(offset + 2, 12 * count)
        entries = {}
        for i in range(count):
            tag, typ, n, value = struct.unpack(
                self.byte_order + "HHI4s", buf[12 * i : 12 * i + 12]
            )
            entries[tag] = (typ, n, value)
        return entries

    def as_offset(self, entry: tuple[int, int, bytes]) -> int:
        typ, _count, value = entry
        if typ == TYPE_SHORT:
            return struct.unpack(self.byte_order + "H", value[:2])[0]
        if typ == TYPE_LONG:
            return struct.unpack(self.byte_order + "I", value)[0]
        raise ExifError(f"expected SHORT/LONG offset, got type {typ}")

    def as_ascii(self, entry: tuple[int, int, bytes]) -> str:
        typ, count, value = entry
        if typ != TYPE_ASCII:
            raise ExifError(f"expected ASCII, got type {typ}")
        if count > _MAX_STRING_LEN:
            raise ExifError(f"implausible string length {count}")
        if count <= 4:
            data = value[:count]
        else:
            (offset,) = struct.unpack(self.byte_order + "I", value)
            data = self._read(offset, count)
        return data.split(b"\x00", 1)[0].decode("ascii", "replace").strip()


def parse_exif_datetime(text: str) -> datetime | None:
    """Parse an EXIF date string, tolerating the usual camera quirks."""
    text = text.strip()
    if not text or text.startswith("0000"):
        return None
    # Cameras occasionally use dashes, and some pad the day with a space.
    normalised = text.replace("-", ":").replace(": ", ":0")
    try:
        return datetime.strptime(normalised, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        pass
    try:
        return datetime.strptime(normalised[:10], "%Y:%m:%d")
    except ValueError:
        return None


def read_capture_datetime(path: Path) -> datetime | None:
    """Return the EXIF capture time of a NEF, or None if there isn't one.

    Raises ExifError only when the file cannot be parsed as TIFF at all.
    """
    with open(path, "rb") as fh:
        tiff = _Tiff(fh)
        ifd0 = tiff.read_ifd(tiff.ifd0_offset)

        # DateTimeOriginal/Digitized live in the EXIF sub-IFD.
        if TAG_EXIF_IFD in ifd0:
            try:
                exif_ifd = tiff.read_ifd(tiff.as_offset(ifd0[TAG_EXIF_IFD]))
            except ExifError:
                exif_ifd = {}
            for tag in (TAG_DATETIME_ORIGINAL, TAG_DATETIME_DIGITIZED):
                if tag in exif_ifd:
                    try:
                        parsed = parse_exif_datetime(tiff.as_ascii(exif_ifd[tag]))
                    except ExifError:
                        continue
                    if parsed is not None:
                        return parsed

        if TAG_DATETIME in ifd0:
            try:
                return parse_exif_datetime(tiff.as_ascii(ifd0[TAG_DATETIME]))
            except ExifError:
                return None
    return None


def capture_date(path: Path) -> tuple[date, str]:
    """Return (date, source) for a file, falling back to filesystem mtime.

    source is "exif" when the date came from the NEF's own metadata and
    "mtime" when it was derived from the filesystem timestamp instead.
    """
    try:
        captured = read_capture_datetime(path)
    except (ExifError, OSError):
        captured = None
    if captured is not None:
        return captured.date(), DATE_SOURCE_EXIF
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return mtime.date(), DATE_SOURCE_MTIME


def date_folder(day: date) -> str:
    """Destination sub-folder name for a capture date, e.g. 2026-07-25."""
    return day.strftime("%Y-%m-%d")
