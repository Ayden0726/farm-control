from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    FinishedPartStock,
    GCodeFile,
    JobStatus,
    Order,
    OrderPartNeed,
    OrderStatus,
    Part,
    PrintJob,
    Printer,
    PrinterStatus,
    ProductionPlan,
    ProductionPlanLine,
    ProductionRun,
    ProductionRunItem,
    ProductionRunPrinter,
    ProductionRunStatus,
    utcnow,
)
from app.services.codes import next_batch_code
from app.services.compatibility import format_incompatibility, gcode_printer_issues, unattended_blocks
from app.services.queue import enqueue_jobs_for_item
from app.util import jobs_needed


OPEN_ORDER = {
    OrderStatus.new,
    OrderStatus.awaiting_production,
    OrderStatus.in_production,
    OrderStatus.awaiting_qc,
}

ACTIVE_JOB = {JobStatus.queued, JobStatus.held, JobStatus.printing, JobStatus.paused}


async def production_approved_gcode(db: AsyncSession, part_id: UUID) -> GCodeFile | None:
    approved = (
        await db.execute(
            select(GCodeFile)
            .where(
                GCodeFile.part_id == part_id,
                GCodeFile.is_archived.is_(False),
                GCodeFile.production_approved.is_(True),
            )
            .order_by(GCodeFile.version.desc())
        )
    ).scalars().first()
    if approved:
        return approved
    return (
        await db.execute(
            select(GCodeFile)
            .where(GCodeFile.part_id == part_id, GCodeFile.is_archived.is_(False))
            .order_by(GCodeFile.version.desc())
        )
    ).scalars().first()


async def _pipeline_qty(db: AsyncSession, part_id: UUID) -> int:
    jobs = (
        await db.execute(
            select(PrintJob).where(PrintJob.part_id == part_id, PrintJob.status.in_(ACTIVE_JOB))
        )
    ).scalars().all()
    return sum(j.quantity_produced or 0 for j in jobs)


def _stock_available(stock: FinishedPartStock | None) -> int:
    if not stock:
        return 0
    return max(0, (stock.quantity_on_hand or 0) - (stock.quantity_reserved or 0))


async def demand_by_part(db: AsyncSession) -> dict[UUID, dict]:
    """True shortage: order needs + target stock − available − already queued/printing."""
    parts = (await db.execute(select(Part).where(Part.is_active.is_(True)))).scalars().all()
    stocks = {s.part_id: s for s in (await db.execute(select(FinishedPartStock))).scalars().all()}
    orders = (
        await db.execute(
            select(Order)
            .options(selectinload(Order.part_needs).selectinload(OrderPartNeed.part))
            .where(Order.status.in_(OPEN_ORDER))
        )
    ).scalars().all()

    order_need: dict[UUID, int] = defaultdict(int)
    order_map: dict[UUID, list[Order]] = defaultdict(list)
    for order in orders:
        for need in order.part_needs:
            still = max(0, (need.required_qty or 0) - (need.reserved_qty or 0))
            if still <= 0:
                continue
            order_need[need.part_id] += still
            order_map[need.part_id].append(order)

    out: dict[UUID, dict] = {}
    for part in parts:
        available = _stock_available(stocks.get(part.id))
        pipeline = await _pipeline_qty(db, part.id)
        from_orders = order_need.get(part.id, 0)
        target_gap = max(0, (part.target_stock or 0) - available - pipeline)
        # Don't print parts already covered by inventory+queue; only the true gap.
        shortage = max(0, from_orders - available - pipeline)
        # Target stock is extra, only if user is building buffer beyond orders.
        buffer = target_gap if from_orders == 0 else max(0, target_gap - shortage)
        total = shortage + buffer
        if total <= 0 and from_orders <= 0:
            continue
        linked = order_map.get(part.id, [])
        oldest = min((o.created_at for o in linked), default=None)
        soonest_due = min((o.due_at for o in linked if o.due_at), default=None)
        out[part.id] = {
            "part": part,
            "physical": stocks.get(part.id).quantity_on_hand if stocks.get(part.id) else 0,
            "reserved": stocks.get(part.id).quantity_reserved if stocks.get(part.id) else 0,
            "available": available,
            "pipeline": pipeline,
            "order_need": from_orders,
            "shortage": shortage,
            "buffer": buffer,
            "to_print": total,
            "orders": linked,
            "oldest_order": oldest,
            "due_at": soonest_due,
            "min_stock": part.min_stock or 0,
            "target_stock": part.target_stock or 0,
        }
    return out


