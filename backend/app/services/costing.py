from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    BomHardwareItem,
    BomItem,
    GCodeFile,
    JobStatus,
    Order,
    OrderLine,
    Part,
    PartCostSnapshot,
    PrintJob,
    Product,
    QcBatch,
    QcStatus,
    utcnow,
)
from app.services.farm_settings import get_mes
from app.services.planner import production_approved_gcode


async def failure_rate_for_part(db: AsyncSession, part_id: UUID) -> float:
    batches = (
        await db.execute(select(QcBatch).where(QcBatch.part_id == part_id, QcBatch.status == QcStatus.complete))
    ).scalars().all()
    total = sum(b.quantity or 0 for b in batches)
    failed = sum(b.failed or 0 for b in batches)
    if total <= 0:
        return 0.05
    return min(0.5, failed / total)


async def estimate_part_cost(db: AsyncSession, part: Part, gcode: GCodeFile | None = None, persist: bool = False) -> dict:
    mes = await get_mes(db)
    gcode = gcode or await production_approved_gcode(db, part.id)
    hours = (gcode.estimated_time_seconds if gcode else 3600) / 3600.0
    grams = gcode.estimated_filament_grams if gcode else 0.0
    qty = max(1, gcode.quantity_per_file if gcode else 1)
    # Latest filament cost from completed jobs, else 0
    last = (
        await db.execute(
            select(PrintJob)
            .where(PrintJob.part_id == part.id, PrintJob.status == JobStatus.completed)
            .order_by(PrintJob.completed_at.desc())
            .limit(1)
        )
    ).scalars().first()
    cost_per_kg = 0.0
    if last and last.filament_used_grams and last.filament_cost:
        cost_per_kg = last.filament_cost / (last.filament_used_grams / 1000.0)
    if not cost_per_kg and last and last.estimated_filament_grams and last.filament_cost:
        cost_per_kg = last.filament_cost / max(0.001, last.estimated_filament_grams / 1000.0)
    from app.models import FilamentSpool

    if not cost_per_kg:
        spool = (
            await db.execute(
                select(FilamentSpool).where(FilamentSpool.is_archived.is_(False), FilamentSpool.cost_per_kg > 0)
            )
        ).scalars().first()
        if spool:
            cost_per_kg = spool.cost_per_kg or 0
    filament_cost = (grams / 1000.0) * cost_per_kg / qty
    watts = 180.0
    electricity = 0.0
    if mes["enable_electricity_cost"]:
        electricity = hours * (watts / 1000.0) * mes["electricity_price_per_kwh"] / qty
    fail_rate = await failure_rate_for_part(db, part.id)
    failure = filament_cost * fail_rate if mes["enable_failure_cost"] else 0.0
    machine = 0.0
    if mes["enable_machine_cost"]:
        # Use average printer machine rate if set; otherwise 0
        from app.models import Printer

        printer = (await db.execute(select(Printer).where(Printer.machine_rate_per_hour > 0))).scalars().first()
        rate = printer.machine_rate_per_hour if printer else 0.0
        machine = hours * rate / qty
    labour = hours * mes["labour_rate_per_hour"] / qty if mes["enable_labour_cost"] else 0.0
    total = filament_cost + electricity + failure + machine + labour
    snap = PartCostSnapshot(
        part_id=part.id,
        gcode_file_id=gcode.id if gcode else None,
        filament_cost=round(filament_cost, 4),
        electricity_cost=round(electricity, 4),
        failure_cost=round(failure, 4),
        machine_cost=round(machine, 4),
        labour_cost=round(labour, 4),
        total_cost=round(total, 4),
        filament_cost_per_kg=round(cost_per_kg, 4),
        electricity_price=mes["electricity_price_per_kwh"],
    )
    if persist:
        db.add(snap)
    return {
        "part_id": str(part.id),
        "sku": part.sku,
        "name": part.name,
        "gcode_filename": gcode.filename if gcode else None,
        "gcode_version": gcode.version if gcode else None,
        "filament_cost": round(filament_cost, 2),
        "electricity": round(electricity, 2),
        "failure_allowance": round(failure, 2),
        "machine_time": round(machine, 2),
        "labour": round(labour, 2),
        "estimated_cost": round(total, 2),
        "filament_cost_per_kg": round(cost_per_kg, 2),
        "print_hours": round(hours / qty, 3),
    }


async def product_cost(db: AsyncSession, product: Product) -> dict:
    await db.refresh(product, attribute_names=["bom_items", "bom_hardware"])
    parts = []
    total_parts = 0.0
    for item in product.bom_items or []:
        part = item.part or await db.get(Part, item.part_id)
        if not part:
            continue
        cost = await estimate_part_cost(db, part)
        line = cost["estimated_cost"] * (item.quantity or 1)
        parts.append({**cost, "bom_qty": item.quantity, "line_total": round(line, 2)})
        total_parts += line
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
    total = total_parts + hw_total
    return {
        "product_id": str(product.id),
        "sku": product.sku,
        "name": product.name,
        "parts": parts,
        "hardware": hardware,
        "parts_cost": round(total_parts, 2),
        "hardware_cost": round(hw_total, 2),
        "packaging_cost": round(packaging, 2),
        "estimated_cost": round(total, 2),
    }


async def order_profitability(db: AsyncSession, order: Order) -> dict:
    mes = await get_mes(db)
    await db.refresh(order, attribute_names=["lines"])
    revenue = order.revenue or 0
    mfg = 0.0
    hardware = 0.0
    packaging = 0.0
    products = []
    for line in order.lines:
        product = line.product or await db.get(Product, line.product_id)
        if not product:
            continue
        cost = await product_cost(db, product)
        qty = line.quantity or 1
        mfg += cost["parts_cost"] * qty
        hardware += cost["hardware_cost"] * qty
        packaging += cost["packaging_cost"] * qty
        products.append({**cost, "order_qty": qty, "line_cost": round(cost["estimated_cost"] * qty, 2)})
    shipping = order.shipping_cost or 0
    fees = order.payment_fee or (revenue * (mes["payment_fee_percent"] or 0) / 100.0)
    total_cost = mfg + hardware + packaging + shipping + fees
    profit = revenue - total_cost
    margin = (profit / revenue * 100.0) if revenue else 0.0
    return {
        "order_id": str(order.id),
        "reference": order.reference,
        "revenue": round(revenue, 2),
        "manufacturing_cost": round(mfg, 2),
        "hardware_cost": round(hardware, 2),
        "packaging_cost": round(packaging, 2),
        "shipping_cost": round(shipping, 2),
        "payment_fees": round(fees, 2),
        "estimated_total_cost": round(total_cost, 2),
        "gross_profit": round(profit, 2),
        "gross_margin_pct": round(margin, 1),
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
        created = order.created_at or utcnow()
        iso_week = created.strftime("%G-W%V")
        month = created.strftime("%Y-%m")
        weeks[iso_week]["revenue"] += p["revenue"]
        weeks[iso_week]["cost"] += p["estimated_total_cost"]
        weeks[iso_week]["orders"] += 1
        months[month]["revenue"] += p["revenue"]
        months[month]["cost"] += p["estimated_total_cost"]
        months[month]["orders"] += 1
        for prod in p["products"]:
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
