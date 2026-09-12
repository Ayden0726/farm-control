"""STL measurements and a conservative plate-packing estimate.

FarmOS is not a slicer. These helpers measure the model's axis-aligned bounding
box and estimate how many copies fit in a regular grid. They never emit G-code.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class StlBounds:
    x_mm: float
    y_mm: float
    z_mm: float
    triangle_count: int


@dataclass(frozen=True)
class PlatePack:
    copies: int
    rotated: bool
    cols: int
    rows: int
    part_x_mm: float
    part_y_mm: float


def copies_on_plate(
    part_x_mm: float,
    part_y_mm: float,
    bed_x_mm: float,
    bed_y_mm: float,
    gap_mm: float = 8.0,
) -> PlatePack:
    """How many copies fit in a regular grid, trying a 90° rotation.

    Spacing is applied between copies, not around the outside of the plate.
    n * part + (n - 1) * gap <= bed  →  n <= (bed + gap) / (part + gap)
    """
    gap = max(0.0, float(gap_mm))

    def grid(px: float, py: float) -> tuple[int, int, int]:
        if px <= 0 or py <= 0 or bed_x_mm <= 0 or bed_y_mm <= 0:
            return 0, 0, 0
        if px > bed_x_mm + 1e-6 or py > bed_y_mm + 1e-6:
            return 0, 0, 0
        cols = int((bed_x_mm + gap) // (px + gap))
        rows = int((bed_y_mm + gap) // (py + gap))
        cols = max(0, cols)
        rows = max(0, rows)
        return cols * rows, cols, rows

    n, cols, rows = grid(part_x_mm, part_y_mm)
    nr, colsr, rowsr = grid(part_y_mm, part_x_mm)
    if nr > n:
        return PlatePack(
            copies=nr,
            rotated=True,
            cols=colsr,
            rows=rowsr,
            part_x_mm=part_y_mm,
            part_y_mm=part_x_mm,
        )
    return PlatePack(
        copies=n,
        rotated=False,
        cols=cols,
        rows=rows,
        part_x_mm=part_x_mm,
        part_y_mm=part_y_mm,
    )


def bounding_box(content: bytes) -> StlBounds | None:
    if len(content) < 84:
        ascii_box = _ascii_bounds(content)
        return ascii_box
    if _looks_ascii(content):
        box = _ascii_bounds(content)
        if box:
            return box
    return _binary_bounds(content) or _ascii_bounds(content)


def _looks_ascii(content: bytes) -> bool:
    head = content[:200].lstrip().lower()
    if not head.startswith(b"solid"):
        return False
    sample = content[:8000].lower()
    return b"facet" in sample and b"vertex" in sample


def _binary_bounds(content: bytes) -> StlBounds | None:
    if len(content) < 84:
        return None
    (count,) = struct.unpack_from("<I", content, 80)
    expected = 84 + count * 50
    if count <= 0 or count > 20_000_000 or len(content) < expected:
        return None
    min_x = min_y = min_z = float("inf")
    max_x = max_y = max_z = float("-inf")
    offset = 84
    for _ in range(count):
        # skip 3-float normal, read 9-float vertices, skip attribute
        nx, ny, nz, x1, y1, z1, x2, y2, z2, x3, y3, z3, _attr = struct.unpack_from(
            "<12fH", content, offset
        )
        del nx, ny, nz
        for x, y, z in ((x1, y1, z1), (x2, y2, z2), (x3, y3, z3)):
            if x < min_x:
                min_x = x
            if y < min_y:
                min_y = y
            if z < min_z:
                min_z = z
            if x > max_x:
                max_x = x
            if y > max_y:
                max_y = y
            if z > max_z:
                max_z = z
        offset += 50
    if not isfinite(min_x):
        return None
    return StlBounds(
        x_mm=round(max_x - min_x, 3),
        y_mm=round(max_y - min_y, 3),
        z_mm=round(max_z - min_z, 3),
        triangle_count=count,
    )


def _ascii_bounds(content: bytes) -> StlBounds | None:
    try:
        text = content.decode("utf-8", errors="ignore")
    except Exception:
        return None
    if "vertex" not in text.lower():
        return None
    min_x = min_y = min_z = float("inf")
    max_x = max_y = max_z = float("-inf")
    triangles = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.lower().startswith("vertex"):
            if stripped.lower().startswith("facet"):
                triangles += 1
            continue
        parts = stripped.split()
        if len(parts) < 4:
            continue
        try:
            x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
        except ValueError:
            continue
        if x < min_x:
            min_x = x
        if y < min_y:
            min_y = y
        if z < min_z:
            min_z = z
        if x > max_x:
            max_x = x
        if y > max_y:
            max_y = y
        if z > max_z:
            max_z = z
    if not isfinite(min_x):
        return None
    return StlBounds(
        x_mm=round(max_x - min_x, 3),
        y_mm=round(max_y - min_y, 3),
        z_mm=round(max_z - min_z, 3),
        triangle_count=max(0, triangles),
    )
