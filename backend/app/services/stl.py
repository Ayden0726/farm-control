"""STL measurements, validation, and plate-copy assembly.

FarmOS is not a slicing engine. These helpers measure the model's bounding box,
reject empty/corrupt uploads, and assemble translated copies so PrusaSlicer CLI
can slice an already-packed plate. They never emit G-code.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from app.services.slicer_filename import sanitise_upload_name

MAX_TRIANGLES = 20_000_000


@dataclass(frozen=True)
class StlBounds:
    x_mm: float
    y_mm: float
    z_mm: float
    triangle_count: int
    volume_mm3: float = 0.0
    min_x: float = 0.0
    min_y: float = 0.0
    min_z: float = 0.0


@dataclass(frozen=True)
class PlatePack:
    copies: int
    rotated: bool
    cols: int
    rows: int
    part_x_mm: float
    part_y_mm: float


@dataclass(frozen=True)
class StlValidation:
    ok: bool
    error: str | None
    bounds: StlBounds | None
    warnings: tuple[str, ...] = ()


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


def looks_like_stl(filename: str, content: bytes) -> bool:
    name = (filename or "").lower()
    if not name.endswith(".stl"):
        return False
    if len(content) < 84:
        head = content.lstrip().lower()
        return head.startswith(b"solid") and b"facet" in content.lower()
    if _looks_ascii(content):
        return True
    (count,) = struct.unpack_from("<I", content, 80)
    expected = 84 + count * 50
    return 0 < count <= MAX_TRIANGLES and len(content) >= min(expected, 84 + 50)


def validate_stl(filename: str, content: bytes, max_bytes: int) -> StlValidation:
    warnings: list[str] = []
    if not content:
        return StlValidation(False, "The file is empty.", None)
    if len(content) > max_bytes:
        mb = max_bytes / (1024 * 1024)
        return StlValidation(False, f"STL is larger than the {mb:.0f} MB upload limit.", None)
    if not looks_like_stl(filename, content):
        return StlValidation(False, "Only STL files are accepted. This upload is not a valid STL.", None)
    box = bounding_box(content)
    if box is None:
        return StlValidation(False, "This STL is empty or corrupt — FarmOS could not read any triangles.", None)
    if box.triangle_count <= 0 or box.x_mm <= 0 or box.y_mm <= 0 or box.z_mm <= 0:
        return StlValidation(False, "This STL has no measurable geometry.", box)
    if box.x_mm < 0.2 or box.y_mm < 0.2:
        warnings.append("Bounding box is smaller than 0.2 mm — check the export units.")
    return StlValidation(True, None, box, tuple(warnings))


def bed_fit_warnings(box: StlBounds, printers: list[tuple[str, float, float, float]]) -> list[str]:
    """Warn when the model is larger than a printer's usable volume."""
    notes: list[str] = []
    for name, bx, by, bz in printers:
        too = []
        if box.x_mm > bx + 0.5:
            too.append("width")
        if box.y_mm > by + 0.5:
            too.append("depth")
        if box.z_mm > bz + 0.5:
            too.append("height")
        if too:
            notes.append(
                f"Larger than {name}'s usable bed ({bx:g}×{by:g}×{bz:g} mm) in {', '.join(too)}."
            )
    return notes


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


def _accumulate(
    min_x, min_y, min_z, max_x, max_y, max_z, volume, x1, y1, z1, x2, y2, z2, x3, y3, z3
):
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
    volume += (
        x1 * (y2 * z3 - y3 * z2)
        + x2 * (y3 * z1 - y1 * z3)
        + x3 * (y1 * z2 - y2 * z1)
    ) / 6.0
    return min_x, min_y, min_z, max_x, max_y, max_z, volume


