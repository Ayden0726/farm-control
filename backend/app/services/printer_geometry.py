"""Usable bed geometry for packing and slicer INI — never marketing size alone."""

from __future__ import annotations

from typing import Any

from app.models import Printer

# Marketing build vs a conservative usable area. Used only when the printer
# record has no measured usable_* fields yet.
_MODEL_DEFAULTS: list[tuple[tuple[str, ...], dict[str, Any]]] = [
    (("cr-6 max", "cr6 max"), {"build": (400.0, 400.0, 400.0), "usable": (390.0, 390.0, 390.0), "nozzle": 0.4, "firmware": "marlin"}),
    (("k1 max",), {"build": (300.0, 300.0, 250.0), "usable": (290.0, 290.0, 250.0), "nozzle": 0.4, "firmware": "klipper"}),
    (("k2 pro",), {"build": (350.0, 350.0, 350.0), "usable": (340.0, 340.0, 340.0), "nozzle": 0.4, "firmware": "klipper"}),
    (("voron",), {"build": (350.0, 350.0, 330.0), "usable": (340.0, 340.0, 320.0), "nozzle": 0.4, "firmware": "klipper"}),
    (("cr-6 se", "cr6 se"), {"build": (235.0, 235.0, 250.0), "usable": (225.0, 225.0, 250.0), "nozzle": 0.4, "firmware": "marlin"}),
]


def _model_key(printer: Printer) -> str:
    return f"{printer.model or ''} {printer.name or ''}".lower()


def model_defaults(printer: Printer) -> dict[str, Any] | None:
    key = _model_key(printer)
    for needles, data in _MODEL_DEFAULTS:
        if any(n in key for n in needles):
            return data
    return None


def apply_printer_geometry_defaults(printer: Printer) -> bool:
    """Fill empty slicer fields from the model. Never overwrites a stored value."""
    defaults = model_defaults(printer)
    changed = False
    if printer.build_x_mm is None and defaults:
        printer.build_x_mm, printer.build_y_mm, printer.build_z_mm = defaults["build"]
        changed = True
    if printer.usable_x_mm is None:
        if printer.build_x_mm is not None:
            printer.usable_x_mm = float(printer.build_x_mm)
            changed = True
        elif defaults:
            printer.usable_x_mm = float(defaults["usable"][0])
            changed = True
    if printer.usable_y_mm is None:
        if printer.build_y_mm is not None:
            printer.usable_y_mm = float(printer.build_y_mm)
            changed = True
        elif defaults:
            printer.usable_y_mm = float(defaults["usable"][1])
            changed = True
    if printer.usable_z_mm is None:
        if printer.build_z_mm is not None:
            printer.usable_z_mm = float(printer.build_z_mm)
            changed = True
        elif defaults:
            printer.usable_z_mm = float(defaults["usable"][2])
            changed = True
    if printer.nozzle_diameter_mm is None and defaults:
        printer.nozzle_diameter_mm = float(defaults["nozzle"])
        changed = True
    if not (printer.firmware or "").strip() and defaults:
        printer.firmware = str(defaults["firmware"])
        changed = True
    return changed


def usable_bed(printer: Printer) -> tuple[float, float, float]:
    """Printable W × D × Z in mm. Prefers usable_* over marketing build_*."""
    apply_printer_geometry_defaults(printer)
    x = float(printer.usable_x_mm or printer.build_x_mm or 220)
    y = float(printer.usable_y_mm or printer.build_y_mm or 220)
    z = float(printer.usable_z_mm or printer.build_z_mm or 220)
    return max(1.0, x), max(1.0, y), max(1.0, z)


def keepout_aabbs(printer: Printer) -> list[dict[str, float]]:
    """Simple clip / purge polygons as axis-aligned boxes in bed coordinates."""
    raw = printer.keepout_polygons or []
    boxes: list[dict[str, float]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if "w" in item and "h" in item:
            boxes.append(
                {
                    "x": float(item.get("x") or 0),
                    "y": float(item.get("y") or 0),
                    "w": float(item.get("w") or 0),
                    "h": float(item.get("h") or 0),
                }
            )
            continue
        pts = item.get("points") or item.get("polygon") or []
        if not pts:
            continue
        xs = [float(p[0]) for p in pts]
        ys = [float(p[1]) for p in pts]
        boxes.append(
            {
                "x": min(xs),
                "y": min(ys),
                "w": max(xs) - min(xs),
                "h": max(ys) - min(ys),
            }
        )
    return [b for b in boxes if b["w"] > 0 and b["h"] > 0]


def bed_origin(printer: Printer) -> str:
    origin = (printer.bed_origin or "corner").strip().lower()
    return origin if origin in {"corner", "center"} else "corner"


def bed_shape(printer: Printer) -> str:
    shape = (printer.bed_shape or "rectangular").strip().lower()
    return shape if shape in {"rectangular", "circular"} else "rectangular"
