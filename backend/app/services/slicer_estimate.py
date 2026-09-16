"""Pre-slice filament/time estimates. Labelled separately from sliced G-code stats."""

from __future__ import annotations

from app.models import SlicerProfile, StlFile
from app.services.gcode_meta import _DENSITY_G_CM3, _grams_from_length_mm


def density_for(material: str | None, profile: SlicerProfile | None = None) -> float:
    if profile and profile.density_g_cm3 and float(profile.density_g_cm3) > 0.4:
        return float(profile.density_g_cm3)
    key = (material or (profile.material if profile else "") or "petg").strip().lower()
    return float(_DENSITY_G_CM3.get(key, 1.24))


def pre_slice_estimate(
    stl: StlFile,
    quantity: int,
    profile: SlicerProfile | None,
    material: str | None = None,
) -> dict:
    """Rough estimate from mesh volume / bbox. Not a substitute for PrusaSlicer."""
    qty = max(1, int(quantity or 1))
    density = density_for(material, profile)
    infill = float(profile.infill_percent if profile else 20) / 100.0
    perimeters = int(profile.perimeters if profile else 3)
    layer = float(profile.layer_height_mm if profile else 0.2) or 0.2
    speed = float(profile.print_speed_mm_s if profile else 80) or 80
    vol_mm3 = float(stl.volume_mm3 or 0)
    if vol_mm3 <= 0 and stl.bbox_x_mm and stl.bbox_y_mm and stl.bbox_z_mm:
        vol_mm3 = float(stl.bbox_x_mm) * float(stl.bbox_y_mm) * float(stl.bbox_z_mm) * 0.35
    # Solid fraction: infill plus a crude wall allowance.
    wall_frac = min(0.45, 0.04 * perimeters)
    solid = min(0.95, max(0.08, infill * 0.9 + wall_frac))
    cm3 = (vol_mm3 * solid * qty) / 1000.0
    grams = cm3 * density
    # Time: volume / (speed * layer * line width heuristic)
    line = float(profile.nozzle_mm if profile else 0.4) or 0.4
    mm3_s = max(0.5, speed * layer * line * 0.6)
    seconds = int((vol_mm3 * solid * qty) / mm3_s)
    seconds = max(60, min(seconds, 7 * 86400))
    return {
        "kind": "pre_slice_estimate",
        "label": "Pre-Slice Estimate",
        "note": "Geometry-based guess. Final time and material come from PrusaSlicer after Slice.",
        "filament_grams": round(grams, 2),
        "filament_cm3": round(cm3, 3),
        "seconds": seconds,
        "density_g_cm3": density,
        "quantity": qty,
    }


def grams_from_slicer_meta(meta: dict, density: float, diameter_mm: float = 1.75) -> tuple[float | None, float | None, float | None]:
    """Return (grams, length_mm, volume_cm3) using the selected filament density."""
    volume = meta.get("filament_volume_cm3")
    length = meta.get("filament_length_mm")
    try:
        volume_f = float(volume) if volume is not None else None
    except (TypeError, ValueError):
        volume_f = None
    try:
        length_f = float(length) if length is not None else None
    except (TypeError, ValueError):
        length_f = None
    grams = None
    if volume_f and volume_f > 0:
        grams = volume_f * float(density)
    elif length_f and length_f > 0:
        grams = _grams_from_length_mm(length_f, diameter_mm, float(density))
        radius = max(diameter_mm, 0.1) / 2.0
        volume_f = (3.141592653589793 * radius * radius * length_f) / 1000.0
    elif meta.get("estimated_filament_grams"):
        # Last resort: comments already applied some density; still prefer selected density if volume missing.
        grams = float(meta["estimated_filament_grams"])
    return (
        round(grams, 2) if grams else None,
        round(length_f, 2) if length_f else None,
        round(volume_f, 3) if volume_f else None,
    )
