#!/usr/bin/env python3
"""Write desktop/resources/icon.png (1024x1024, no third-party deps)."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

SIZE = 1024
BG = (7, 11, 16, 255)
INK = (231, 238, 246, 255)
TEAL = (42, 157, 143, 255)
CYAN = (76, 201, 240, 255)
GOLD = (233, 196, 106, 255)


def _blend(dst: bytearray, idx: int, r: int, g: int, b: int, a: int) -> None:
    if a <= 0:
        return
    if a >= 255:
        dst[idx : idx + 4] = bytes((r, g, b, 255))
        return
    inv = 255 - a
    dst[idx] = (dst[idx] * inv + r * a) // 255
    dst[idx + 1] = (dst[idx + 1] * inv + g * a) // 255
    dst[idx + 2] = (dst[idx + 2] * inv + b * a) // 255
    dst[idx + 3] = 255


def _fill_circle(px: bytearray, cx: float, cy: float, radius: float, color: tuple[int, int, int, int]) -> None:
    r, g, b, a = color
    x0 = max(int(cx - radius) - 1, 0)
    x1 = min(int(cx + radius) + 2, SIZE)
    y0 = max(int(cy - radius) - 1, 0)
    y1 = min(int(cy + radius) + 2, SIZE)
    rad2 = radius * radius
    for y in range(y0, y1):
        dy = y + 0.5 - cy
        for x in range(x0, x1):
            dx = x + 0.5 - cx
            d2 = dx * dx + dy * dy
            if d2 <= rad2:
                _blend(px, (y * SIZE + x) * 4, r, g, b, a)
            else:
                edge = d2**0.5 - radius
                if edge < 1:
                    _blend(px, (y * SIZE + x) * 4, r, g, b, int(a * (1 - edge)))


def _draw_line(
    px: bytearray,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    width: float,
    color: tuple[int, int, int, int],
) -> None:
    steps = max(int(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5) * 2, 1)
    for i in range(steps + 1):
        t = i / steps
        _fill_circle(px, x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, width / 2, color)


def _write_png(path: Path, px: bytearray) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes(px[y * SIZE * 4 : (y + 1) * SIZE * 4]) for y in range(SIZE))
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)


def main() -> None:
    px = bytearray(SIZE * SIZE * 4)
    for i in range(0, len(px), 4):
        px[i : i + 4] = bytes(BG)

    margin = 96
    _fill_circle(px, SIZE / 2, SIZE / 2, SIZE / 2 - 24, (13, 20, 28, 255))
    _fill_circle(px, SIZE / 2, SIZE / 2, SIZE / 2 - margin, (18, 28, 38, 255))

    nodes = [
        (280, 720, TEAL),
        (400, 430, CYAN),
        (640, 520, GOLD),
        (760, 280, INK),
    ]
    for (x0, y0, _), (x1, y1, _) in zip(nodes, nodes[1:]):
        _draw_line(px, x0, y0, x1, y1, 36, TEAL)
    for x, y, color in nodes:
        _fill_circle(px, x, y, 58, color)
        _fill_circle(px, x, y, 22, BG)

    out = Path(__file__).resolve().parents[1] / "desktop" / "resources" / "icon.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    _write_png(out, px)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