def _printer_free_at(printer: Printer, queued_seconds: int, now: datetime) -> datetime:
    remaining = printer.time_remaining_seconds or 0
    if printer.status == PrinterStatus.waiting_for_bed_clear:
        remaining = max(remaining, 300)
    if printer.status == PrinterStatus.offline:
        remaining = max(remaining, 3600)
    return now + timedelta(seconds=remaining + queued_seconds)


async def _workload_seconds(db: AsyncSession, printer_id: UUID) -> int:
    jobs = (
        await db.execute(
            select(PrintJob).where(
                PrintJob.assigned_printer_id == printer_id,
                PrintJob.status.in_({JobStatus.queued, JobStatus.held}),
            )
        )
        ).scalars().all()
    total = 0
    from app.services.slicer_duration import scheduling_multiplier

    printer = await db.get(Printer, printer_id)
    for job in jobs:
        gcode = None
        if job.gcode_file_id:
            gcode = await db.get(GCodeFile, job.gcode_file_id)
        mult = 1.0
        if printer:
            mult = await scheduling_multiplier(
                db, printer, gcode.material if gcode else None, gcode.nozzle_mm if gcode else None, None
            )
        total += int((job.estimated_time_seconds or 0) * mult)
    return total


async def recommend_printer(
    db: AsyncSession,
    gcode: GCodeFile | None,
    printers: list[Printer],
    load_seconds: dict[UUID, int],
    now: datetime,
) -> tuple[Printer | None, list[str], datetime | None, datetime | None]:
    best: Printer | None = None
    best_end: datetime | None = None
    best_issues: list[str] = []
    for printer in printers:
        if not printer.is_enabled:
            continue
        issues = gcode_printer_issues(gcode, printer) if gcode else ["No production-approved G-code"]
        if printer.status in {PrinterStatus.error} and printer.current_downtime_reason:
            issues.append(f"{printer.name} is unavailable ({printer.current_downtime_reason})")
        if issues:
            if best is None and not best_issues:
                best_issues = issues
            continue
        dummy = PrintJob(
            gcode_file_id=gcode.id if gcode else None,
            unattended_approved=True if gcode is None else bool(gcode.unattended_approved),
        )
        dummy.gcode_file = gcode
        block = await unattended_blocks(db, dummy, printer, now)
        extra = 0
        if block:
            extra = 8 * 3600
        start = _printer_free_at(printer, load_seconds.get(printer.id, 0) + extra, now)
        duration = gcode.estimated_time_seconds if gcode else 3600
        end = start + timedelta(seconds=duration or 3600)
        if best is None or end < (best_end or end):
            best = printer
            best_end = end
            best_issues = []
            start_best = start
    if best is None:
        return None, best_issues, None, None
    start = _printer_free_at(best, load_seconds.get(best.id, 0), now)
    end = start + timedelta(seconds=(gcode.estimated_time_seconds if gcode else 3600) or 3600)
    return best, [], start, end


