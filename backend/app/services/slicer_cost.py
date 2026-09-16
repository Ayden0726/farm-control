"""Material and machine cost for a sliced (or pre-sliced) plate."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FilamentProduct, FilamentSpool, Printer, SlicerProfile
from app.services.costing import (
    cost_per_gram_from_profile,
    cost_per_gram_from_spool,
    filament_line_cost,
    select_filament_rate,
)
from app.services.farm_settings import get_mes


def spool_insufficient(spool: FilamentSpool | None, grams: float) -> dict[str, Any]:
    required = float(grams or 0)
    available = float(spool.remaining_weight_g) if spool else 0.0
    ok = bool(spool) and available >= required * 1.08
    reasons = []
    if not spool:
        reasons.append("No spool is assigned to this printer.")
    elif not ok:
        reasons.append(
            f"Insufficient filament. This plate needs {required:.0f} g; "
            f"{spool.public_code or spool.name} has {available:.0f} g remaining."
        )
    return {
        "ok": ok,
        "required_g": required,
        "available_g": available,
        "reasons": reasons,
        "actions": ["change_spool", "choose_printer", "override"] if not ok else [],
        "spool_id": str(spool.id) if spool else None,
        "spool_code": spool.public_code if spool else None,
        "message": "Insufficient Filament" if not ok else "",
    }


async def plate_cost(
    db: AsyncSession,
    *,
    grams: float,
    seconds: int,
    quantity: int,
    printer: Printer | None,
    spool: FilamentSpool | None,
    profile: SlicerProfile | None,
    material: str | None,
) -> dict[str, Any]:
    mes = await get_mes(db)
    filament_profile: FilamentProduct | None = None
    if spool and spool.product:
        filament_profile = spool.product
    elif spool and spool.product_id:
        filament_profile = await db.get(FilamentProduct, spool.product_id)
    spool_rate = None
    if spool:
        spool_rate = cost_per_gram_from_spool(
            cost=spool.cost,
            initial_g=spool.initial_weight_g,
            remaining_g=spool.remaining_weight_g,
            consumed_g=spool.consumed_g,
            cost_per_kg=spool.cost_per_kg,
        )
    profile_rate = None
    if filament_profile:
        profile_rate = cost_per_gram_from_profile(
            normal_price=filament_profile.normal_price,
            purchase_cost=filament_profile.purchase_cost,
            filament_weight_g=filament_profile.filament_weight_g,
            cost_per_kg=filament_profile.cost_per_kg,
        )
    rate_info = select_filament_rate(spool_per_g=spool_rate, profile_per_g=profile_rate)
    line = filament_line_cost(grams if grams > 0 else None, rate_info.get("cost_per_g"))
    hours = (seconds / 3600.0) if seconds else 0.0
    watts = float(printer.avg_power_watts or 180) if printer else 180.0
    electricity = 0.0
    if mes.get("enable_electricity_cost") and hours:
        electricity = hours * (watts / 1000.0) * float(mes.get("electricity_price_per_kwh") or 0)
    machine = 0.0
    if mes.get("enable_machine_cost") and hours and printer:
        machine = hours * float(printer.machine_rate_per_hour or 0)
    labour = hours * float(mes.get("labour_rate_per_hour") or 0) if mes.get("enable_labour_cost") and hours else 0.0
    filament_cost = line.get("filament_cost")
    total = (filament_cost or 0.0) + electricity + machine + labour
    qty = max(1, int(quantity or 1))
    return {
        "filament_cost": round(filament_cost, 4) if filament_cost is not None else None,
        "filament_costed": bool(line.get("costed")),
        "filament_reason": line.get("reason"),
        "cost_per_g": rate_info.get("cost_per_g"),
        "rate_source": rate_info.get("source"),
        "electricity_cost": round(electricity, 4),
        "machine_cost": round(machine, 4),
        "labour_cost": round(labour, 4),
        "total_cost": round(total, 4) if line.get("costed") else None,
        "cost_per_part": round(total / qty, 4) if line.get("costed") and qty else None,
        "material": material or (profile.material if profile else None),
        "grams": grams,
        "seconds": seconds,
        "quantity": qty,
    }
