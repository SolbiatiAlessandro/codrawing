from __future__ import annotations

from collections import Counter, defaultdict
import struct
import zlib


COLOR_CHARACTER = {
    "#EF4444": "R",
    "#3B82F6": "B",
    "#22C55E": "G",
    "#F59E0B": "A",
    "#A855F7": "V",
}


def png_snapshot(
    pixels: list[dict[str, object]],
    *,
    width: int,
    height: int,
    scale: int = 4,
) -> bytes:
    colors = {(int(pixel["x"]), int(pixel["y"])): str(pixel["color"]) for pixel in pixels}
    output_width = width * scale
    output_height = height * scale
    rows = bytearray()
    for output_y in range(output_height):
        rows.append(0)  # PNG filter: none
        source_y = output_y // scale
        for output_x in range(output_width):
            source_x = output_x // scale
            color = colors.get((source_x, source_y), "#FFFFFF")
            rows.extend(bytes.fromhex(color.removeprefix("#")))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", output_width, output_height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b"")


def textual_snapshot(
    pixels: list[dict[str, object]],
    *,
    width: int,
    height: int,
    grid_size: int = 32,
) -> dict[str, object]:
    if pixels:
        xs = [int(pixel["x"]) for pixel in pixels]
        ys = [int(pixel["y"]) for pixel in pixels]
        bounds: dict[str, int] | None = {
            "min_x": min(xs), "min_y": min(ys), "max_x": max(xs), "max_y": max(ys),
        }
    else:
        bounds = None
    cells: dict[tuple[int, int], Counter[str]] = defaultdict(Counter)
    for pixel in pixels:
        grid_x = min(grid_size - 1, int(pixel["x"]) * grid_size // width)
        grid_y = min(grid_size - 1, int(pixel["y"]) * grid_size // height)
        cells[(grid_x, grid_y)][COLOR_CHARACTER.get(str(pixel["color"]), "?")] += 1
    rows = []
    for y in range(grid_size):
        rows.append("".join(cells[(x, y)].most_common(1)[0][0] if cells[(x, y)] else "." for x in range(grid_size)))
    return {
        "legend": ".=white R=red B=blue G=green A=amber V=violet",
        "occupied_bounds": bounds,
        "grid_scale": f"each character summarizes {width // grid_size}x{height // grid_size} board pixels",
        "rows": rows,
    }