async def build_plan(
    db: AsyncSession,
    *,
    persist: bool = True,
    actor: str = "operator",
    needed_by: datetime | None = None,
) -> ProductionPlan:
    demand = await demand_by_part(db)
    printers = (
        await db.execute(select(Printer).options(selectinload(Printer.assigned_spool)).order_by(Printer.name))
    ).scalars().all()
    load = {p.id: await _workload_seconds(db, p.id) for p in printers}
    now = utcnow()
    plan = ProductionPlan(
        status="draft",
        notes="Generated from open orders, inventory, and queue",
        created_by=actor,
        needed_by=needed_by,
    )
    db.add(plan)
    await db.flush()

    # Sort: customer order shortage first, then due date, then age, then buffer
    ranked = sorted(
        demand.values(),
        key=lambda d: (
            0 if d["shortage"] > 0 else 1,
            d["due_at"] or datetime.max.replace(tzinfo=timezone.utc),
            d["oldest_order"] or datetime.max.replace(tzinfo=timezone.utc),
        ),
    )
    for row in ranked:
        if row["to_print"] <= 0:
            continue
        part: Part = row["part"]
        gcode = await production_approved_gcode(db, part.id)
        qty_per = gcode.quantity_per_file if gcode else 1
        n_jobs = jobs_needed(row["to_print"], qty_per)
        printer, issues, start, end = await recommend_printer(db, gcode, printers, load, now)
        filament = (gcode.estimated_filament_grams if gcode else 0) * n_jobs
        filament_ok = True
        if printer and printer.assigned_spool and filament:
            filament_ok = (printer.assigned_spool.remaining_weight_g or 0) >= filament
        reason = (
            f"Required for {', '.join(o.reference for o in row['orders'][:3])}"
            if row["orders"]
            else f"Inventory below target stock ({row['available']} available, target {row['target_stock']})"
        )
        line = ProductionPlanLine(
            plan_id=plan.id,
            part_id=part.id,
            gcode_file_id=gcode.id if gcode else None,
            printer_id=printer.id if printer else None,
            quantity=row["to_print"],
            jobs_needed=n_jobs,
            estimated_start=start,
            estimated_end=end,
            required_filament_g=filament,
            filament_ok=filament_ok,
            compatible=not issues and printer is not None,
            incompatibility_reason="; ".join(issues) if issues else "",
            order_ids=[str(o.id) for o in row["orders"]],
            order_refs=[o.reference for o in row["orders"]],
            reason=reason,
            included=bool(printer and gcode and not issues),
        )
        db.add(line)
        if printer and gcode:
            load[printer.id] = load.get(printer.id, 0) + (gcode.estimated_time_seconds or 3600) * n_jobs
    if persist:
        await db.flush()
    return plan


async def load_plan(db: AsyncSession, plan_id: UUID) -> ProductionPlan | None:
    return (
        await db.execute(
            select(ProductionPlan)
            .options(
                selectinload(ProductionPlan.lines).selectinload(ProductionPlanLine.part),
                selectinload(ProductionPlan.lines).selectinload(ProductionPlanLine.gcode_file),
                selectinload(ProductionPlan.lines).selectinload(ProductionPlanLine.printer),
            )
            .where(ProductionPlan.id == plan_id)
        )
    ).scalar_one_or_none()


def plan_payload(plan: ProductionPlan) -> dict:
    lines = []
    for line in plan.lines:
        lines.append(
            {
                "id": str(line.id),
                "part_id": str(line.part_id),
                "part_sku": line.part.sku if line.part else "",
                "part_name": line.part.name if line.part else "",
                "gcode_file_id": str(line.gcode_file_id) if line.gcode_file_id else None,
                "gcode_filename": line.gcode_file.filename if line.gcode_file else None,
                "gcode_version": line.gcode_file.version if line.gcode_file else None,
                "printer_id": str(line.printer_id) if line.printer_id else None,
                "printer_name": line.printer.name if line.printer else None,
                "quantity": line.quantity,
                "jobs_needed": line.jobs_needed,
                "estimated_start": line.estimated_start.isoformat() if line.estimated_start else None,
                "estimated_end": line.estimated_end.isoformat() if line.estimated_end else None,
                "required_filament_g": line.required_filament_g,
                "filament_ok": line.filament_ok,
                "compatible": line.compatible,
                "incompatibility_reason": line.incompatibility_reason,
                "order_ids": line.order_ids or [],
                "order_refs": line.order_refs or [],
                "reason": line.reason,
                "included": line.included,
            }
        )
    return {
        "id": str(plan.id),
        "status": plan.status,
        "notes": plan.notes,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "committed_at": plan.committed_at.isoformat() if plan.committed_at else None,
        "needed_by": plan.needed_by.date().isoformat() if plan.needed_by else None,
        "production_run_id": str(plan.production_run_id) if plan.production_run_id else None,
        "lines": lines,
    }


