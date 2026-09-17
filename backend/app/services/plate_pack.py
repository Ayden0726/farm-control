"""2D nest for production plates. Not a slicer — placements only.

Uses MaxRects with per-copy 0°/90° Z rotation. Does not flip a part onto
another face. Spacing is between copies, not around the outside of the plate
(same identity as n*part + (n-1)*gap <= bed).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import inf

MIN_SPACING_MM = 2.0
MAX_SPACING_MM = 30.0
DEFAULT_SPACING_MM = 6.0
RELIABLE_SPACING_MM = 12.0


@dataclass(frozen=True)
class OrientationRules:
    preferred_z_deg: float = 0.0
    allowed_z_rotations: tuple[float, ...] = (0.0, 90.0)
    lock: bool = False
    step_deg: float = 90.0
    auto_rotate: bool = True
    allow_mirror: bool = False


@dataclass
class PlacedPart:
    index: int
    x: float
    y: float
    w: float
    h: float
    rotation_z: float
    stl_id: str | None = None


@dataclass
class PackResult:
    placed: list[PlacedPart]
    quantity: int
    spacing_mm: float
    utilisation: float
    max_quantity: int
    bed_w: float
    bed_h: float
    part_w: float
    part_h: float
    brim_mm: float
    warnings: list[str] = field(default_factory=list)
    keepouts: list[dict[str, float]] = field(default_factory=list)

    def as_json(self) -> dict:
        return {
            "placed": [asdict(p) for p in self.placed],
            "quantity": self.quantity,
            "spacing_mm": self.spacing_mm,
            "utilisation": round(self.utilisation, 4),
            "max_quantity": self.max_quantity,
            "bed_w": self.bed_w,
            "bed_h": self.bed_h,
            "part_w": self.part_w,
            "part_h": self.part_h,
            "brim_mm": self.brim_mm,
            "warnings": list(self.warnings),
            "keepouts": list(self.keepouts),
        }


def clamp_spacing(spacing_mm: float, min_safe: float = MIN_SPACING_MM) -> float:
    gap = float(spacing_mm)
    floor = max(MIN_SPACING_MM, float(min_safe))
    return min(MAX_SPACING_MM, max(floor, gap))


def copies_to_pack(quantity: int | None, fill_plate: bool, max_q: int) -> int:
    """How many copies to nest on this plate.

    A full plate is `fill_plate` or an omitted quantity — that is the right end
    of the slicer parts slider. A specific count is packed as requested; geometry
    may still cap it inside `pack_copies`.
    """
    if fill_plate or quantity is None:
        return max(0, int(max_q))
    return max(0, int(quantity))


def spacing_hint(spacing_mm: float, recommended_mm: float = DEFAULT_SPACING_MM) -> str:
    rec = max(MIN_SPACING_MM, float(recommended_mm or DEFAULT_SPACING_MM))
    if spacing_mm <= rec - 1.5:
        return "Tight"
    if spacing_mm >= rec + 4 or spacing_mm >= RELIABLE_SPACING_MM:
        return "Conservative"
    return "Recommended"


def _aabb_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float], gap: float) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (
        ax + aw + gap <= bx + 1e-6
        or bx + bw + gap <= ax + 1e-6
        or ay + ah + gap <= by + 1e-6
        or by + bh + gap <= ay + 1e-6
    )


def _inside(part: tuple[float, float, float, float], bed_w: float, bed_h: float) -> bool:
    x, y, w, h = part
    return x >= -1e-6 and y >= -1e-6 and x + w <= bed_w + 1e-6 and y + h <= bed_h + 1e-6


def _allowed_sizes(part_w: float, part_h: float, rules: OrientationRules) -> list[tuple[float, float, float]]:
    """Return (w, h, rotation_z) candidates. Never mirrors."""
    if rules.lock or not rules.auto_rotate:
        rot = float(rules.preferred_z_deg) % 180.0
        if rot in (90.0, -90.0, 270.0):
            return [(part_h, part_w, 90.0)]
        return [(part_w, part_h, 0.0)]
    allowed = rules.allowed_z_rotations or (0.0, 90.0)
    out: list[tuple[float, float, float]] = []
    seen: set[tuple[float, float]] = set()
    for raw in allowed:
        deg = float(raw) % 360.0
        if deg in (90.0, 270.0):
            size = (part_h, part_w, 90.0)
        elif deg in (0.0, 180.0):
            size = (part_w, part_h, 0.0 if deg == 0.0 else 180.0)
        else:
            continue
        key = (round(size[0], 4), round(size[1], 4))
        if key in seen:
            continue
        seen.add(key)
        out.append(size)
    return out or [(part_w, part_h, 0.0)]


def _split_free(free: tuple[float, float, float, float], used: tuple[float, float, float, float]) -> list[tuple[float, float, float, float]]:
    fx, fy, fw, fh = free
    ux, uy, uw, uh = used
    if ux >= fx + fw or uy >= fy + fh or ux + uw <= fx or uy + uh <= fy:
        return [free]
    pieces: list[tuple[float, float, float, float]] = []
    if ux > fx:
        pieces.append((fx, fy, ux - fx, fh))
    if ux + uw < fx + fw:
        pieces.append((ux + uw, fy, fx + fw - (ux + uw), fh))
    if uy > fy:
        pieces.append((fx, fy, fw, uy - fy))
    if uy + uh < fy + fh:
        pieces.append((fx, uy + uh, fw, fy + fh - (uy + uh)))
    return [p for p in pieces if p[2] > 0.5 and p[3] > 0.5]


def pack_copies(
    part_w: float,
    part_h: float,
    bed_w: float,
    bed_h: float,
    quantity: int,
    spacing_mm: float = DEFAULT_SPACING_MM,
    brim_mm: float = 0.0,
    keepouts: list[dict[str, float]] | None = None,
    rules: OrientationRules | None = None,
    stl_id: str | None = None,
) -> PackResult:
    rules = rules or OrientationRules()
    gap = clamp_spacing(spacing_mm)
    brim = max(0.0, float(brim_mm))
    keepouts = list(keepouts or [])
    qty = max(0, int(quantity))
    footprint_w = part_w + 2 * brim
    footprint_h = part_h + 2 * brim
    sizes = _allowed_sizes(footprint_w, footprint_h, rules)
    warnings: list[str] = []
    if not sizes or all(w > bed_w + 1e-6 or h > bed_h + 1e-6 for w, h, _ in sizes):
        return PackResult(
            placed=[],
            quantity=0,
            spacing_mm=gap,
            utilisation=0.0,
            max_quantity=0,
            bed_w=bed_w,
            bed_h=bed_h,
            part_w=part_w,
            part_h=part_h,
            brim_mm=brim,
            warnings=["Model is larger than this printer's usable bed."],
            keepouts=keepouts,
        )

    # Pack inflated rects into an inflated bin so gap is between copies only.
    bin_w = bed_w + gap
    bin_h = bed_h + gap
    obstacles: list[tuple[float, float, float, float]] = []
    for box in keepouts:
        obstacles.append((float(box["x"]), float(box["y"]), float(box["w"]) + gap, float(box["h"]) + gap))

    def try_pack(n: int) -> list[PlacedPart]:
        free: list[tuple[float, float, float, float]] = [(0.0, 0.0, bin_w, bin_h)]
        placed: list[PlacedPart] = []
        for obs in obstacles:
            nxt: list[tuple[float, float, float, float]] = []
            for fr in free:
                nxt.extend(_split_free(fr, obs))
            free = nxt
        for i in range(n):
            best: tuple[float, tuple[float, float, float, float], tuple[float, float, float]] | None = None
            for fr in free:
                fx, fy, fw, fh = fr
                for w, h, rot in sizes:
                    rw, rh = w + gap, h + gap
                    if rw <= fw + 1e-6 and rh <= fh + 1e-6:
                        leftover = min(fw - rw, fh - rh)
                        cand = (leftover, (fx, fy, rw, rh), (w, h, rot))
                        if best is None or leftover < best[0] or (leftover == best[0] and fx + fy < best[1][0] + best[1][1]):
                            best = cand
            if best is None:
                return placed
            _, used, (w, h, rot) = best
            ux, uy, _, _ = used
            actual = (ux, uy, w, h)
            if not _inside(actual, bed_w, bed_h):
                return placed
            blocked = False
            for obs in keepouts:
                ox, oy, ow, oh = float(obs["x"]), float(obs["y"]), float(obs["w"]), float(obs["h"])
                if _aabb_overlap(actual, (ox, oy, ow, oh), gap):
                    blocked = True
                    break
            if blocked:
                nxt = []
                for fr in free:
                    nxt.extend(_split_free(fr, used))
                free = nxt
                continue
            placed.append(
                PlacedPart(index=i, x=round(ux, 3), y=round(uy, 3), w=round(w, 3), h=round(h, 3), rotation_z=rot, stl_id=stl_id)
            )
            nxt = []
            for fr in free:
                nxt.extend(_split_free(fr, used))
            free = nxt
        return placed

    # Upper bound from area, then binary-search max that actually nests.
    area_part = min((w + gap) * (h + gap) for w, h, _ in sizes)
    area_bed = max(1.0, bin_w * bin_h)
    area_cap = int(area_bed // max(area_part, 1.0))
    hi = max(area_cap, 1)
    lo = 0
    best_placed: list[PlacedPart] = []
    while lo < hi:
        mid = (lo + hi + 1) // 2
        got = try_pack(mid)
        if len(got) >= mid:
            lo = mid
            best_placed = got
        else:
            hi = mid - 1
            if len(got) > len(best_placed):
                best_placed = got
    max_qty = lo
    if qty <= 0:
        placed = []
    elif qty <= max_qty:
        placed = try_pack(qty)
        if len(placed) < qty:
            placed = best_placed[:qty]
    else:
        placed = best_placed
        warnings.append(f"Only {max_qty} copies fit on this bed at {gap:g} mm spacing.")
    occ = sum(p.w * p.h for p in placed)
    util = occ / max(bed_w * bed_h, 1.0)
    return PackResult(
        placed=placed,
        quantity=len(placed),
        spacing_mm=gap,
        utilisation=util,
        max_quantity=max_qty,
        bed_w=bed_w,
        bed_h=bed_h,
        part_w=part_w,
        part_h=part_h,
        brim_mm=brim,
        warnings=warnings,
        keepouts=keepouts,
    )


def max_quantity(
    part_w: float,
    part_h: float,
    bed_w: float,
    bed_h: float,
    spacing_mm: float = DEFAULT_SPACING_MM,
    brim_mm: float = 0.0,
    keepouts: list[dict[str, float]] | None = None,
    rules: OrientationRules | None = None,
) -> int:
    return pack_copies(part_w, part_h, bed_w, bed_h, 10_000, spacing_mm, brim_mm, keepouts, rules).max_quantity


def validate_plate(result: PackResult, extra_keepouts: list[dict[str, float]] | None = None) -> list[str]:
    errors: list[str] = []
    keepouts = list(result.keepouts) + list(extra_keepouts or [])
    for i, a in enumerate(result.placed):
        box_a = (a.x, a.y, a.w, a.h)
        if not _inside(box_a, result.bed_w, result.bed_h):
            errors.append(f"Part {i + 1} sits outside the printable region.")
        for j, b in enumerate(result.placed):
            if j <= i:
                continue
            if _aabb_overlap(box_a, (b.x, b.y, b.w, b.h), result.spacing_mm):
                errors.append(f"Parts {i + 1} and {j + 1} overlap or are closer than {result.spacing_mm:g} mm.")
        for k, obs in enumerate(keepouts):
            if _aabb_overlap(box_a, (float(obs["x"]), float(obs["y"]), float(obs["w"]), float(obs["h"])), result.spacing_mm):
                errors.append(f"Part {i + 1} intersects a keep-out / clip zone.")
    if result.quantity <= 0:
        errors.append("No parts fit on this plate.")
    return errors


def even_plate_counts(needed: int, max_per_plate: int) -> list[int]:
    """Split quantity across plates without a leftover of 1 when the mode cares."""
    need = max(0, int(needed))
    cap = max(1, int(max_per_plate))
    if need == 0:
        return []
    plates = (need + cap - 1) // cap
    base = need // plates
    extra = need % plates
    counts = [base + (1 if i < extra else 0) for i in range(plates)]
    return [c for c in counts if c > 0]


def greedy_plate_counts(needed: int, max_per_plate: int) -> list[int]:
    need = max(0, int(needed))
    cap = max(1, int(max_per_plate))
    counts: list[int] = []
    while need > 0:
        take = min(cap, need)
        counts.append(take)
        need -= take
    return counts


def plan_plates(
    needed: int,
    max_per_plate: int,
    mode: str = "balanced",
) -> list[int]:
    mode = (mode or "balanced").lower()
    if mode in {"minimum_bed_clears", "min_clears", "fastest_print"}:
        return even_plate_counts(needed, max_per_plate)
    return greedy_plate_counts(needed, max_per_plate)


def candidate_layouts(
    part_w: float,
    part_h: float,
    bed_w: float,
    bed_h: float,
    needed: int,
    recommended_spacing: float,
    brim_mm: float = 0.0,
    keepouts: list[dict[str, float]] | None = None,
    rules: OrientationRules | None = None,
) -> list[dict]:
    rec = clamp_spacing(recommended_spacing)
    tight = clamp_spacing(max(MIN_SPACING_MM, rec - 2))
    conservative = clamp_spacing(max(rec + 4, RELIABLE_SPACING_MM))
    rows: list[dict] = []
    for label, gap in (("tight", tight), ("recommended", rec), ("conservative", conservative)):
        packed = pack_copies(part_w, part_h, bed_w, bed_h, 10_000, gap, brim_mm, keepouts, rules)
        max_q = packed.max_quantity
        if max_q <= 0:
            continue
        greedy = greedy_plate_counts(needed, max_q)
        even = even_plate_counts(needed, max_q)
        rows.append(
            {
                "label": label,
                "spacing_mm": gap,
                "max_per_plate": max_q,
                "utilisation": packed.utilisation,
                "greedy_plates": greedy,
                "even_plates": even,
                "greedy_plate_count": len(greedy),
                "even_plate_count": len(even),
            }
        )
    return rows


def pick_layout(candidates: list[dict], mode: str, needed: int) -> dict | None:
    if not candidates:
        return None
    mode = (mode or "balanced").lower()
    if mode in {"maximum_parts", "max_parts"}:
        return min(candidates, key=lambda c: (-c["max_per_plate"], c["spacing_mm"]))
    if mode in {"maximum_reliability", "reliability"}:
        return max(candidates, key=lambda c: (c["spacing_mm"], -c["even_plate_count"]))
    if mode in {"minimum_bed_clears", "min_clears"}:
        return min(candidates, key=lambda c: (c["even_plate_count"], -c["max_per_plate"]))
    if mode in {"fastest_print", "fastest"}:
        return min(candidates, key=lambda c: (c["even_plate_count"], -c["max_per_plate"], c["spacing_mm"]))
    # balanced
    rec = [c for c in candidates if c["label"] == "recommended"]
    return rec[0] if rec else candidates[0]


def orientation_from_json(raw: dict | None) -> OrientationRules:
    data = raw or {}
    allowed = data.get("allowed_z_rotations") or (0.0, 90.0)
    try:
        allowed_t = tuple(float(x) for x in allowed)
    except (TypeError, ValueError):
        allowed_t = (0.0, 90.0)
    return OrientationRules(
        preferred_z_deg=float(data.get("preferred_z_deg") or 0),
        allowed_z_rotations=allowed_t,
        lock=bool(data.get("lock")),
        step_deg=float(data.get("step_deg") or 90),
        auto_rotate=bool(data.get("auto_rotate", True)),
        allow_mirror=False,
    )
