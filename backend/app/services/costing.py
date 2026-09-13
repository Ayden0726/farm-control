from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    BomHardwareItem,
    FilamentProduct,
    FilamentSpool,
    GCodeFile,
    JobStatus,
    Order,
    OrderLine,
    Part,
    PartCostSnapshot,
    PrintJob,
    Printer,
    Product,
    QcBatch,
    QcStatus,
    utcnow,
)
from app.services.farm_settings import get_mes
from app.services.gcode_meta import parse_filament_grams_from_filename
from app.services.planner import production_approved_gcode

GRAMS_ACTUAL = "actual"
GRAMS_SLICER = "slicer"
GRAMS_FILENAME = "filename"
GRAMS_MISSING = "missing"

RATE_SPOOL = "spool"
RATE_PROFILE = "profile"
RATE_MISSING = "missing"

MISSING_GRAMS = "missing_grams"
MISSING_RATE = "missing_rate"
MISSING_GCODE = "missing_gcode"

MISSING_COPY = {
    MISSING_GRAMS: "No filament estimate on this G-code — re-read estimates in Library",
    MISSING_RATE: "No filament price — set a receive cost on a spool or a normal cost on the matching filament profile",
    MISSING_GCODE: "No G-code tagged to this part — upload a file in Library",
}


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number <= 0:
        return None
    return number


def _qty(value: Any) -> int:
    try:
        n = int(value or 1)
    except (TypeError, ValueError):
        n = 1
    return max(1, n)


def spool_net_grams(
    initial_g: Any = None,
    remaining_g: Any = None,
    consumed_g: Any = None,
) -> float | None:
    """Original net filament on the spool. Prefer initial; else remaining + used."""
    initial = _positive(initial_g)
    if initial:
        return initial
    rem = float(remaining_g or 0)
    used = float(consumed_g or 0)
    net = rem + used
    return net if net > 0 else None


def cost_per_gram_from_spool(
    *,
    cost: Any = 0,
    initial_g: Any = None,
    remaining_g: Any = None,
    consumed_g: Any = None,
    cost_per_kg: Any = 0,
) -> float | None:
    """Purchase price paid at receive ÷ original net grams. Profile price must not override this."""
    net = spool_net_grams(initial_g, remaining_g, consumed_g)
    paid = float(cost or 0)
    if paid > 0 and net:
        return paid / net
    per_kg = float(cost_per_kg or 0)
    if per_kg > 0:
        return per_kg / 1000.0
    return None


def cost_per_gram_from_profile(
    *,
    normal_price: Any = 0,
    purchase_cost: Any = 0,
    filament_weight_g: Any = None,
    cost_per_kg: Any = 0,
) -> float | None:
    """Profile normal cost (typically a full spool) ÷ spool size grams."""
    weight = _positive(filament_weight_g)
    price = float(normal_price or 0) or float(purchase_cost or 0)
    if price > 0 and weight:
        return price / weight
    per_kg = float(cost_per_kg or 0)
    if per_kg > 0:
        return per_kg / 1000.0
    return None


def select_part_grams(
    *,
    actual_used_g: Any = None,
    estimate_g: Any = None,
    filename_g: Any = None,
    quantity: Any = 1,
) -> dict[str, Any]:
    """Prefer completed job usage, then slicer/G-code estimate, then filename grams."""
    qty = _qty(quantity)
    actual = _positive(actual_used_g)
    if actual:
        return {
            "grams": actual / qty,
            "plate_grams": actual,
            "source": GRAMS_ACTUAL,
            "quantity": qty,
        }
    estimate = _positive(estimate_g)
    if estimate:
        return {
            "grams": estimate / qty,
            "plate_grams": estimate,
            "source": GRAMS_SLICER,
            "quantity": qty,
        }
    filename = _positive(filename_g)
    if filename:
        return {
            "grams": filename / qty,
            "plate_grams": filename,
            "source": GRAMS_FILENAME,
            "quantity": qty,
        }
    return {
        "grams": None,
        "plate_grams": None,
        "source": GRAMS_MISSING,
        "quantity": qty,
    }


