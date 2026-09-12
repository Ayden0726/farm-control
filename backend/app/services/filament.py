from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    DryingStatus,
    FilamentProduct,
    FilamentSpool,
    FilamentTransaction,
    GCodeFile,
    IdSequence,
    InventoryAudit,
    JobStatus,
    Order,
    OrderPartNeed,
    OrderStatus,
    PrintJob,
    Printer,
    ProductionRun,
    ProductionRunItem,
    ProductionRunStatus,
    PurchaseOrder,
    PurchaseOrderLine,
    StorageLocation,
    Supplier,
    utcnow,
)
from app.services.barcodes import unique_product_barcode
from app.util import new_qr_token

ACTIVE_JOBS = (JobStatus.queued, JobStatus.held, JobStatus.printing, JobStatus.paused)
OPEN_PO = (
    "suggested",
    "draft",
    "awaiting_approval",
    "approved",
    "ordered",
    "shipped",
    "partially_received",
)
DEFAULT_SPEND = {
    "monthly_budget": 2000.0,
    "max_po_value": 800.0,
    "max_price_per_kg": 80.0,
    "max_price_per_spool": 150.0,
    "price_increase_tolerance_pct": 15.0,
    "require_approval_price_increase": True,
    "require_approval_backup_supplier": True,
    "require_approval_unusual_qty": True,
    "never_auto_order_unknown": True,
    "full_auto_enabled": False,
}


async def audit(
    db: AsyncSession,
    action: str,
    entity_type: str,
    entity_id: Any,
    detail: dict | None = None,
    actor: str = "system",
) -> None:
    db.add(
        InventoryAudit(
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            detail=detail or {},
            actor=actor,
        )
    )


async def next_spool_number(db: AsyncSession) -> int:
    """Allocate the next SPOOL-###### value. Numbers are never reused."""
    seq = (
        await db.execute(select(IdSequence).where(IdSequence.name == "spool").with_for_update())
    ).scalar_one_or_none()
    if seq is None:
        db.add(IdSequence(name="spool", next_value=1))
        await db.flush()
        seq = (
            await db.execute(select(IdSequence).where(IdSequence.name == "spool").with_for_update())
        ).scalar_one()
    max_existing = (
        await db.execute(
            select(func.max(cast(func.substr(FilamentSpool.public_code, 7), Integer))).where(
                FilamentSpool.public_code.ilike("SPOOL-%")
            )
        )
    ).scalar()
    n = max(int(seq.next_value or 1), int(max_existing or 0) + 1)
    seq.next_value = n + 1
    return n


def spool_code(n: int) -> str:
    return f"SPOOL-{n:06d}"


async def next_po_reference(db: AsyncSession) -> str:
    seq = await db.get(IdSequence, "purchase_order")
    if seq is None:
        seq = IdSequence(name="purchase_order", next_value=1)
        db.add(seq)
        await db.flush()
    n = seq.next_value
    seq.next_value = n + 1
    return f"PO-{n:05d}"


def kg(grams: float) -> float:
    return round((grams or 0) / 1000.0, 3)


def cost_per_kg(cost: float, weight_g: float) -> float:
    if not weight_g:
        return 0.0
    return round(cost / (weight_g / 1000.0), 2)


async def ensure_product_barcode(db: AsyncSession, product: FilamentProduct) -> None:
    if product.barcode_id:
        return
    product.barcode_id = await unique_product_barcode(
        db, product.manufacturer, product.material, product.color, product.filament_weight_g
    )


def _color_matches(required: str, actual: str) -> bool:
    a = (required or "").strip().lower()
    b = (actual or "").strip().lower()
    if not a:
        return True
    if not b:
        return False
    return a == b or a in b or b in a


def _material_matches(required: str, actual: str) -> bool:
    a = (required or "").strip().lower()
    b = (actual or "").strip().lower()
    if not a:
        return True
    return a == b


async def product_physical_g(db: AsyncSession, product_id: UUID) -> float:
    val = (
        await db.execute(
            select(func.coalesce(func.sum(FilamentSpool.remaining_weight_g), 0)).where(
                FilamentSpool.product_id == product_id,
                FilamentSpool.is_archived.is_(False),
                FilamentSpool.is_empty.is_(False),
            )
        )
    ).scalar()
    return float(val or 0)