async def commit_plan(
    db: AsyncSession, plan: ProductionPlan, actor: str = "operator", needed_by: datetime | None = None
) -> ProductionRun:
    included = [ln for ln in plan.lines if ln.included and ln.quantity > 0]
    if not included:
        raise ValueError("No included lines to commit")
    sku = included[0].part.sku if included[0].part else "GEN"
    batch = await next_batch_code(db, sku)
    if needed_by is not None:
        plan.needed_by = needed_by
    due = plan.needed_by
    run = ProductionRun(
        name=f"Plan {batch}",
        status=ProductionRunStatus.queued,
        notes=f"Committed from production plan {plan.id}",
        batch_code=batch,
        started_at=utcnow(),
        needed_by=due,
    )
    db.add(run)
    await db.flush()
    printer_ids = {ln.printer_id for ln in included if ln.printer_id}
    for pid in printer_ids:
        db.add(ProductionRunPrinter(production_run_id=run.id, printer_id=pid))
    # Merge same part
    by_part: dict[UUID, list[ProductionPlanLine]] = defaultdict(list)
    for ln in included:
        by_part[ln.part_id].append(ln)
    for part_id, group in by_part.items():
        qty = sum(ln.quantity for ln in group)
        gcode_id = group[0].gcode_file_id
        gcode = group[0].gcode_file
        if gcode_id and gcode is None:
            gcode = await db.get(GCodeFile, gcode_id)
        item = ProductionRunItem(
            production_run_id=run.id,
            part_id=part_id,
            gcode_file_id=gcode_id,
            required_qty=qty,
        )
        db.add(item)
        await db.flush()
        if gcode:
            preferred = group[0].printer_id
            jobs = await enqueue_jobs_for_item(db, item, gcode, preferred_printer_id=preferred)
            for job in jobs:
                job.batch_code = batch
                if preferred:
                    printer = await db.get(Printer, preferred)
                    if printer:
                        issues = gcode_printer_issues(gcode, printer)
                        if issues:
                            job.incompatibility_reason = format_incompatibility(printer.name, issues)
                            job.assigned_printer_id = None
    for ln in included:
        for oid in ln.order_ids or []:
            try:
                order = await db.get(Order, UUID(oid))
            except ValueError:
                order = None
            if order and not order.production_run_id:
                order.production_run_id = run.id
                if order.status in {OrderStatus.new, OrderStatus.awaiting_production}:
                    order.status = OrderStatus.in_production
    plan.status = "committed"
    plan.committed_at = utcnow()
    plan.production_run_id = run.id
    return run


async def recommended_next_jobs(db: AsyncSession) -> list[dict]:
    demand = await demand_by_part(db)
    printers = (
        await db.execute(select(Printer).options(selectinload(Printer.assigned_spool)).order_by(Printer.name))
    ).scalars().all()
    load = {p.id: await _workload_seconds(db, p.id) for p in printers}
    now = utcnow()
    ranked = sorted(
        demand.values(),
        key=lambda d: (
            0 if d["shortage"] > 0 else 1,
            d["due_at"] or datetime.max.replace(tzinfo=timezone.utc),
            d["oldest_order"] or datetime.max.replace(tzinfo=timezone.utc),
            -d["to_print"],
        ),
    )
    used_parts: set[UUID] = set()
    recs: list[dict] = []
    for printer in printers:
        if not printer.is_enabled:
            continue
        pick = None
        for row in ranked:
            part: Part = row["part"]
            if part.id in used_parts or row["to_print"] <= 0:
                continue
            gcode = await production_approved_gcode(db, part.id)
            issues = gcode_printer_issues(gcode, printer) if gcode else ["No G-code"]
            if issues:
                continue
            dummy = PrintJob(gcode_file_id=gcode.id if gcode else None, unattended_approved=True)
            dummy.gcode_file = gcode
            if await unattended_blocks(db, dummy, printer, now):
                continue
            if gcode and printer.assigned_spool:
                need_g = gcode.estimated_filament_grams or 0
                if need_g and (printer.assigned_spool.remaining_weight_g or 0) < need_g:
                    continue
            pick = (row, gcode)
            break
        if not pick:
            recs.append(
                {
                    "printer_id": str(printer.id),
                    "printer_name": printer.name,
                    "printer_status": printer.status.value,
                    "recommendation": None,
                    "reason": "No compatible shortage to print",
                }
            )
            continue
        row, gcode = pick
        part = row["part"]
        used_parts.add(part.id)
        qty = row["to_print"]
        start = _printer_free_at(printer, load.get(printer.id, 0), now)
        duration = (gcode.estimated_time_seconds if gcode else 3600) * jobs_needed(
            qty, gcode.quantity_per_file if gcode else 1
        )
        reason = (
            f"Required for Order {row['orders'][0].reference}"
            if row["orders"]
            else f"Inventory below target stock ({row['available']} available, target {row['target_stock']})"
        )
        recs.append(
            {
                "printer_id": str(printer.id),
                "printer_name": printer.name,
                "printer_status": printer.status.value,
                "recommendation": {
                    "part_id": str(part.id),
                    "part_sku": part.sku,
                    "part_name": part.name,
                    "quantity": qty,
                    "gcode_file_id": str(gcode.id) if gcode else None,
                    "gcode_filename": gcode.filename if gcode else None,
                    "estimated_start": start.isoformat(),
                    "estimated_end": (start + timedelta(seconds=duration or 3600)).isoformat(),
                    "required_filament_g": (gcode.estimated_filament_grams if gcode else 0)
                    * jobs_needed(qty, gcode.quantity_per_file if gcode else 1),
                },
                "reason": reason,
            }
        )
    return recs