def select_filament_rate(*, spool_per_g: float | None, profile_per_g: float | None) -> dict[str, Any]:
    if spool_per_g and spool_per_g > 0:
        return {"cost_per_g": spool_per_g, "source": RATE_SPOOL}
    if profile_per_g and profile_per_g > 0:
        return {"cost_per_g": profile_per_g, "source": RATE_PROFILE}
    return {"cost_per_g": None, "source": RATE_MISSING}


def filament_line_cost(grams: float | None, cost_per_g: float | None) -> dict[str, Any]:
    if grams is None or grams <= 0:
        return {"filament_cost": None, "costed": False, "reason": MISSING_GRAMS}
    if cost_per_g is None or cost_per_g <= 0:
        return {"filament_cost": None, "costed": False, "reason": MISSING_RATE}
    return {"filament_cost": grams * cost_per_g, "costed": True, "reason": None}


def _round_money(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _grams_for_gcode(gcode: GCodeFile | None) -> tuple[float | None, float | None]:
    if not gcode:
        return None, None
    estimate = _positive(gcode.estimated_filament_grams)
    filename = parse_filament_grams_from_filename(gcode.filename or "")
    return estimate, filename


async def failure_rate_for_part(db: AsyncSession, part_id: UUID) -> float:
    batches = (
        await db.execute(select(QcBatch).where(QcBatch.part_id == part_id, QcBatch.status == QcStatus.complete))
    ).scalars().all()
    total = sum(b.quantity or 0 for b in batches)
    failed = sum(b.failed or 0 for b in batches)
    if total <= 0:
        return 0.05
    return min(0.5, failed / total)


def _rate_from_spool(spool: FilamentSpool | None) -> float | None:
    if not spool:
        return None
    return cost_per_gram_from_spool(
        cost=spool.cost,
        initial_g=spool.initial_weight_g,
        remaining_g=spool.remaining_weight_g,
        consumed_g=spool.consumed_g,
        cost_per_kg=spool.cost_per_kg,
    )


def _rate_from_profile(product: FilamentProduct | None) -> float | None:
    if not product:
        return None
    return cost_per_gram_from_profile(
        normal_price=product.normal_price,
        purchase_cost=product.purchase_cost,
        filament_weight_g=product.filament_weight_g,
        cost_per_kg=product.cost_per_kg,
    )


def _material_key(value: str | None) -> str:
    return (value or "").strip().lower()


async def typical_filament_product(
    db: AsyncSession, material: str | None, color: str | None = None
) -> FilamentProduct | None:
    products = (
        await db.execute(select(FilamentProduct).where(FilamentProduct.is_active.is_(True)))
    ).scalars().all()
    if not products:
        return None
    material_l = _material_key(material)
    color_l = _material_key(color)
    scored: list[tuple[int, FilamentProduct]] = []
    for product in products:
        score = 0
        if material_l and _material_key(product.material) != material_l:
            continue
        if material_l:
            score += 4
        if color_l and _material_key(product.color) == color_l:
            score += 2
        if _rate_from_profile(product):
            score += 1
        scored.append((score, product))
    if not scored:
        return None
    scored.sort(key=lambda item: -item[0])
    best_score, best = scored[0]
    if best_score <= 0:
        return None
    return best


async def _latest_completed_job(
    db: AsyncSession, part_id: UUID, gcode_id: UUID | None
) -> PrintJob | None:
    stmt = (
        select(PrintJob)
        .options(selectinload(PrintJob.spool).selectinload(FilamentSpool.product))
        .where(PrintJob.part_id == part_id, PrintJob.status == JobStatus.completed)
        .order_by(PrintJob.completed_at.desc())
    )
    jobs = (await db.execute(stmt)).scalars().all()
    if gcode_id:
        for job in jobs:
            if job.gcode_file_id == gcode_id:
                return job
    return jobs[0] if jobs else None


def _part_cost_payload(
    *,
    part: Part,
    gcode: GCodeFile | None,
    grams_info: dict[str, Any],
    rate_info: dict[str, Any],
    filament: dict[str, Any],
    electricity: float,
    failure: float,
    machine: float,
    labour: float,
    hours: float,
    spool: FilamentSpool | None,
    profile: FilamentProduct | None,
    missing_reason: str | None,
) -> dict[str, Any]:
    grams = grams_info["grams"]
    cost_per_g = rate_info["cost_per_g"]
    filament_cost = filament["filament_cost"]
    extras = electricity + failure + machine + labour
    costed = bool(filament["costed"])
    total = (filament_cost or 0.0) + extras if costed else None
    cost_per_kg = (cost_per_g * 1000.0) if cost_per_g else None
    grams_source = grams_info["source"]
    if grams_source == GRAMS_ACTUAL:
        grams_label = "Actual printed grams from the last completed job"
    elif grams_source == GRAMS_SLICER:
        grams_label = "Slicer / G-code estimate"
    elif grams_source == GRAMS_FILENAME:
        grams_label = "Filename estimate"
    else:
        grams_label = MISSING_COPY[missing_reason or MISSING_GRAMS]
    if rate_info["source"] == RATE_SPOOL and spool:
        rate_label = (
            f"Spool {spool.public_code or spool.name} purchase price at receive"
        )
    elif rate_info["source"] == RATE_PROFILE and profile:
        rate_label = f"{profile.manufacturer} {profile.material} {profile.color} profile normal cost"
    elif rate_info["source"] == RATE_MISSING:
        rate_label = MISSING_COPY[MISSING_RATE]
    else:
        rate_label = None
    return {
        "part_id": str(part.id),
        "sku": part.sku,
        "name": part.name,
        "gcode_filename": gcode.filename if gcode else None,
        "gcode_version": gcode.version if gcode else None,
        "gcode_material": gcode.material if gcode else None,
        "quantity_per_file": grams_info["quantity"],
        "grams": _round_money(grams, 2),
        "plate_grams": _round_money(grams_info["plate_grams"], 2),
        "grams_source": grams_source,
        "grams_label": grams_label,
        "filament_cost_per_g": _round_money(cost_per_g, 6),
        "filament_cost_per_kg": _round_money(cost_per_kg, 4),
        "rate_source": rate_info["source"],
        "rate_label": rate_label,
        "spool_code": (spool.public_code or spool.name) if spool else None,
        "filament_profile": (
            f"{profile.manufacturer} {profile.material} {profile.color}".strip() if profile else None
        ),
        "filament_cost": _round_money(filament_cost, 2) if costed else None,
        "electricity": round(electricity, 2),
        "failure_allowance": round(failure, 2),
        "machine_time": round(machine, 2),
        "labour": round(labour, 2),
        "estimated_cost": _round_money(total, 2) if costed else None,
        "print_hours": round(hours, 3),
        "costed": costed,
        "missing_reason": missing_reason if not costed else None,
        "missing_message": MISSING_COPY.get(missing_reason or "") if not costed else None,
    }


async def estimate_part_cost(
    db: AsyncSession, part: Part, gcode: GCodeFile | None = None, persist: bool = False
) -> dict:
    mes = await get_mes(db)
    gcode = gcode or await production_approved_gcode(db, part.id)
    last = await _latest_completed_job(db, part.id, gcode.id if gcode else None)
    grams_job = last if last and gcode and last.gcode_file_id == gcode.id else (last if not gcode else None)
    spool_job = last

    actual_g = None
    actual_qty = None
    spool: FilamentSpool | None = None
    if grams_job:
        actual_g = _positive(grams_job.filament_used_grams)
        if actual_g:
            actual_qty = grams_job.quantity_produced
    if spool_job:
        if spool_job.spool:
            spool = spool_job.spool
        elif spool_job.spool_id:
            spool = await db.get(FilamentSpool, spool_job.spool_id)

    estimate_g, filename_g = _grams_for_gcode(gcode)
    qty = actual_qty if actual_g else (gcode.quantity_per_file if gcode else 1)
    grams_info = select_part_grams(
        actual_used_g=actual_g,
        estimate_g=estimate_g,
        filename_g=filename_g,
        quantity=qty,
    )

    profile: FilamentProduct | None = None
    if spool and spool.product:
        profile = spool.product
    elif spool and spool.product_id:
        profile = await db.get(FilamentProduct, spool.product_id)
    if profile is None and gcode:
        profile = await typical_filament_product(db, gcode.material, getattr(gcode, "required_color", "") or "")

    rate_info = select_filament_rate(
        spool_per_g=_rate_from_spool(spool),
        profile_per_g=_rate_from_profile(profile),
    )
    filament = filament_line_cost(grams_info["grams"], rate_info["cost_per_g"])
    missing_reason = filament["reason"]
    if not gcode and grams_info["source"] == GRAMS_MISSING:
        missing_reason = MISSING_GCODE
        filament = {"filament_cost": None, "costed": False, "reason": MISSING_GCODE}

    seconds = gcode.estimated_time_seconds if gcode else 0
    hours = (seconds / 3600.0) / grams_info["quantity"] if seconds else 0.0
    watts = 180.0
    electricity = 0.0
    if mes["enable_electricity_cost"] and hours:
        electricity = hours * (watts / 1000.0) * mes["electricity_price_per_kwh"]
    fail_rate = await failure_rate_for_part(db, part.id)
    filament_for_fail = filament["filament_cost"] or 0.0
    failure = filament_for_fail * fail_rate if mes["enable_failure_cost"] and filament["costed"] else 0.0
    machine = 0.0
    if mes["enable_machine_cost"] and hours:
        printer = (await db.execute(select(Printer).where(Printer.machine_rate_per_hour > 0))).scalars().first()
        rate = printer.machine_rate_per_hour if printer else 0.0
        machine = hours * rate
    labour = hours * mes["labour_rate_per_hour"] if mes["enable_labour_cost"] and hours else 0.0

    payload = _part_cost_payload(
        part=part,
        gcode=gcode,
        grams_info=grams_info,
        rate_info=rate_info,
        filament=filament,
        electricity=electricity,
        failure=failure,
        machine=machine,
        labour=labour,
        hours=hours,
        spool=spool,
        profile=profile,
        missing_reason=missing_reason,
    )

    snap = PartCostSnapshot(
        part_id=part.id,
        gcode_file_id=gcode.id if gcode else None,
        filament_cost=round(filament["filament_cost"] or 0.0, 4),
        electricity_cost=round(electricity, 4),
        failure_cost=round(failure, 4),
        machine_cost=round(machine, 4),
        labour_cost=round(labour, 4),
        total_cost=round((filament["filament_cost"] or 0.0) + electricity + failure + machine + labour, 4),
        filament_cost_per_kg=round((rate_info["cost_per_g"] or 0.0) * 1000.0, 4),
        electricity_price=mes["electricity_price_per_kwh"],
        notes=payload.get("missing_message") or payload.get("grams_label") or "",
    )
    if persist:
        db.add(snap)
    return payload


async def product_cost(db: AsyncSession, product: Product) -> dict:
    await db.refresh(product, attribute_names=["bom_items", "bom_hardware"])
    parts = []
    total_parts = 0.0
    costed = True
    missing = []
    for item in product.bom_items or []:
        part = await db.get(Part, item.part_id)
        if not part:
            continue
        cost = await estimate_part_cost(db, part)
        qty = item.quantity or 1
        if cost.get("costed") and cost.get("estimated_cost") is not None:
            line = cost["estimated_cost"] * qty
            total_parts += line
        else:
            line = None
            if not item.is_optional:
                costed = False
                missing.append(cost.get("sku") or part.sku)
        parts.append({**cost, "bom_qty": item.quantity, "line_total": _round_money(line, 2)})
    hardware = []
    hw_total = 0.0
    rows = (
        await db.execute(
            select(BomHardwareItem)
            .options(selectinload(BomHardwareItem.hardware_item))
            .where(BomHardwareItem.product_id == product.id)
        )
    ).scalars().all()
    packaging = 0.0
    for item in rows:
        hw = item.hardware_item
        unit = (hw.unit_cost or hw.purchase_cost or 0) if hw else 0
        line = unit * (item.quantity or 1)
        hardware.append(
            {
                "sku": hw.sku if hw else "",
                "name": hw.name if hw else "",
                "category": hw.category if hw else "",
                "qty": item.quantity,
                "unit_cost": unit,
                "line_total": round(line, 2),
            }
        )
        hw_total += line
        if hw and (hw.category or "").lower() in {"packaging", "shipping", "labels"}:
            packaging += line
    total = total_parts + hw_total if costed else None
    return {
        "product_id": str(product.id),
        "sku": product.sku,
        "name": product.name,
        "parts": parts,
        "hardware": hardware,
        "parts_cost": round(total_parts, 2) if costed else None,
        "hardware_cost": round(hw_total, 2),
        "packaging_cost": round(packaging, 2),
        "estimated_cost": _round_money(total, 2),
        "costed": costed,
        "missing_parts": missing,
        "missing_message": (
            None
            if costed
            else f"Incomplete — no filament cost yet for {', '.join(missing)}"
        ),
    }


async def order_profitability(db: AsyncSession, order: Order) -> dict:
    mes = await get_mes(db)
    await db.refresh(order, attribute_names=["lines"])
    revenue = order.revenue or 0
    mfg = 0.0
    hardware = 0.0
    packaging = 0.0
    products = []
    costed = True
    for line in order.lines:
        product = await db.get(Product, line.product_id)
        if not product:
            continue
        cost = await product_cost(db, product)
        qty = line.quantity or 1
        if cost.get("costed") and cost.get("parts_cost") is not None:
            mfg += cost["parts_cost"] * qty
        else:
            costed = False
        hardware += (cost["hardware_cost"] or 0) * qty
        packaging += (cost["packaging_cost"] or 0) * qty
        line_cost = (cost["estimated_cost"] * qty) if cost.get("estimated_cost") is not None else None
        products.append({**cost, "order_qty": qty, "line_cost": _round_money(line_cost, 2)})
    shipping = order.shipping_cost or 0
    fees = order.payment_fee or (revenue * (mes["payment_fee_percent"] or 0) / 100.0)
    known_cost = mfg + hardware + packaging + shipping + fees
    total_cost = known_cost if costed else None
    profit = (revenue - known_cost) if costed else None
    margin = (profit / revenue * 100.0) if costed and revenue and profit is not None else None
    return {
        "order_id": str(order.id),
        "reference": order.reference,
        "revenue": round(revenue, 2),
        "manufacturing_cost": round(mfg, 2) if costed else None,
        "hardware_cost": round(hardware, 2),
        "packaging_cost": round(packaging, 2),
        "shipping_cost": round(shipping, 2),
        "payment_fees": round(fees, 2),
        "estimated_total_cost": _round_money(total_cost, 2),
        "gross_profit": _round_money(profit, 2),
        "gross_margin_pct": round(margin, 1) if margin is not None else None,
        "costed": costed,
        "products": products,
    }


async def profitability_series(db: AsyncSession) -> dict:
    orders = (
        await db.execute(
            select(Order)
            .options(selectinload(Order.lines).selectinload(OrderLine.product))
            .where(Order.revenue > 0)
            .order_by(Order.created_at.desc())
            .limit(200)
        )
    ).scalars().all()
    by_product: dict[str, dict] = {}
    weeks: dict[str, dict] = defaultdict(lambda: {"revenue": 0.0, "cost": 0.0, "orders": 0})
    months: dict[str, dict] = defaultdict(lambda: {"revenue": 0.0, "cost": 0.0, "orders": 0})
    rows = []
    for order in orders:
        p = await order_profitability(db, order)
        rows.append(p)
        if not p.get("costed"):
            continue
        created = order.created_at or utcnow()
        iso_week = created.strftime("%G-W%V")
        month = created.strftime("%Y-%m")
        weeks[iso_week]["revenue"] += p["revenue"]
        weeks[iso_week]["cost"] += p["estimated_total_cost"] or 0
        weeks[iso_week]["orders"] += 1
        months[month]["revenue"] += p["revenue"]
        months[month]["cost"] += p["estimated_total_cost"] or 0
        months[month]["orders"] += 1
        for prod in p["products"]:
            if prod.get("line_cost") is None:
                continue
            key = prod["sku"]
            slot = by_product.setdefault(key, {"sku": key, "name": prod["name"], "revenue": 0, "cost": 0, "qty": 0})
            slot["cost"] += prod["line_cost"]
            slot["qty"] += prod["order_qty"]
    return {
        "orders": rows[:50],
        "by_product": list(by_product.values()),
        "by_week": [{"period": k, **v, "profit": round(v["revenue"] - v["cost"], 2)} for k, v in sorted(weeks.items())],
        "by_month": [
            {"period": k, **v, "profit": round(v["revenue"] - v["cost"], 2)} for k, v in sorted(months.items())
        ],
    }