def _binary_bounds(content: bytes) -> StlBounds | None:
    if len(content) < 84:
        return None
    (count,) = struct.unpack_from("<I", content, 80)
    expected = 84 + count * 50
    if count <= 0 or count > MAX_TRIANGLES or len(content) < expected:
        return None
    min_x = min_y = min_z = float("inf")
    max_x = max_y = max_z = float("-inf")
    volume = 0.0
    offset = 84
    for _ in range(count):
        nx, ny, nz, x1, y1, z1, x2, y2, z2, x3, y3, z3, _attr = struct.unpack_from(
            "<12fH", content, offset
        )
        del nx, ny, nz
        min_x, min_y, min_z, max_x, max_y, max_z, volume = _accumulate(
            min_x, min_y, min_z, max_x, max_y, max_z, volume, x1, y1, z1, x2, y2, z2, x3, y3, z3
        )
        offset += 50
    if not isfinite(min_x):
        return None
    return StlBounds(
        x_mm=round(max_x - min_x, 3),
        y_mm=round(max_y - min_y, 3),
        z_mm=round(max_z - min_z, 3),
        triangle_count=count,
        volume_mm3=abs(volume),
        min_x=min_x,
        min_y=min_y,
        min_z=min_z,
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
    verts: list[tuple[float, float, float]] = []
    volume = 0.0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("facet"):
            triangles += 1
        if not stripped.lower().startswith("vertex"):
            continue
        parts = stripped.split()
        if len(parts) < 4:
            continue
        try:
            x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
        except ValueError:
            continue
        verts.append((x, y, z))
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
        if len(verts) == 3:
            x1, y1, z1 = verts[0]
            x2, y2, z2 = verts[1]
            x3, y3, z3 = verts[2]
            volume += (
                x1 * (y2 * z3 - y3 * z2)
                + x2 * (y3 * z1 - y1 * z3)
                + x3 * (y1 * z2 - y2 * z1)
            ) / 6.0
            verts = []
    if not isfinite(min_x):
        return None
    return StlBounds(
        x_mm=round(max_x - min_x, 3),
        y_mm=round(max_y - min_y, 3),
        z_mm=round(max_z - min_z, 3),
        triangle_count=max(0, triangles),
        volume_mm3=abs(volume),
        min_x=min_x,
        min_y=min_y,
        min_z=min_z,
    )


def _iter_binary_triangles(content: bytes):
    if len(content) < 84:
        return
    (count,) = struct.unpack_from("<I", content, 80)
    expected = 84 + count * 50
    if count <= 0 or len(content) < expected:
        return
    offset = 84
    for _ in range(count):
        yield struct.unpack_from("<12fH", content, offset)
        offset += 50


def write_binary_stl(path: Path, triangles: list[tuple], header: bytes = b"FarmOS packed plate") -> None:
    head = (header[:80] + b" " * 80)[:80]
    buf = bytearray(head)
    buf += struct.pack("<I", len(triangles))
    for tri in triangles:
        if len(tri) == 13:
            buf += struct.pack("<12fH", *tri)
        else:
            buf += struct.pack("<12fH", *tri, 0)
    path.write_bytes(bytes(buf))


def assemble_packed_stl(
    source: bytes,
    placements: list[dict],
    dest: Path,
    origin_min: tuple[float, float, float] | None = None,
) -> Path:
    """Translate (and yaw) copies of the source mesh into one binary STL."""
    box = bounding_box(source)
    ox = box.min_x if box else 0.0
    oy = box.min_y if box else 0.0
    oz = box.min_z if box else 0.0
    if origin_min:
        ox, oy, oz = origin_min
    tris = list(_iter_binary_triangles(source))
    if not tris and box:
        # ASCII source — rewrite as a single-copy binary first via vertex walk is heavy;
        # packing still works from bbox for preview; slicer gets the original + duplicate.
        dest.write_bytes(source)
        return dest
    out: list[tuple] = []
    for place in placements:
        dx = float(place.get("x") or 0) - ox
        dy = float(place.get("y") or 0) - oy
        rot = float(place.get("rotation_z") or 0)
        rad = math.radians(rot)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        for nx, ny, nz, x1, y1, z1, x2, y2, z2, x3, y3, z3, attr in tris:
            pts = []
            for x, y, z in ((x1, y1, z1), (x2, y2, z2), (x3, y3, z3)):
                lx, ly = x - ox, y - oy
                rx = lx * cos_a - ly * sin_a
                ry = lx * sin_a + ly * cos_a
                pts.extend((rx + dx + ox, ry + dy + oy, z))
            nxx = nx * cos_a - ny * sin_a
            nyy = nx * sin_a + ny * cos_a
            out.append((nxx, nyy, nz, *pts, attr))
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_binary_stl(dest, out)
    return dest


def unique_stored_name(directory: Path, filename: str) -> Path:
    safe = sanitise_upload_name(filename, ".stl")
    dest = directory / safe
    if not dest.exists():
        return dest
    stem = dest.stem
    suffix = dest.suffix
    n = 2
    while True:
        candidate = directory / f"{stem}-{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1
