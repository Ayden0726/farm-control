from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.models import (
    FilamentSpool,
    JobStatus,
    Notification,
    Order,
    OrderStatus,
    PrintJob,
    Printer,
    PrinterStatus,
    ProductionRun,
    ProductionRunItem,
    ProductionRunStatus,
    QcBatch,
    QcStatus,
    User,
)
from app.serialize import eta_iso, job_out, printer_out, run_out

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
async def dashboard(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    printers = (
        await db.execute(
            select(Printer)
            .options(selectinload(Printer.assigned_spool))
            .where(Printer.is_enabled.is_(True))
            .order_by(Printer.name)
        )
    ).scalars().all()
    jobs = (
        await db.execute(
            select(PrintJob)
            .options(
                selectinload(PrintJob.gcode_file),
                selectinload(PrintJob.part),
                selectinload(PrintJob.assigned_printer),
                selectinload(PrintJob.actual_printer),
                selectinload(PrintJob.production_run),
            )
            .where(
                PrintJob.status.in_(
                    [JobStatus.queued, JobStatus.held, JobStatus.printing, JobStatus.paused, JobStatus.failed]
                )
            )
            .order_by(PrintJob.queue_position)
        )
    ).scalars().all()
    runs = (
        await db.execute(
            select(ProductionRun)
            .options(
                selectinload(ProductionRun.items).selectinload(ProductionRunItem.part),
                selectinload(ProductionRun.items).selectinload(ProductionRunItem.gcode_file),
                selectinload(ProductionRun.printers),
                selectinload(ProductionRun.jobs),
            )
            .where(
                ProductionRun.status.in_(
                    [
                        ProductionRunStatus.queued,
                        ProductionRunStatus.in_progress,
                        ProductionRunStatus.paused,
                    ]
                )
            )
        )
    ).scalars().all()
    orders = (
        await db.execute(
            select(Order).where(
                Order.status.in_(
                    [
                        OrderStatus.new,
                        OrderStatus.awaiting_production,
                        OrderStatus.in_production,
                        OrderStatus.awaiting_qc,
                        OrderStatus.ready_to_ship,
                    ]
                )
            )
        )
    ).scalars().all()
    spools = (
        await db.execute(select(FilamentSpool).where(FilamentSpool.is_archived.is_(False)))
    ).scalars().all()
    failed_jobs = [j for j in jobs if j.status == JobStatus.failed]
    queued = [j for j in jobs if j.status in {JobStatus.queued, JobStatus.held}]
    printing = [j for j in jobs if j.status in {JobStatus.printing, JobStatus.paused}]
    waiting = [p for p in printers if p.status == PrinterStatus.waiting_for_bed_clear]
    low_spools = [s for s in spools if s.remaining_weight_g <= s.low_stock_threshold_g]
    unread = (
        await db.execute(select(Notification).where(Notification.is_read.is_(False)))
    ).scalars().all()
    awaiting_qc = (
        await db.execute(select(QcBatch).where(QcBatch.status == QcStatus.awaiting_qc))
    ).scalars().all()

    now = datetime.now(timezone.utc)
    printer_cards = []
    for printer in printers:
        job = next((j for j in printing if j.actual_printer_id == printer.id or printer.current_job_id == j.id), None)
        run_name = job.production_run.name if job and job.production_run else None
        remaining_qty = None
        completed_qty = None
        if job and job.production_run_item_id:
            for run in runs:
                for item in run.items:
                    if item.id == job.production_run_item_id:
                        remaining_qty = item.remaining_qty
                        completed_qty = item.passed_qc
        cost = 0.0
        grams = job.estimated_filament_grams if job else 0
        if job and printer.assigned_spool and printer.assigned_spool.initial_weight_g:
            cost = (printer.assigned_spool.cost / printer.assigned_spool.initial_weight_g) * grams * (
                printer.progress_percent / 100 if printer.progress_percent else 0
            )
        printer_cards.append(
            {
                **printer_out(printer).model_dump(mode="json"),
                "current_part": job.part.sku if job and job.part else None,
                "production_run": run_name,
                "quantity_completed": completed_qty,
                "quantity_remaining": remaining_qty,
                "eta": eta_iso(printer.time_remaining_seconds),
                "filament_name": printer.assigned_spool.name if printer.assigned_spool else None,
                "filament_material": printer.assigned_spool.material if printer.assigned_spool else None,
                "estimated_filament_used_g": round(grams * (printer.progress_percent / 100), 1)
                if grams
                else 0,
                "estimated_filament_cost": round(cost, 2),
                "job": job_out(job).model_dump(mode="json") if job else None,
            }
        )

    from app.models import FinishedPartStock, HardwareItem
    from datetime import timedelta as _td

    parts_stock = (await db.execute(select(FinishedPartStock))).scalars().all()
    low_parts = 0
    from app.models import Part as PartModel

    parts_by_id = {p.id: p for p in (await db.execute(select(PartModel))).scalars().all()}
    for stock in parts_stock:
        part = parts_by_id.get(stock.part_id)
        min_s = part.min_stock if part else 0
        if stock.quantity_available < (min_s or 0) and min_s:
            low_parts += 1
    hw_rows = (await db.execute(select(HardwareItem).where(HardwareItem.is_active.is_(True)))).scalars().all()
    low_hw = [h for h in hw_rows if h.quantity_available < (h.min_stock or 0)]
    pack_hw = [h for h in low_hw if (h.category or "").lower() in {"packaging", "shipping", "labels"}]
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    qc_today = (
        await db.execute(select(QcBatch).where(QcBatch.inspected_at >= today))
    ).scalars().all()
    failed_today = sum(b.failed or 0 for b in qc_today)
    printed_today = sum(b.quantity or 0 for b in qc_today)
    passed_today = sum(b.passed or 0 for b in qc_today)
    defects: dict[str, int] = {}
    for b in qc_today:
        if b.failure_reason and b.failed:
            defects[b.failure_reason] = defects.get(b.failure_reason, 0) + b.failed
    common_defect = max(defects, key=defects.get) if defects else None
    completed_jobs_today = (
        await db.execute(
            select(PrintJob).where(PrintJob.status == JobStatus.completed, PrintJob.completed_at >= today)
        )
    ).scalars().all()
    shipped_today = [o for o in orders if o.status == OrderStatus.shipped]
    # utilisation
    enabled = printers
    printing_n = len([p for p in enabled if p.status == PrinterStatus.printing])
    util = round(100 * printing_n / max(1, len(enabled)), 1)
    revenue_today = sum(getattr(o, "revenue", 0) or 0 for o in (await db.execute(select(Order).where(Order.created_at >= today))).scalars().all())

    return {
        "generated_at": now.isoformat(),
        "counts": {
            "printing": len([p for p in printers if p.status == PrinterStatus.printing]),
            "idle": len([p for p in printers if p.status == PrinterStatus.idle]),
            "waiting_for_bed_clear": len(waiting),
            "offline": len([p for p in printers if p.status == PrinterStatus.offline]),
            "queued_jobs": len(queued),
            "failed_jobs": len(failed_jobs),
            "orders_waiting": len(
                [o for o in orders if o.status in {OrderStatus.new, OrderStatus.awaiting_production}]
            ),
            "orders_ready": len([o for o in orders if o.status == OrderStatus.ready_to_ship]),
            "low_filament": len(low_spools),
            "unread_notifications": len(unread),
            "awaiting_qc": len(awaiting_qc),
            "in_production_orders": len([o for o in orders if o.status == OrderStatus.in_production]),
            "ready_to_pack": len([o for o in orders if o.packing_status == "unpacked" and o.status == OrderStatus.ready_to_ship]),
        },
        "printers": printer_cards,
        "waiting_for_bed_clear": [printer_out(p).model_dump(mode="json") for p in waiting],
        "failed_jobs": [job_out(j).model_dump(mode="json") for j in failed_jobs],
        "upcoming_jobs": [job_out(j).model_dump(mode="json") for j in queued[:12]],
        "production_runs": [run_out(r).model_dump(mode="json") for r in runs],
        "orders_waiting": [
            {
                "id": str(o.id),
                "reference": o.reference,
                "customer_name": o.customer_name,
                "status": o.status.value,
            }
            for o in orders
            if o.status
            in {
                OrderStatus.new,
                OrderStatus.awaiting_production,
                OrderStatus.in_production,
                OrderStatus.awaiting_qc,
            }
        ],
        "orders_ready": [
            {"id": str(o.id), "reference": o.reference, "customer_name": o.customer_name, "status": o.status.value}
            for o in orders
            if o.status == OrderStatus.ready_to_ship
        ],
        "low_filament": [
            {
                "id": str(s.id),
                "name": s.name,
                "material": s.material,
                "color": s.color,
                "remaining_weight_g": s.remaining_weight_g,
                "assigned_printer_id": str(s.assigned_printer_id) if s.assigned_printer_id else None,
            }
            for s in low_spools
        ],
        "manufacturing": {
            "parts_low": low_parts,
            "hardware_low": len(low_hw),
            "packaging_low": len(pack_hw),
            "first_pass_yield": round(100 * passed_today / max(1, printed_today), 1) if printed_today else None,
            "failed_parts_today": failed_today,
            "most_common_defect": common_defect,
            "parts_produced_today": passed_today,
            "printer_utilisation_pct": util,
            "orders_new": len([o for o in orders if o.status == OrderStatus.new]),
            "waiting_production": len([o for o in orders if o.status == OrderStatus.awaiting_production]),
            "in_production": len([o for o in orders if o.status == OrderStatus.in_production]),
            "waiting_qc": len([o for o in orders if o.status == OrderStatus.awaiting_qc]),
            "ready_to_pack": len(
                [o for o in orders if o.status == OrderStatus.ready_to_ship and o.packing_status != "packed"]
            ),
            "ready_to_ship": len([o for o in orders if o.status == OrderStatus.ready_to_ship]),
            "revenue_today": round(revenue_today, 2),
            "print_cost_today": round(sum(j.filament_cost or 0 for j in completed_jobs_today), 2),
        },
    }