async def committed_by_product(db: AsyncSession) -> dict[UUID, float]:
    """Estimated grams already spoken for, keyed by filament product id.

    Includes current/queued prints, remaining production-run copies that are not
    yet jobs, and customer-order parts waiting for production. Jobs with an
    assigned spool count against that spool's product; otherwise they match
    material + colour.
    """
    committed: dict[UUID, float] = defaultdict(float)
    products = (await db.execute(select(FilamentProduct).where(FilamentProduct.is_active.is_(True)))).scalars().all()
    by_mat_color: dict[tuple[str, str], list[FilamentProduct]] = defaultdict(list)
    for p in products:
        by_mat_color[(p.material.lower(), p.color.lower())].append(p)

    def pick(material: str, color: str) -> FilamentProduct | None:
        key = ((material or "").lower(), (color or "").lower())
        rows = by_mat_color.get(key)
        if rows:
            return rows[0]
        mat = (material or "").lower()
        for p in products:
            if p.material.lower() == mat and _color_matches(color, p.color):
                return p
        for p in products:
            if p.material.lower() == mat:
                return p
        return None

    jobs = (
        await db.execute(
            select(PrintJob)
            .options(selectinload(PrintJob.gcode_file), selectinload(PrintJob.spool))
            .where(PrintJob.status.in_(ACTIVE_JOBS))
        )
    ).scalars().all()
    counted_item_qty: dict[UUID, int] = defaultdict(int)
    for job in jobs:
        grams = float(job.estimated_filament_grams or 0)
        if grams <= 0:
            continue
        product = None
        if job.spool_id and job.spool and job.spool.product_id:
            product = next((p for p in products if p.id == job.spool.product_id), None)
        if product is None and job.gcode_file:
            product = pick(job.gcode_file.material, job.gcode_file.required_color)
        if product:
            committed[product.id] += grams
        if job.production_run_item_id:
            counted_item_qty[job.production_run_item_id] += job.quantity_produced

    items = (
        await db.execute(
            select(ProductionRunItem)
            .options(selectinload(ProductionRunItem.gcode_file), selectinload(ProductionRunItem.production_run))
            .join(ProductionRun, ProductionRunItem.production_run_id == ProductionRun.id)
            .where(
                ProductionRun.status.in_(
                    [
                        ProductionRunStatus.draft,
                        ProductionRunStatus.queued,
                        ProductionRunStatus.in_progress,
                        ProductionRunStatus.paused,
                    ]
                )
            )
        )
    ).scalars().all()
    for item in items:
        gcode = item.gcode_file
        if not gcode:
            continue
        remaining = max(0, item.remaining_to_print - counted_item_qty.get(item.id, 0))
        if remaining <= 0:
            continue
        per = max(1, gcode.quantity_per_file)
        jobs_left = math.ceil(remaining / per)
        grams = jobs_left * float(gcode.estimated_filament_grams or 0)
        product = pick(gcode.material, gcode.required_color)
        if product:
            committed[product.id] += grams

    orders = (
        await db.execute(
            select(Order)
            .options(selectinload(Order.part_needs))
            .where(Order.status.in_([OrderStatus.new, OrderStatus.awaiting_production]))
        )
    ).scalars().all()
    gcodes_by_part: dict[UUID, GCodeFile] = {}
    all_gcode = (await db.execute(select(GCodeFile).where(GCodeFile.is_archived.is_(False)))).scalars().all()
    for g in all_gcode:
        if g.part_id and g.part_id not in gcodes_by_part:
            gcodes_by_part[g.part_id] = g
    for order in orders:
        if order.production_run_id:
            continue
        for need in order.part_needs:
            gcode = gcodes_by_part.get(need.part_id)
            if not gcode:
                continue
            qty = max(0, need.to_produce)
            if qty <= 0:
                continue
            per = max(1, gcode.quantity_per_file)
            grams = math.ceil(qty / per) * float(gcode.estimated_filament_grams or 0)
            product = pick(gcode.material, gcode.required_color)
            if product:
                committed[product.id] += grams
    return dict(committed)


