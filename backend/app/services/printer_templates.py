"""Save and apply printer geometry / nozzle templates."""

from __future__ import annotations

from typing import Any

from app.models import Printer

SNAPSHOT_KEYS = (
    "model",
    "adapter_type",
    "build_x_mm",
    "build_y_mm",
    "build_z_mm",
    "usable_x_mm",
    "usable_y_mm",
    "usable_z_mm",
    "nozzle_diameter_mm",
    "nozzle_material",
    "supported_materials",
    "max_nozzle_temp_c",
    "max_bed_temp_c",
    "build_plate_type",
    "slicer_profile",
    "firmware",
    "filament_diameter_mm",
    "bed_shape",
    "bed_origin",
    "keepout_polygons",
    "max_speed_mm_s",
    "max_accel_mm_s2",
    "max_volumetric_mm3_s",
    "unattended_mode",
    "avg_power_watts",
    "machine_rate_per_hour",
    "maintenance_interval_hours",
)


def printer_snapshot(printer: Printer) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in SNAPSHOT_KEYS:
        value = getattr(printer, key, None)
        if key == "adapter_type":
            value = value.value if hasattr(value, "value") else value
        if key == "supported_materials":
            value = list(value or [])
        if key == "keepout_polygons":
            value = list(value or [])
        out[key] = value
    return out


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def apply_snapshot(target: Any, snapshot: dict[str, Any] | None, *, only_empty: bool = False) -> None:
    """Copy template fields onto a Printer or a mutable mapping/namespace."""
    if not snapshot:
        return
    for key in SNAPSHOT_KEYS:
        if key not in snapshot or key == "adapter_type":
            continue
        value = snapshot[key]
        if value is None:
            continue
        if only_empty:
            current = getattr(target, key, None) if not isinstance(target, dict) else target.get(key)
            if not _empty(current):
                continue
        if isinstance(target, dict):
            target[key] = value
        else:
            setattr(target, key, value)
