"""Generate DateTree.app's icon.

Renders a blue rounded-square tile with a white folder glyph at every size
macOS wants, writes the PNGs with nothing but zlib and struct, and hands the
iconset to iconutil. Pure standard library, so the icon can be regenerated on
any machine without installing an imaging library.

    python3 tools/make_icon.py [output.icns]
"""

from __future__ import annotations

import math
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

# Icon design, in 0..1 units so it scales to any pixel size.
TILE_INSET = 0.055
TILE_RADIUS = 0.215
GRADIENT_TOP = (0x1E, 0x90, 0xFF)
GRADIENT_BOTTOM = (0x00, 0x52, 0xD6)
GLYPH = (0xFF, 0xFF, 0xFF)

FOLDER_BODY = (0.235, 0.415, 0.765, 0.720)  # x1, y1, x2, y2
FOLDER_BODY_RADIUS = 0.035
FOLDER_TAB = (0.235, 0.320, 0.470, 0.430)
FOLDER_TAB_RADIUS = 0.030

ICONSET_SIZES = [
    ("icon_16x16.png", 16), ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32), ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128), ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256), ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512), ("icon_512x512@2x.png", 1024),
]


def _rounded_rect_distance(x, y, x1, y1, x2, y2, radius) -> float:
    """Signed distance to a rounded rectangle; negative means inside."""
    cx = min(max(x, x1 + radius), x2 - radius)
    cy = min(max(y, y1 + radius), y2 - radius)
    dx, dy = x - cx, y - cy
    if dx == 0 and dy == 0:
        return -radius
    return math.hypot(dx, dy) - radius


def _sample(x: float, y: float) -> tuple[int, int, int, int]:
    """Colour of the icon at a point in 0..1 space, RGBA, not premultiplied."""
    tile = _rounded_rect_distance(
        x, y, TILE_INSET, TILE_INSET, 1 - TILE_INSET, 1 - TILE_INSET, TILE_RADIUS
    )
    if tile > 0:
        return (0, 0, 0, 0)

    # The union of tab and body would pinch inward where their corner radii
    # meet, so a spine strip keeps the left edge straight through the junction.
    spine_x1, spine_y1 = FOLDER_TAB[0], FOLDER_TAB[1] + FOLDER_TAB_RADIUS
    spine_x2, spine_y2 = FOLDER_TAB[0] + 0.07, FOLDER_BODY[3] - FOLDER_BODY_RADIUS
    in_folder = (
        _rounded_rect_distance(x, y, *FOLDER_BODY, FOLDER_BODY_RADIUS) <= 0
        or _rounded_rect_distance(x, y, *FOLDER_TAB, FOLDER_TAB_RADIUS) <= 0
        or (spine_x1 <= x <= spine_x2 and spine_y1 <= y <= spine_y2)
    )
    if in_folder:
        return (*GLYPH, 255)

    blend = (y - TILE_INSET) / (1 - 2 * TILE_INSET)
    blend = min(max(blend, 0.0), 1.0)
    return (
        round(GRADIENT_TOP[0] + (GRADIENT_BOTTOM[0] - GRADIENT_TOP[0]) * blend),
        round(GRADIENT_TOP[1] + (GRADIENT_BOTTOM[1] - GRADIENT_TOP[1]) * blend),
        round(GRADIENT_TOP[2] + (GRADIENT_BOTTOM[2] - GRADIENT_TOP[2]) * blend),
        255,
    )


def render(size: int, supersample: int = 3) -> bytes:
    """Render the icon as raw RGBA rows, antialiased by supersampling."""
    rows = bytearray()
    samples = supersample * supersample
    step = 1.0 / (size * supersample)
    for py in range(size):
        rows.append(0)  # PNG per-scanline filter type: none
        for px in range(size):
            r = g = b = a = 0
            for sy in range(supersample):
                y = (py * supersample + sy + 0.5) * step
                for sx in range(supersample):
                    x = (px * supersample + sx + 0.5) * step
                    sr, sg, sb, sa = _sample(x, y)
                    # Premultiply so edge pixels don't bleed toward black.
                    r += sr * sa
                    g += sg * sa
                    b += sb * sa
                    a += sa
            if a == 0:
                rows.extend(b"\x00\x00\x00\x00")
            else:
                rows.extend(bytes((round(r / a), round(g / a), round(b / a),
                                   round(a / samples))))
    return bytes(rows)


def write_png(path: Path, size: int, raw_rows: bytes) -> None:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw_rows, 9))
        + chunk(b"IEND", b"")
    )


def main(destination: Path) -> int:
    if shutil.which("iconutil") is None:
        print("iconutil not found; this script only runs on macOS", file=sys.stderr)
        return 1

    rendered: dict[int, bytes] = {}
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "DateTree.iconset"
        iconset.mkdir()
        for name, size in ICONSET_SIZES:
            if size not in rendered:
                # Large sizes need less supersampling to look smooth.
                rendered[size] = render(size, 2 if size >= 512 else 3)
                print(f"  rendered {size}x{size}")
            write_png(iconset / name, size, rendered[size])
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(destination)],
            check=True,
        )
    print(f"wrote {destination} ({destination.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "assets/DateTree.icns"
    )
    sys.exit(main(target))
