"""Default versioned slicer profiles and printer geometry backfill."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Printer, SlicerProfile
from app.services.gcode_meta import _DENSITY_G_CM3
from app.services.printer_geometry import apply_printer_geometry_defaults

_DEFAULTS = [
    {
        "name": "PETG 0.4 mm — production",
        "material": "PETG",
        "nozzle_mm": 0.4,
        "density_g_cm3": 1.27,
        "layer_height_mm": 0.2,
        "first_layer_height_mm": 0.2,
        "perimeters": 3,
        "infill_percent": 20,
        "nozzle_temp_c": 250,
        "bed_temp_c": 80,
        "brim_width_mm": 0,
        "print_speed_mm_s": 80,
        "notes": "Farm default PETG profile. Duplicate it before changing production settings.",
    },
    {
        "name": "PLA 0.4 mm — production",
        "material": "PLA",
        "nozzle_mm": 0.4,
        "density_g_cm3": 1.24,
        "layer_height_mm": 0.2,
        "first_layer_height_mm": 0.2,
        "perimeters": 3,
        "infill_percent": 15,
        "nozzle_temp_c": 210,
        "bed_temp_c": 60,
        "brim_width_mm": 0,
        "print_speed_mm_s": 80,
        "notes": "Farm default PLA profile.",
    },
    {
        "name": "PETG 0.6 mm — production",
        "material": "PETG",
        "nozzle_mm": 0.6,
        "density_g_cm3": 1.27,
        "layer_height_mm": 0.28,
        "first_layer_height_mm": 0.28,
        "perimeters": 3,
        "infill_percent": 20,
        "nozzle_temp_c": 250,
        "bed_temp_c": 80,
        "brim_width_mm": 0,
        "print_speed_mm_s": 70,
        "notes": "Only for printers with a 0.6 mm nozzle.",
    },
]


async def ensure_slicer_defaults(db: AsyncSession) -> None:
    printers = (await db.execute(select(Printer))).scalars().all()
    dirty = False
    for printer in printers:
        if apply_printer_geometry_defaults(printer):
            dirty = True
        if not printer.supported_materials:
            printer.supported_materials = ["PETG", "PLA"]
            dirty = True
    existing = (await db.execute(select(SlicerProfile).limit(1))).scalar_one_or_none()
    if existing:
        if dirty:
            await db.flush()
        return
    for spec in _DEFAULTS:
        db.add(SlicerProfile(**spec))
    await db.flush()


def density_from_material(material: str | None, fallback: float = 1.24) -> float:
    key = (material or "").strip().lower()
    return float(_DENSITY_G_CM3.get(key, fallback))