async def queue_recommendation(db: AsyncSession, printer_id: UUID, part_id: UUID, quantity: int) -> ProductionRun:
    printer = await db.get(Printer, printer_id)
    part = await db.get(Part, part_id)
    if not printer or not part:
        raise ValueError("Unknown printer or part")
    gcode = await production_approved_gcode(db, part.id)
    if not gcode:
        raise ValueError(f"No G-code for {part.sku}")
    issues = gcode_printer_issues(gcode, printer)
    if issues:
        raise ValueError(format_incompatibility(printer.name, issues))
    batch = await next_batch_code(db, part.sku)
    run = ProductionRun(
        name=f"{part.sku} × {quantity}",
        status=ProductionRunStatus.queued,
        notes=f"Queued from recommended next job on {printer.name}",
        batch_code=batch,
    )
    db.add(run)
    await db.flush()
    db.add(ProductionRunPrinter(production_run_id=run.id, printer_id=printer.id))
    item = ProductionRunItem(
        production_run_id=run.id,
        part_id=part.id,
        gcode_file_id=gcode.id,
        required_qty=quantity,
    )
    db.add(item)
    await db.flush()
    jobs = await enqueue_jobs_for_item(db, item, gcode, preferred_printer_id=printer.id)
    for job in jobs:
        job.batch_code = batch
    return run


async def redistribute_printer(db: AsyncSession, printer_id: UUID) -> dict:
    printer = await db.get(Printer, printer_id)
    if not printer:
        raise ValueError("Printer not found")
    jobs = (
        await db.execute(
            select(PrintJob)
            .options(selectinload(PrintJob.gcode_file), selectinload(PrintJob.part))
            .where(
                PrintJob.assigned_printer_id == printer.id,
                PrintJob.status.in_({JobStatus.queued, JobStatus.held}),
            )
            .order_by(PrintJob.queue_position)
        )
    ).scalars().all()
    others = (
        await db.execute(
            select(Printer).where(Printer.id != printer.id, Printer.is_enabled.is_(True))
        )
    ).scalars().all()
    load = {p.id: await _workload_seconds(db, p.id) for p in others}
    now = utcnow()
    moved = []
    skipped = []
    for job in jobs:
        if job.status == JobStatus.printing:
            skipped.append({"job_id": str(job.id), "reason": "Actively printing — not moved"})
            continue
        alt, issues, start, end = await recommend_printer(db, job.gcode_file, others, load, now)
        if not alt:
            skipped.append(
                {
                    "job_id": str(job.id),
                    "part_sku": job.part.sku if job.part else None,
                    "reason": "; ".join(issues) or "No compatible alternative",
                }
            )
            continue
        job.assigned_printer_id = alt.id
        job.incompatibility_reason = ""
        load[alt.id] = load.get(alt.id, 0) + (job.estimated_time_seconds or 0)
        moved.append(
            {
                "job_id": str(job.id),
                "part_sku": job.part.sku if job.part else None,
                "from_printer": printer.name,
                "to_printer": alt.name,
                "estimated_start": start.isoformat() if start else None,
                "estimated_end": end.isoformat() if end else None,
            }
        )
    return {
        "printer_id": str(printer.id),
        "printer_name": printer.name,
        "queued": len(jobs),
        "moved": moved,
        "skipped": skipped,
        "alternatives": [p.name for p in others],
    }