async def on_order_g(db: AsyncSession, product_id: UUID) -> float:
    rows = (
        await db.execute(
            select(PurchaseOrderLine, PurchaseOrder)
            .join(PurchaseOrder, PurchaseOrderLine.purchase_order_id == PurchaseOrder.id)
            .where(
                PurchaseOrderLine.product_id == product_id,
                PurchaseOrder.status.in_(OPEN_PO),
            )
        )
    ).all()
    total = 0.0
    for line, po in rows:
        outstanding = max(0, line.quantity_ordered - line.quantity_received)
        total += outstanding * float(line.spool_weight_g or 0)
    return total


async def stock_snapshot(db: AsyncSession, product: FilamentProduct, committed_map: dict[UUID, float] | None = None) -> dict:
    spools = (
        await db.execute(
            select(FilamentSpool)
            .options(selectinload(FilamentSpool.assigned_printer), selectinload(FilamentSpool.location))
            .where(FilamentSpool.product_id == product.id, FilamentSpool.is_archived.is_(False))
        )
    ).scalars().all()
    live = [s for s in spools if not s.is_empty]
    physical = sum(s.remaining_weight_g for s in live)
    sealed = sum(1 for s in live if s.is_sealed and not s.assigned_printer_id)
    opened = sum(1 for s in live if not s.is_sealed and not s.assigned_printer_id)
    installed = sum(1 for s in live if s.assigned_printer_id)
    empty = sum(1 for s in spools if s.is_empty)
    value = sum((s.remaining_weight_g / s.initial_weight_g) * s.cost for s in live if s.initial_weight_g)
    committed = (committed_map or {}).get(product.id, 0.0)
    available = physical - committed
    on_order = await on_order_g(db, product.id)
    return {
        "product_id": str(product.id),
        "barcode_id": product.barcode_id,
        "manufacturer": product.manufacturer,
        "product_name": product.product_name,
        "material": product.material,
        "color": product.color,
        "spool_size_label": product.spool_size_label,
        "filament_weight_g": product.filament_weight_g,
        "physical_g": physical,
        "physical_kg": kg(physical),
        "committed_g": committed,
        "committed_kg": kg(committed),
        "available_g": available,
        "available_kg": kg(available),
        "on_order_g": on_order,
        "on_order_kg": kg(on_order),
        "sealed_rolls": sealed,
        "open_rolls": opened,
        "installed_rolls": installed,
        "empty_rolls": empty,
        "live_rolls": len(live),
        "inventory_value": round(value, 2),
        "min_stock_g": product.min_stock_g,
        "target_stock_g": product.target_stock_g,
        "below_minimum": available < product.min_stock_g,
        "reorder_mode": product.reorder_mode,
    }


