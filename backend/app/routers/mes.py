from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user, require_perm, require_roles
from app.models import (
    AssemblyKit,
    AssemblyKitLine,
    AuditLog,
    BackupRecord,
    BomHardwareItem,
    FilamentProduct,
    FilamentSpool,
    GCodeFile,
    HardwareItem,
    JobStatus,
    MaintenanceTask,
    Order,
    OrderLine,
    OrderStatus,
    Part,
    PartBin,
    PrintJob,
    Printer,
    PrinterDowntime,
    PrinterStatus,
    Product,
    ProductionRun,
    ProductionRunItem,
    PurchaseOrder,
    QcBatch,
    QcStatus,
    User,
    UserRole,
    utcnow,
)
from app.services.audit import record_audit
from app.services.backups import create_backup, restore_backup
from app.services.codes import next_order_code
from app.services.costing import estimate_part_cost, order_profitability, product_cost, profitability_series
from app.services.health import collect_health
from app.services.kits import advance_kit, create_kit, kit_out, kit_requirements, refresh_kit, reserve_kit
from app.services.packing import confirm_item, ensure_checks, mark_packed, packing_list
from app.services.planner import production_approved_gcode
from app.services.shipping import record_shipment

router = APIRouter(tags=["mes"])


class KitIn(BaseModel):
    product_id: UUID
    quantity: int = 1
    order_id: UUID | None = None


class KitStatusIn(BaseModel):
    status: str


class PackConfirmIn(BaseModel):
    qty: float | None = None


class PackCompleteIn(BaseModel):
    override: bool = False
    notes: str = ""


class ShipIn(BaseModel):
    carrier: str
    tracking_number: str
    cost: float = 0
    notes: str = ""


class PresetIn(BaseModel):
    product_id: UUID
    quantity: int = 1
    build_stock: bool = False


