"""Farm-wide AppSetting helpers (automation + plate packing)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting

DEFAULT_PACK_BED_X_MM = 220.0
DEFAULT_PACK_BED_Y_MM = 220.0
DEFAULT_PACK_GAP_MM = 8.0


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _as_float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return number


async def get_automation(db: AsyncSession) -> dict[str, Any]:
    ejection = await db.get(AppSetting, "auto_part_ejection")
    pack = await db.get(AppSetting, "plate_pack")
    pack_val = pack.value if pack and isinstance(pack.value, dict) else {}
    bed_x = max(1.0, _as_float(pack_val.get("bed_x_mm"), DEFAULT_PACK_BED_X_MM))
    bed_y = max(1.0, _as_float(pack_val.get("bed_y_mm"), DEFAULT_PACK_BED_Y_MM))
    gap = max(0.0, _as_float(pack_val.get("gap_mm"), DEFAULT_PACK_GAP_MM))
    return {
        "auto_part_ejection": _as_bool(ejection.value if ejection else False, False),
        "pack_bed_x_mm": round(bed_x, 1),
        "pack_bed_y_mm": round(bed_y, 1),
        "pack_gap_mm": round(gap, 1),
    }


async def auto_part_ejection_enabled(db: AsyncSession) -> bool:
    row = await db.get(AppSetting, "auto_part_ejection")
    return _as_bool(row.value if row else False, False)


async def upsert_automation(
    db: AsyncSession,
    *,
    auto_part_ejection: bool | None = None,
    pack_bed_x_mm: float | None = None,
    pack_bed_y_mm: float | None = None,
    pack_gap_mm: float | None = None,
) -> dict[str, Any]:
    current = await get_automation(db)
    if auto_part_ejection is not None:
        row = await db.get(AppSetting, "auto_part_ejection")
        if row:
            row.value = bool(auto_part_ejection)
        else:
            db.add(AppSetting(key="auto_part_ejection", value=bool(auto_part_ejection)))
        current["auto_part_ejection"] = bool(auto_part_ejection)
    pack_changed = any(v is not None for v in (pack_bed_x_mm, pack_bed_y_mm, pack_gap_mm))
    if pack_changed:
        payload = {
            "bed_x_mm": max(1.0, float(pack_bed_x_mm if pack_bed_x_mm is not None else current["pack_bed_x_mm"])),
            "bed_y_mm": max(1.0, float(pack_bed_y_mm if pack_bed_y_mm is not None else current["pack_bed_y_mm"])),
            "gap_mm": max(0.0, float(pack_gap_mm if pack_gap_mm is not None else current["pack_gap_mm"])),
        }
        row = await db.get(AppSetting, "plate_pack")
        if row:
            row.value = payload
        else:
            db.add(AppSetting(key="plate_pack", value=payload))
        current["pack_bed_x_mm"] = round(payload["bed_x_mm"], 1)
        current["pack_bed_y_mm"] = round(payload["bed_y_mm"], 1)
        current["pack_gap_mm"] = round(payload["gap_mm"], 1)
    return current