def recommend_rolls(product: FilamentProduct, available_g: float) -> dict:
    spool_g = product.preferred_spool_weight_g or product.filament_weight_g or 1000
    spool_g = max(1.0, spool_g)
    if available_g >= product.min_stock_g:
        return {
            "needed": False,
            "rolls": 0,
            "resulting_g": available_g,
            "spool_g": spool_g,
            "reason": "Available stock is at or above the minimum.",
        }
    deficit = max(0.0, product.target_stock_g - available_g)
    rolls = math.ceil(deficit / spool_g) if deficit else 0
    rolls = max(rolls, product.min_reorder_qty or 1)
    multiple = max(1, product.reorder_multiple or 1)
    if rolls % multiple:
        rolls = ((rolls // multiple) + 1) * multiple
    resulting = available_g + rolls * spool_g
    return {
        "needed": True,
        "rolls": rolls,
        "resulting_g": resulting,
        "spool_g": spool_g,
        "reason": (
            f"Available {kg(available_g)} kg is below the {kg(product.min_stock_g)} kg minimum. "
            f"{rolls} × {kg(spool_g)} kg reaches {kg(resulting)} kg (target {kg(product.target_stock_g)} kg)."
        ),
    }


async def usage_stats(db: AsyncSession, product_id: UUID | None = None, days: int = 30) -> dict:
    cutoff = utcnow() - timedelta(days=days)
    stmt = select(FilamentTransaction).where(
        FilamentTransaction.reason == "print_consumed",
        FilamentTransaction.created_at >= cutoff,
    )
    if product_id:
        stmt = stmt.join(FilamentSpool).where(FilamentSpool.product_id == product_id)
    rows = (await db.execute(stmt)).scalars().all()
    consumed = sum(abs(t.amount_g) for t in rows)
    daily = consumed / max(1, days)
    return {"window_days": days, "consumed_g": consumed, "avg_daily_g": daily, "txn_count": len(rows)}


async def forecast(db: AsyncSession, product: FilamentProduct, snap: dict, stats: dict) -> dict:
    available = snap["available_g"]
    daily = stats["avg_daily_g"]
    lead = max(0, product.lead_time_days or 0)
    days_remaining = (available / daily) if daily > 0 else None
    now = utcnow()
    depletion = (now + timedelta(days=days_remaining)) if days_remaining is not None else None
    reorder_date = None
    if days_remaining is not None:
        reorder_in = max(0.0, days_remaining - lead)
        reorder_date = now + timedelta(days=reorder_in)
    return {
        "avg_daily_g": daily,
        "days_remaining": round(days_remaining, 1) if days_remaining is not None else None,
        "depletion_at": depletion.isoformat() if depletion else None,
        "recommended_reorder_at": reorder_date.isoformat() if reorder_date else None,
        "lead_time_days": lead,
        "will_stockout_before_delivery": bool(
            days_remaining is not None and days_remaining < lead and snap["below_minimum"]
        ),
    }


async def record_transaction(
    db: AsyncSession,
    spool: FilamentSpool,
    amount_g: float,
    reason: str,
    *,
    printer_id: UUID | None = None,
    job_id: UUID | None = None,
    production_run_id: UUID | None = None,
    notes: str = "",
) -> FilamentTransaction:
    previous = float(spool.remaining_weight_g or 0)
    if reason == "receive":
        txn_amount = amount_g
        remaining = float(spool.remaining_weight_g or 0)
        previous = 0.0
    elif reason == "adjustment":
        remaining = max(0.0, amount_g)
        txn_amount = previous - remaining
        spool.remaining_weight_g = remaining
        spool.consumed_g = max(0.0, (spool.consumed_g or 0) + txn_amount)
    else:
        txn_amount = amount_g
        remaining = max(0.0, previous - amount_g)
        spool.remaining_weight_g = remaining
        spool.consumed_g = (spool.consumed_g or 0) + max(0.0, amount_g)
    if spool.remaining_weight_g <= 0:
        spool.is_empty = True
        spool.remaining_weight_g = 0
    if reason in {"print_consumed", "adjustment"} and spool.is_sealed:
        spool.is_sealed = False
        spool.date_opened = spool.date_opened or utcnow()
    txn = FilamentTransaction(
        spool_id=spool.id,
        previous_g=previous,
        amount_g=txn_amount,
        remaining_g=spool.remaining_weight_g,
        reason=reason,
        printer_id=printer_id,
        job_id=job_id,
        production_run_id=production_run_id,
        notes=notes,
    )
    db.add(txn)
    await audit(
        db,
        reason,
        "spool",
        spool.public_code or spool.id,
        {
            "previous_g": previous,
            "amount_g": txn_amount,
            "remaining_g": spool.remaining_weight_g,
            "job_id": str(job_id) if job_id else None,
            "printer_id": str(printer_id) if printer_id else None,
        },
    )
    return txn


async def consume_for_job(db: AsyncSession, spool: FilamentSpool, job: PrintJob, printer: Printer) -> None:
    used = float(job.estimated_filament_grams or 0)
    if used <= 0:
        return
    await record_transaction(
        db,
        spool,
        used,
        "print_consumed",
        printer_id=printer.id,
        job_id=job.id,
        production_run_id=job.production_run_id,
        notes=f"G-code estimate for {job.id}",
    )
    job.filament_used_grams = used
    job.spool_id = spool.id
    if spool.initial_weight_g:
        job.filament_cost = (spool.cost / spool.initial_weight_g) * used


def parse_drying_status(value: str | DryingStatus | None) -> DryingStatus:
    if value is None or value == "":
        return DryingStatus.unknown
    if isinstance(value, DryingStatus):
        return value
    try:
        return DryingStatus(str(value))
    except ValueError as exc:
        raise ValueError("Drying must be dry, drying, needs_drying, or unknown") from exc


async def resolve_receive_location(
    db: AsyncSession, location_id: UUID | None, drying: DryingStatus
) -> UUID | None:
    if location_id is not None:
        return location_id
    if drying == DryingStatus.drying:
        dryer = (
            await db.execute(
                select(StorageLocation)
                .where(StorageLocation.kind == "dryer", StorageLocation.is_active.is_(True))
                .order_by(StorageLocation.name)
            )
        ).scalars().first()
        if dryer:
            return dryer.id
    sealed = (
        await db.execute(select(StorageLocation).where(StorageLocation.name == "Sealed Stock"))
    ).scalar_one_or_none()
    return sealed.id if sealed else None


async def create_spools_from_receive(
    db: AsyncSession,
    product: FilamentProduct,
    quantity: int,
    cost_per_spool: float,
    *,
    supplier_id: UUID | None = None,
    purchase_order_id: UUID | None = None,
    location_id: UUID | None = None,
    date_purchased: datetime | None = None,
    notes: str = "",
    actor: str = "operator",
    drying_status: str | DryingStatus | None = None,
) -> list[FilamentSpool]:
    if quantity < 1 or quantity > 500:
        raise ValueError("Quantity must be between 1 and 500 rolls")
    created: list[FilamentSpool] = []
    now = utcnow()
    drying = parse_drying_status(drying_status)
    opened = drying in (DryingStatus.drying, DryingStatus.dry)
    last_dried = now if drying == DryingStatus.dry else None
    cpk = cost_per_kg(cost_per_spool, product.filament_weight_g)
    size = product.spool_size_label or f"{kg(product.filament_weight_g)} kg"
    loc = await resolve_receive_location(db, location_id, drying)
    for _ in range(quantity):
        n = await next_spool_number(db)
        code = spool_code(n)
        spool = FilamentSpool(
            name=f"{product.manufacturer} {product.material} {product.color} {size}",
            manufacturer=product.manufacturer,
            material=product.material,
            color=product.color,
            initial_weight_g=product.filament_weight_g,
            remaining_weight_g=product.filament_weight_g,
            cost=cost_per_spool,
            cost_per_kg=cpk,
            purchase_date=date_purchased or now,
            date_received=now,
            date_opened=now if opened else None,
            last_dried_at=last_dried,
            assigned_printer_id=None,
            product_id=product.id,
            location_id=loc,
            supplier_id=supplier_id or product.preferred_supplier_id,
            purchase_order_id=purchase_order_id,
            drying_status=drying,
            low_stock_threshold_g=max(150, product.filament_weight_g * 0.05),
            qr_token=new_qr_token(),
            public_code=code,
            is_sealed=not opened,
            is_empty=False,
            consumed_g=0,
            notes=notes,
        )
        db.add(spool)
        await db.flush()
        await record_transaction(db, spool, product.filament_weight_g, "receive", notes="Incoming stock")
        created.append(spool)
    await audit(
        db,
        "filament_received",
        "product",
        product.barcode_id,
        {
            "quantity": quantity,
            "cost_per_spool": cost_per_spool,
            "drying_status": drying.value,
            "spool_codes": [s.public_code for s in created],
            "purchase_order_id": str(purchase_order_id) if purchase_order_id else None,
        },
        actor=actor,
    )
    return created


async def assign_spool_to_printer(
    db: AsyncSession,
    printer: Printer,
    spool: FilamentSpool,
    actor: str = "operator",
) -> None:
    if printer.assigned_spool_id and printer.assigned_spool_id != spool.id:
        prev = await db.get(FilamentSpool, printer.assigned_spool_id)
        if prev:
            prev.assigned_printer_id = None
    if spool.assigned_printer_id and spool.assigned_printer_id != printer.id:
        other = await db.get(Printer, spool.assigned_printer_id)
        if other and other.assigned_spool_id == spool.id:
            other.assigned_spool_id = None
    printer.assigned_spool_id = spool.id
    spool.assigned_printer_id = printer.id
    if spool.is_sealed:
        spool.is_sealed = False
        spool.date_opened = spool.date_opened or utcnow()
    printer_loc = (
        await db.execute(select(StorageLocation).where(StorageLocation.printer_id == printer.id))
    ).scalar_one_or_none()
    if printer_loc:
        spool.location_id = printer_loc.id
    await audit(
        db,
        "printer_assigned",
        "spool",
        spool.public_code or spool.id,
        {"printer": printer.name, "printer_id": str(printer.id)},
        actor=actor,
    )


async def move_spool(db: AsyncSession, spool: FilamentSpool, location: StorageLocation, actor: str = "operator") -> None:
    previous = spool.location_id
    spool.location_id = location.id
    if location.kind == "open":
        if spool.is_sealed:
            spool.is_sealed = False
            spool.date_opened = spool.date_opened or utcnow()
    if location.printer_id:
        printer = await db.get(Printer, location.printer_id)
        if printer:
            await assign_spool_to_printer(db, printer, spool, actor=actor)
            return
    await audit(
        db,
        "spool_moved",
        "spool",
        spool.public_code or spool.id,
        {"from": str(previous) if previous else None, "to": location.name},
        actor=actor,
    )


def job_filament_check(job: PrintJob, printer: Printer, spool: FilamentSpool | None, gcode: GCodeFile | None) -> dict:
    required = float(job.estimated_filament_grams or 0)
    available = float(spool.remaining_weight_g) if spool else 0.0
    reasons: list[str] = []
    if required <= 0:
        return {"ok": True, "required_g": required, "available_g": available, "reasons": []}
    if job.filament_override:
        return {"ok": True, "required_g": required, "available_g": available, "reasons": [], "overridden": True}
    if not spool:
        reasons.append("No spool is assigned to this printer.")
    else:
        if available < required * 1.08:
            reasons.append(
                f"Insufficient filament. Required {required:.0f} g, available {available:.0f} g on {spool.public_code or spool.name}."
            )
        if gcode and not _material_matches(gcode.material, spool.material):
            reasons.append(f"Material mismatch: job wants {gcode.material}, spool is {spool.material}.")
        if gcode and gcode.required_color and not _color_matches(gcode.required_color, spool.color):
            reasons.append(f"Colour mismatch: job wants {gcode.required_color}, spool is {spool.color}.")
    return {
        "ok": not reasons,
        "required_g": required,
        "available_g": available,
        "reasons": reasons,
        "spool_id": str(spool.id) if spool else None,
        "spool_code": spool.public_code if spool else None,
        "printer_id": str(printer.id),
        "printer_name": printer.name,
    }


async def production_filament_check(db: AsyncSession, run: ProductionRun) -> dict:
    committed_map = await committed_by_product(db)
    products = (await db.execute(select(FilamentProduct).where(FilamentProduct.is_active.is_(True)))).scalars().all()
    by_id = {p.id: p for p in products}
    needed: dict[UUID, float] = defaultdict(float)
    for item in run.items:
        gcode = item.gcode_file
        if not gcode:
            continue
        remaining = item.remaining_to_print
        per = max(1, gcode.quantity_per_file)
        grams = math.ceil(remaining / per) * float(gcode.estimated_filament_grams or 0)
        match = None
        color = (gcode.required_color or "").lower()
        for p in products:
            if p.material.lower() == (gcode.material or "").lower() and (
                not color or p.color.lower() == color or color in p.color.lower()
            ):
                match = p
                break
        if match is None:
            for p in products:
                if p.material.lower() == (gcode.material or "").lower():
                    match = p
                    break
        if match:
            needed[match.id] += grams
    lines = []
    overall = "can_start"
    for pid, grams in needed.items():
        product = by_id[pid]
        snap = await stock_snapshot(db, product, committed_map)
        available = snap["available_g"]
        on_order = snap["on_order_g"]
        physical = snap["physical_g"]
        if physical >= grams:
            verdict = "can_start"
        elif physical + on_order >= grams:
            verdict = "wait_for_stock"
        elif physical > 0:
            verdict = "partial"
        else:
            verdict = "needs_purchase"
        if verdict == "partial" and overall == "can_start":
            overall = "partial"
        if verdict == "wait_for_stock" and overall in {"can_start", "partial"}:
            overall = "wait_for_stock"
        if verdict == "needs_purchase":
            overall = "needs_purchase"
        rec = recommend_rolls(product, snap["available_g"] - grams + snap["committed_g"])
        lines.append(
            {
                "product_id": str(product.id),
                "label": f"{product.manufacturer} {product.material} — {product.color}",
                "required_g": grams,
                "physical_g": physical,
                "available_g": available,
                "on_order_g": on_order,
                "verdict": verdict,
                "recommend_rolls": rec["rolls"] if rec["needed"] else 0,
            }
        )
    if not lines:
        overall = "can_start"
    return {"run_id": str(run.id), "run_name": run.name, "overall": overall, "materials": lines}