# --- Kits ---
@router.get("/qc/stats")
async def qc_stats(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    batches = (
        await db.execute(
            select(QcBatch).options(selectinload(QcBatch.part), selectinload(QcBatch.job)).where(
                QcBatch.status == QcStatus.complete
            )
        )
    ).scalars().all()
    def bucket(key_fn):
        acc: dict[str, dict] = {}
        for b in batches:
            key = key_fn(b) or "—"
            slot = acc.setdefault(key, {"key": key, "printed": 0, "passed": 0, "failed": 0})
            slot["printed"] += b.quantity or 0
            slot["passed"] += b.passed or 0
            slot["failed"] += b.failed or 0
        for slot in acc.values():
            slot["yield_pct"] = round(100 * slot["passed"] / max(1, slot["printed"]), 1)
        return sorted(acc.values(), key=lambda r: -r["printed"])[:20]

    defects: dict[str, int] = {}
    for b in batches:
        if b.failure_reason and b.failed:
            defects[b.failure_reason] = defects.get(b.failure_reason, 0) + b.failed
    return {
        "by_part": bucket(lambda b: b.part.sku if b.part else None),
        "by_reason": [{"reason": k, "failed": v} for k, v in sorted(defects.items(), key=lambda kv: -kv[1])],
        "first_pass_yield": round(
            100 * sum(b.passed or 0 for b in batches) / max(1, sum(b.quantity or 0 for b in batches)), 1
        ),
    }


# --- Kits ---
@router.get("/kits")
async def list_kits(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    rows = (
        await db.execute(
            select(AssemblyKit)
            .options(
                selectinload(AssemblyKit.product),
                selectinload(AssemblyKit.lines).selectinload(AssemblyKitLine.part),
                selectinload(AssemblyKit.lines).selectinload(AssemblyKitLine.hardware_item),
            )
            .order_by(AssemblyKit.created_at.desc())
        )
    ).scalars().all()
    out = []
    for kit in rows:
        await refresh_kit(db, kit)
        out.append(kit_out(kit))
    return out


@router.post("/kits")
async def new_kit(payload: KitIn, db: AsyncSession = Depends(get_db), user: User = Depends(require_perm("production"))):
    try:
        kit = await create_kit(db, payload.product_id, payload.quantity, payload.order_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await db.commit()
    kit = (
        await db.execute(
            select(AssemblyKit)
            .options(
                selectinload(AssemblyKit.product),
                selectinload(AssemblyKit.lines).selectinload(AssemblyKitLine.part),
                selectinload(AssemblyKit.lines).selectinload(AssemblyKitLine.hardware_item),
            )
            .where(AssemblyKit.id == kit.id)
        )
    ).scalar_one()
    return kit_out(kit)


@router.get("/kits/{kit_id}")
async def get_kit(kit_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    kit = (
        await db.execute(
            select(AssemblyKit)
            .options(
                selectinload(AssemblyKit.product),
                selectinload(AssemblyKit.lines).selectinload(AssemblyKitLine.part),
                selectinload(AssemblyKit.lines).selectinload(AssemblyKitLine.hardware_item),
            )
            .where(AssemblyKit.id == kit_id)
        )
    ).scalar_one_or_none()
    if not kit:
        raise HTTPException(404, "Kit not found")
    await refresh_kit(db, kit)
    return kit_out(kit)


@router.post("/kits/{kit_id}/reserve")
async def kit_reserve(
    kit_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_perm("production"))
):
    kit = (
        await db.execute(
            select(AssemblyKit)
            .options(
                selectinload(AssemblyKit.product),
                selectinload(AssemblyKit.lines).selectinload(AssemblyKitLine.part),
                selectinload(AssemblyKit.lines).selectinload(AssemblyKitLine.hardware_item),
            )
            .where(AssemblyKit.id == kit_id)
        )
    ).scalar_one_or_none()
    if not kit:
        raise HTTPException(404, "Kit not found")
    try:
        await reserve_kit(db, kit)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await db.commit()
    return kit_out(kit)


@router.post("/kits/{kit_id}/status")
async def kit_status(
    kit_id: UUID,
    payload: KitStatusIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_perm("production")),
):
    kit = (
        await db.execute(
            select(AssemblyKit)
            .options(
                selectinload(AssemblyKit.product),
                selectinload(AssemblyKit.lines).selectinload(AssemblyKitLine.part),
                selectinload(AssemblyKit.lines).selectinload(AssemblyKitLine.hardware_item),
            )
            .where(AssemblyKit.id == kit_id)
        )
    ).scalar_one_or_none()
    if not kit:
        raise HTTPException(404, "Kit not found")
    try:
        await advance_kit(db, kit, payload.status)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await db.commit()
    return kit_out(kit)


@router.get("/products/{product_id}/kit-preview")
async def kit_preview(
    product_id: UUID, quantity: int = 1, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Unknown product")
    reqs = await kit_requirements(db, product, quantity)
    ready = all(r["ok"] for r in reqs) and bool(reqs)
    return {"product_id": str(product.id), "sku": product.sku, "ready": ready, "lines": reqs}


# --- Packing / shipping ---
@router.get("/packing/{order_id}")
async def packing_get(order_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    order = (
        await db.execute(
            select(Order)
            .options(selectinload(Order.lines).selectinload(OrderLine.product), selectinload(Order.part_needs))
            .where(Order.id == order_id)
        )
    ).scalar_one_or_none()
    if not order:
        raise HTTPException(404, "Order not found")
    checks = await ensure_checks(db, order)
    await db.commit()
    return {
        "order_id": str(order.id),
        "reference": order.reference,
        "public_code": order.public_code,
        "status": order.status.value,
        "packing_status": order.packing_status,
        "packed_at": order.packed_at.isoformat() if order.packed_at else None,
        "packing_override": order.packing_override,
        "items": await packing_list(db, order),
        "checks": [
            {
                "id": str(c.id),
                "label": c.label,
                "kind": c.kind,
                "required_qty": c.required_qty,
                "confirmed": c.confirmed,
                "confirmed_qty": c.confirmed_qty,
            }
            for c in checks
        ],
    }


@router.post("/packing/{order_id}/confirm/{check_id}")
async def packing_confirm(
    order_id: UUID,
    check_id: UUID,
    payload: PackConfirmIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_perm("packing")),
):
    order = await db.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    try:
        await confirm_item(db, order, check_id, payload.qty)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await db.commit()
    return {"ok": True}


@router.post("/packing/{order_id}/complete")
async def packing_complete(
    order_id: UUID,
    payload: PackCompleteIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_perm("packing")),
):
    order = (
        await db.execute(
            select(Order)
            .options(selectinload(Order.lines).selectinload(OrderLine.product), selectinload(Order.part_needs))
            .where(Order.id == order_id)
        )
    ).scalar_one_or_none()
    if not order:
        raise HTTPException(404, "Order not found")
    try:
        await mark_packed(db, order, override=payload.override, notes=payload.notes, actor=user.email)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await db.commit()
    return {"ok": True, "status": order.status.value, "packed_at": order.packed_at.isoformat() if order.packed_at else None}


@router.post("/orders/{order_id}/ship")
async def ship_order(
    order_id: UUID,
    payload: ShipIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_perm("packing")),
):
    order = (
        await db.execute(
            select(Order).options(selectinload(Order.part_needs), selectinload(Order.lines)).where(Order.id == order_id)
        )
    ).scalar_one_or_none()
    if not order:
        raise HTTPException(404, "Order not found")
    shipment = await record_shipment(
        db,
        order,
        carrier=payload.carrier,
        tracking_number=payload.tracking_number,
        cost=payload.cost,
        notes=payload.notes,
        actor=user.email,
    )
    await db.commit()
    return {
        "id": str(shipment.id),
        "carrier": shipment.carrier,
        "tracking_number": shipment.tracking_number,
        "cost": shipment.cost,
        "status": shipment.status,
    }


# --- Costing ---
@router.get("/costing/parts")
async def costing_parts(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    parts = (await db.execute(select(Part).where(Part.is_active.is_(True)).order_by(Part.sku))).scalars().all()
    return [await estimate_part_cost(db, p) for p in parts]


@router.get("/costing/products/{product_id}")
async def costing_product(
    product_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Unknown product")
    return await product_cost(db, product)


@router.get("/costing/orders/{order_id}")
async def costing_order(order_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    order = (
        await db.execute(
            select(Order).options(selectinload(Order.lines).selectinload(OrderLine.product)).where(Order.id == order_id)
        )
    ).scalar_one_or_none()
    if not order:
        raise HTTPException(404, "Order not found")
    return await order_profitability(db, order)


@router.get("/costing/profitability")
async def costing_profit(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    return await profitability_series(db)


# --- Search / health / audit / backups ---
@router.get("/search")
async def search(q: str = "", db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    term = (q or "").strip()
    if len(term) < 1:
        return {"query": term, "results": []}
    like = f"%{term}%"
    results = []

    async def add(kind, rows, label_fn, path_fn):
        for row in rows:
            results.append({"kind": kind, "id": str(row.id), "label": label_fn(row), "path": path_fn(row)})

    await add(
        "order",
        (await db.execute(select(Order).where(or_(Order.reference.ilike(like), Order.public_code.ilike(like))).limit(8))).scalars().all(),
        lambda o: f"Order {o.reference}",
        lambda o: f"/orders/{o.id}",
    )
    await add(
        "part",
        (await db.execute(select(Part).where(or_(Part.sku.ilike(like), Part.name.ilike(like))).limit(8))).scalars().all(),
        lambda p: f"{p.sku} — {p.name}",
        lambda p: "/inventory",
    )
    await add(
        "product",
        (await db.execute(select(Product).where(or_(Product.sku.ilike(like), Product.name.ilike(like))).limit(8))).scalars().all(),
        lambda p: f"{p.sku} — {p.name}",
        lambda p: "/products",
    )
    await add(
        "printer",
        (await db.execute(select(Printer).where(or_(Printer.name.ilike(like), Printer.public_code.ilike(like))).limit(8))).scalars().all(),
        lambda p: p.name,
        lambda p: f"/printers/{p.id}",
    )
    await add(
        "spool",
        (await db.execute(select(FilamentSpool).where(or_(FilamentSpool.public_code.ilike(like), FilamentSpool.name.ilike(like))).limit(8))).scalars().all(),
        lambda s: s.public_code or s.name,
        lambda s: f"/filament/spools/{s.id}",
    )
    await add(
        "filament",
        (await db.execute(select(FilamentProduct).where(or_(FilamentProduct.barcode_id.ilike(like), FilamentProduct.color.ilike(like))).limit(8))).scalars().all(),
        lambda p: p.barcode_id,
        lambda p: f"/filament/products/{p.id}",
    )
    await add(
        "bin",
        (await db.execute(select(PartBin).where(or_(PartBin.public_code.ilike(like), PartBin.name.ilike(like))).limit(8))).scalars().all(),
        lambda b: b.public_code or b.name,
        lambda b: f"/inventory/bins/{b.id}",
    )
    await add(
        "batch",
        (await db.execute(select(ProductionRun).where(ProductionRun.batch_code.ilike(like)).limit(8))).scalars().all(),
        lambda r: r.batch_code or r.name,
        lambda r: f"/production/{r.id}",
    )
    await add(
        "gcode",
        (await db.execute(select(GCodeFile).where(GCodeFile.filename.ilike(like)).limit(8))).scalars().all(),
        lambda g: f"{g.filename} v{g.version}",
        lambda g: "/library",
    )
    await add(
        "po",
        (await db.execute(select(PurchaseOrder).where(PurchaseOrder.reference.ilike(like)).limit(8))).scalars().all(),
        lambda p: p.reference,
        lambda p: f"/filament/purchasing/{p.id}",
    )
    await add(
        "hardware",
        (await db.execute(select(HardwareItem).where(or_(HardwareItem.sku.ilike(like), HardwareItem.name.ilike(like))).limit(8))).scalars().all(),
        lambda h: f"{h.sku} — {h.name}",
        lambda h: "/hardware",
    )
    return {"query": term, "results": results[:40]}


@router.get("/health")
async def health_page(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    return await collect_health(db)


@router.get("/audit")
async def audit_list(
    limit: int = Query(100, le=500), db: AsyncSession = Depends(get_db), _: User = Depends(require_roles(UserRole.admin, UserRole.operator))
):
    rows = (await db.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit))).scalars().all()
    return [
        {
            "id": str(r.id),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "previous_value": r.previous_value,
            "new_value": r.new_value,
            "actor": r.actor,
            "source": r.source,
        }
        for r in rows
    ]


@router.get("/backups")
async def list_backups(db: AsyncSession = Depends(get_db), _: User = Depends(require_roles(UserRole.admin))):
    rows = (await db.execute(select(BackupRecord).order_by(BackupRecord.created_at.desc()).limit(50))).scalars().all()
    last_ok = next((r for r in rows if r.status == "ok"), None)
    return {
        "last_successful": last_ok.created_at.isoformat() if last_ok and last_ok.created_at else None,
        "backups": [
            {
                "id": str(r.id),
                "filename": r.filename,
                "kind": r.kind,
                "status": r.status,
                "size_bytes": r.size_bytes,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "error_message": r.error_message,
                "notes": r.notes,
            }
            for r in rows
        ],
    }


@router.post("/backups")
async def make_backup(
    include_files: bool = False, db: AsyncSession = Depends(get_db), _: User = Depends(require_roles(UserRole.admin))
):
    row = await create_backup(db, kind="manual", include_files=include_files)
    await db.commit()
    return {"id": str(row.id), "status": row.status, "filename": row.filename, "error": row.error_message}


@router.get("/backups/{backup_id}/download")
async def download_backup(
    backup_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(require_roles(UserRole.admin))
):
    row = await db.get(BackupRecord, backup_id)
    if not row:
        raise HTTPException(404, "Backup not found")
    from pathlib import Path

    path = Path(row.stored_path)
    if not path.exists():
        raise HTTPException(404, "Backup file missing")
    return FileResponse(path, filename=row.filename, media_type="application/gzip")


@router.post("/backups/{backup_id}/restore")
async def restore(
    backup_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(require_roles(UserRole.admin))
):
    try:
        row = await restore_backup(db, backup_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await db.commit()
    return {"ok": True, "filename": row.filename}


# --- Timeline / capacity / downtime ---
@router.get("/timeline")
async def timeline(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    printers = (await db.execute(select(Printer).where(Printer.is_enabled.is_(True)).order_by(Printer.name))).scalars().all()
    jobs = (
        await db.execute(
            select(PrintJob)
            .options(selectinload(PrintJob.part), selectinload(PrintJob.gcode_file))
            .where(PrintJob.status.in_([JobStatus.queued, JobStatus.held, JobStatus.printing, JobStatus.paused]))
            .order_by(PrintJob.queue_position)
        )
    ).scalars().all()
    now = utcnow()
    lanes = []
    for printer in printers:
        cursor = now + timedelta(seconds=printer.time_remaining_seconds or 0)
        if printer.status.value == "waiting_for_bed_clear":
            cursor += timedelta(minutes=5)
        blocks = []
        active = next((j for j in jobs if j.actual_printer_id == printer.id and j.status in {JobStatus.printing, JobStatus.paused}), None)
        if active:
            end = now + timedelta(seconds=printer.time_remaining_seconds or active.estimated_time_seconds or 0)
            blocks.append(
                {
                    "job_id": str(active.id),
                    "label": active.part.sku if active.part else (active.gcode_file.filename if active.gcode_file else "Print"),
                    "start": now.isoformat(),
                    "end": end.isoformat(),
                    "status": active.status.value,
                    "current": True,
                }
            )
            cursor = end + timedelta(seconds=10)
        queued = [j for j in jobs if j.assigned_printer_id == printer.id and j.status in {JobStatus.queued, JobStatus.held}]
        queued.sort(key=lambda j: j.queue_position)
        for job in queued:
            dur = job.estimated_time_seconds or 3600
            end = cursor + timedelta(seconds=dur)
            blocks.append(
                {
                    "job_id": str(job.id),
                    "label": job.part.sku if job.part else (job.gcode_file.filename if job.gcode_file else "Print"),
                    "start": cursor.isoformat(),
                    "end": end.isoformat(),
                    "status": job.status.value,
                    "current": False,
                    "incompatibility_reason": job.incompatibility_reason,
                }
            )
            cursor = end + timedelta(seconds=10)
        lanes.append({"printer_id": str(printer.id), "printer_name": printer.name, "status": printer.status.value, "blocks": blocks})
    return {"generated_at": now.isoformat(), "lanes": lanes}


@router.get("/capacity")
async def capacity(days: int = 7, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    printers = (await db.execute(select(Printer).where(Printer.is_enabled.is_(True)))).scalars().all()
    hours_each = 24.0 * max(1, days)
    # subtract overnight disabled printers roughly 9h/day
    available = 0.0
    for p in printers:
        if (p.unattended_mode or "allowed") == "disabled_overnight":
            available += 15 * max(1, days)
        else:
            available += hours_each
        if p.status == PrinterStatus.offline:
            available -= min(hours_each, 24)
    jobs = (
        await db.execute(
            select(PrintJob).where(PrintJob.status.in_([JobStatus.queued, JobStatus.held, JobStatus.printing, JobStatus.paused]))
        )
    ).scalars().all()
    required = sum((j.estimated_time_seconds or 0) for j in jobs) / 3600.0
    orders = (
        await db.execute(
            select(Order).where(Order.status.in_([OrderStatus.new, OrderStatus.awaiting_production, OrderStatus.in_production, OrderStatus.awaiting_qc]))
        )
    ).scalars().all()
    due = [o for o in orders if o.due_at and o.due_at <= utcnow() + timedelta(days=days)]
    util = (required / available * 100) if available else 0
    finish = utcnow() + timedelta(hours=required / max(1, len(printers) or 1))
    return {
        "window_days": days,
        "available_printer_hours": round(available, 1),
        "required_printer_hours": round(required, 1),
        "capacity_utilisation_pct": round(util, 1),
        "orders_due": len(due),
        "backlog_jobs": len(jobs),
        "estimated_completion": finish.isoformat(),
        "over_capacity": util > 100,
    }


@router.get("/downtime")
async def downtime_stats(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    printers = (await db.execute(select(Printer))).scalars().all()
    rows = (await db.execute(select(PrinterDowntime))).scalars().all()
    now = utcnow()
    by_reason: dict[str, int] = {}
    events = []
    for row in rows:
        end = row.ended_at or now
        secs = max(0, int((end - row.started_at).total_seconds()))
        by_reason[row.reason] = by_reason.get(row.reason, 0) + secs
        events.append(
            {
                "printer_id": str(row.printer_id),
                "reason": row.reason,
                "started_at": row.started_at.isoformat(),
                "ended_at": row.ended_at.isoformat() if row.ended_at else None,
                "seconds": secs,
            }
        )
    printers_out = []
    for p in printers:
        total = p.total_print_seconds or 0
        down = sum(e["seconds"] for e in events if e["printer_id"] == str(p.id))
        window = max(total + down, 1)
        printers_out.append(
            {
                "id": str(p.id),
                "name": p.name,
                "uptime_pct": round(100 * total / window, 1),
                "downtime_seconds": down,
                "utilisation_pct": round(100 * total / window, 1),
                "failure_rate_pct": round(100 * (p.failed_jobs or 0) / max(1, p.total_jobs or 0), 1),
            }
        )
    common = sorted(by_reason.items(), key=lambda kv: -kv[1])
    return {
        "printers": printers_out,
        "most_common_reason": common[0][0] if common else None,
        "reasons": [{"reason": k, "seconds": v} for k, v in common],
        "events": events[-50:],
    }


# --- Production presets ---
@router.post("/presets/produce")
async def produce_preset(
    payload: PresetIn, db: AsyncSession = Depends(get_db), user: User = Depends(require_perm("production"))
):
    from app.services.inventory import get_or_create_stock
    from app.services.planner import build_plan, commit_plan, load_plan

    product = await db.get(Product, payload.product_id)
    if not product:
        raise HTTPException(404, "Unknown product")
    reqs = await kit_requirements(db, product, payload.quantity)
    shortages = []
    for row in reqs:
        if row["kind"] != "part":
            continue
        if payload.build_stock:
            shortages.append(row)
            continue
        missing = max(0, row["required"] - row["available"])
        if missing:
            shortages.append({**row, "required": missing})
    plan = await build_plan(db, actor=user.email)
    loaded = await load_plan(db, plan.id)
    wanted = {r["sku"] for r in shortages}
    for line in loaded.lines:
        sku = line.part.sku if line.part else ""
        match = next((r for r in shortages if r["sku"] == sku), None)
        if match:
            line.included = True
            line.quantity = int(match["required"])
        elif not payload.build_stock:
            line.included = sku in wanted
    await db.flush()
    try:
        run = await commit_plan(db, loaded, actor=user.email)
    except ValueError as exc:
        from app.services.planner import plan_payload as _plan_payload

        await db.commit()
        loaded = await load_plan(db, plan.id)
        return {
            "plan": _plan_payload(loaded) if loaded else None,
            "run": None,
            "message": str(exc),
            "hardware": [r for r in reqs if r["kind"] == "hardware"],
        }
    await db.commit()
    from app.services.planner import plan_payload

    return {
        "plan": plan_payload(await load_plan(db, plan.id)),
        "run_id": str(run.id),
        "batch_code": run.batch_code,
        "hardware": [r for r in reqs if r["kind"] == "hardware"],
        "shortages": shortages,
    }


@router.get("/maintenance/tasks")
async def maint_tasks(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    rows = (
        await db.execute(
            select(MaintenanceTask).options(selectinload(MaintenanceTask.printer)).order_by(MaintenanceTask.due_at.nulls_last())
        )
    ).scalars().all()
    return [
        {
            "id": str(t.id),
            "name": t.name,
            "kind": t.kind,
            "status": t.status,
            "printer_id": str(t.printer_id),
            "printer_name": t.printer.name if t.printer else "",
            "due_at": t.due_at.isoformat() if t.due_at else None,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            "notes": t.notes,
        }
        for t in rows
    ]


@router.post("/maintenance/tasks/{task_id}/complete")
async def complete_task(
    task_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_perm("production"))
):
    task = await db.get(MaintenanceTask, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    task.status = "complete"
    task.completed_at = utcnow()
    await record_audit(
        db, action="maintenance_complete", entity_type="maintenance_task", entity_id=str(task.id), actor=user.email
    )
    await db.commit()
    return {"ok": True}


@router.get("/users")
async def list_users(db: AsyncSession = Depends(get_db), _: User = Depends(require_roles(UserRole.admin))):
    rows = (await db.execute(select(User).order_by(User.email))).scalars().all()
    return [{"id": str(u.id), "email": u.email, "full_name": u.full_name, "role": u.role.value, "is_active": u.is_active} for u in rows]


class UserRoleIn(BaseModel):
    role: str
    is_active: bool | None = None


@router.patch("/users/{user_id}")
async def patch_user(
    user_id: UUID,
    payload: UserRoleIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.admin)),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    try:
        user.role = UserRole(payload.role)
    except ValueError:
        raise HTTPException(400, "Unknown role")
    if payload.is_active is not None:
        user.is_active = payload.is_active
    await db.commit()
    return {"id": str(user.id), "role": user.role.value, "is_active": user.is_active}
