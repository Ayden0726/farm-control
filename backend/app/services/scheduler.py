from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.adapters import build_adapter
from app.config import get_settings
from app.models import (
    FilamentSpool,
    GCodeFile,
    GCodePrinterCompat,
    JobStatus,
    NotificationType,
    PrintJob,
    Printer,
    PrinterStatus,
    ProductionRun,
    ProductionRunItem,
    ProductionRunPrinter,
    ProductionRunStatus,
    QcBatch,
    QcStatus,
    utcnow,
)
from app.services.notifications import notify

logger = logging.getLogger("farmos.scheduler")


def _elapsed_print_seconds(job: PrintJob, now: datetime) -> float:
    if not job.started_at:
        return 0
    started = job.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    paused = job.pause_seconds or 0
    if job.status == JobStatus.paused and job.paused_at:
        paused_at = job.paused_at
        if paused_at.tzinfo is None:
            paused_at = paused_at.replace(tzinfo=timezone.utc)
        paused += (now - paused_at).total_seconds()
    return max(0.0, (now - started).total_seconds() - paused)


async def complete_job(db: AsyncSession, job: PrintJob, printer: Printer, failed: bool = False, reason: str | None = None) -> None:
    now = utcnow()
    job.completed_at = now
    job.progress_percent = 100 if not failed else job.progress_percent
    printer.current_job_id = None
    printer.status = PrinterStatus.waiting_for_bed_clear
    printer.progress_percent = 100 if not failed else printer.progress_percent
    printer.time_remaining_seconds = 0
    duration = int(_elapsed_print_seconds(job, now))
    printer.total_print_seconds += duration
    printer.total_jobs += 1

    if failed:
        job.status = JobStatus.failed
        job.fail_reason = reason or "Print failed"
        printer.failed_jobs += 1
        printer.last_error = job.fail_reason
        await notify(
            db,
            NotificationType.print_failed,
            f"{printer.name}: print failed",
            job.fail_reason or "",
            severity="error",
            entity_type="job",
            entity_id=job.id,
        )
        await notify(
            db,
            NotificationType.bed_needs_clearing,
            f"{printer.name} waiting for bed clear",
            "Remove failed print before the next job can start.",
            severity="warning",
            entity_type="printer",
            entity_id=printer.id,
        )
        return

    job.status = JobStatus.completed
    if job.production_run_item_id:
        item = await db.get(ProductionRunItem, job.production_run_item_id)
        if item:
            item.printed_qty += job.quantity_produced
    db.add(
        QcBatch(
            job_id=job.id,
            part_id=job.part_id,
            production_run_item_id=job.production_run_item_id,
            quantity=job.quantity_produced,
            status=QcStatus.awaiting_qc,
        )
    )

    spool = None
    if printer.assigned_spool_id:
        spool = await db.get(FilamentSpool, printer.assigned_spool_id)
    if spool and job.estimated_filament_grams:
        used = job.estimated_filament_grams
        spool.remaining_weight_g = max(0, spool.remaining_weight_g - used)
        job.filament_used_grams = used
        job.spool_id = spool.id
        if spool.initial_weight_g:
            job.filament_cost = (spool.cost / spool.initial_weight_g) * used
        if spool.remaining_weight_g <= spool.low_stock_threshold_g:
            await notify(
                db,
                NotificationType.filament_low,
                f"Low filament: {spool.name}",
                f"{spool.remaining_weight_g:.0f} g remaining of {spool.material} {spool.color}.",
                severity="warning",
                entity_type="spool",
                entity_id=spool.id,
            )

    filename = printer.current_file or "print"
    await notify(
        db,
        NotificationType.print_completed,
        f"{printer.name} finished {filename}",
        f"{job.quantity_produced} part(s) awaiting QC. Bed must be cleared before the next job.",
        entity_type="job",
        entity_id=job.id,
    )
    await notify(
        db,
        NotificationType.bed_needs_clearing,
        f"{printer.name} waiting for bed clear",
        "Confirm the bed is empty to release the next queued job.",
        severity="warning",
        entity_type="printer",
        entity_id=printer.id,
    )
    if job.production_run_id:
        await maybe_complete_run(db, job.production_run_id)


async def maybe_complete_run(db: AsyncSession, run_id: UUID) -> None:
    run = await db.get(ProductionRun, run_id)
    if not run:
        return
    await db.refresh(run, attribute_names=["items", "jobs"])
    items = (
        await db.execute(select(ProductionRunItem).where(ProductionRunItem.production_run_id == run_id))
    ).scalars().all()
    active = (
        await db.execute(
            select(PrintJob).where(
                PrintJob.production_run_id == run_id,
                PrintJob.status.in_(
                    [JobStatus.queued, JobStatus.held, JobStatus.printing, JobStatus.paused]
                ),
            )
        )
    ).scalars().all()
    if items and all(item.printed_qty >= item.required_qty for item in items) and not active:
        run.status = ProductionRunStatus.completed
        run.completed_at = utcnow()
        await notify(
            db,
            NotificationType.production_run_completed,
            f"Production run complete: {run.name}",
            "All required prints have finished. QC may still be outstanding.",
            entity_type="production_run",
            entity_id=run.id,
        )


async def update_simulated_job(db: AsyncSession, printer: Printer, job: PrintJob) -> None:
    settings = get_settings()
    now = utcnow()
    if job.status == JobStatus.paused:
        return
    scale = settings.simulated_time_scale
    elapsed_wall = _elapsed_print_seconds(job, now)
    simulated = elapsed_wall * scale
    est = max(1, job.estimated_time_seconds or 3600)
    pct = min(100.0, simulated / est * 100)
    remaining_sim = max(0.0, est - simulated)
    remaining_wall = int(remaining_sim / scale)
    job.progress_percent = pct
    printer.progress_percent = pct
    printer.time_remaining_seconds = remaining_wall
    printer.status = PrinterStatus.printing
    sim = dict(printer.extra_config or {})
    sim.setdefault("sim", {})
    sim["sim"]["status"] = "printing"
    sim["sim"]["progress_percent"] = pct
    sim["sim"]["time_remaining_seconds"] = remaining_wall
    sim["sim"]["current_file"] = printer.current_file
    printer.extra_config = sim
    if pct >= 100:
        await complete_job(db, job, printer)


async def poll_live_printer(db: AsyncSession, printer: Printer) -> None:
    if printer.status == PrinterStatus.waiting_for_bed_clear:
        # Hardware may report idle; FarmOS keeps the printer locked until the operator confirms.
        return
    try:
        adapter = build_adapter(printer)
        snap = await adapter.get_status()
    except Exception as exc:
        printer.status = PrinterStatus.offline
        printer.last_error = str(exc)
        return
    printer.last_seen_at = utcnow()
    printer.nozzle_temp = snap.nozzle_temp
    printer.bed_temp = snap.bed_temp
    printer.target_nozzle = snap.target_nozzle
    printer.target_bed = snap.target_bed
    if snap.current_file:
        printer.current_file = snap.current_file
    printer.progress_percent = snap.progress_percent
    printer.time_remaining_seconds = snap.time_remaining_seconds
    if not snap.online:
        if printer.status != PrinterStatus.offline:
            await notify(
                db,
                NotificationType.printer_offline,
                f"{printer.name} went offline",
                snap.error or "",
                severity="error",
                entity_type="printer",
                entity_id=printer.id,
            )
        printer.status = PrinterStatus.offline
        printer.last_error = snap.error
        return
    printer.last_error = snap.error
    if printer.current_job_id:
        job = await db.get(PrintJob, printer.current_job_id)
        if job and job.status == JobStatus.printing:
            job.progress_percent = snap.progress_percent
            if snap.status == "paused":
                job.status = JobStatus.paused
                printer.status = PrinterStatus.paused
                if not job.paused_at:
                    job.paused_at = utcnow()
            elif snap.status == "error":
                await complete_job(db, job, printer, failed=True, reason=snap.error or "Printer error")
            elif snap.status in {"idle"} and snap.progress_percent >= 99:
                await complete_job(db, job, printer)
            elif snap.status == "printing":
                printer.status = PrinterStatus.printing
        return
    if snap.status == "error":
        printer.status = PrinterStatus.error
    elif snap.status == "printing":
        printer.status = PrinterStatus.printing
    elif snap.status == "paused":
        printer.status = PrinterStatus.paused
    else:
        printer.status = PrinterStatus.idle


async def gcode_compatible(db: AsyncSession, gcode_id: UUID, printer_id: UUID) -> bool:
    rows = (
        await db.execute(select(GCodePrinterCompat).where(GCodePrinterCompat.gcode_id == gcode_id))
    ).scalars().all()
    if not rows:
        return True
    return any(r.printer_id == printer_id for r in rows)


async def printer_allowed_for_job(db: AsyncSession, job: PrintJob, printer: Printer) -> bool:
    if job.assigned_printer_id and job.assigned_printer_id != printer.id:
        return False
    if job.production_run_id:
        allowed = (
            await db.execute(
                select(ProductionRunPrinter).where(
                    ProductionRunPrinter.production_run_id == job.production_run_id
                )
            )
        ).scalars().all()
        if allowed and printer.id not in {a.printer_id for a in allowed}:
            return False
    return await gcode_compatible(db, job.gcode_file_id, printer.id)


async def spool_sufficient(db: AsyncSession, printer: Printer, job: PrintJob) -> bool:
    if not printer.assigned_spool_id or not job.estimated_filament_grams:
        return True
    spool = await db.get(FilamentSpool, printer.assigned_spool_id)
    if not spool:
        return True
    if spool.remaining_weight_g < job.estimated_filament_grams * 1.08:
        await notify(
            db,
            NotificationType.filament_low,
            f"{printer.name}: spool may not have enough filament",
            f"{spool.name} has {spool.remaining_weight_g:.0f} g; job needs ~{job.estimated_filament_grams:.0f} g.",
            severity="warning",
            entity_type="printer",
            entity_id=printer.id,
        )
        return False
    return True


async def start_job_on_printer(db: AsyncSession, job: PrintJob, printer: Printer) -> None:
    gcode = await db.get(GCodeFile, job.gcode_file_id)
    if not gcode:
        job.status = JobStatus.failed
        job.fail_reason = "G-code missing"
        return
    adapter = build_adapter(printer)
    try:
        await adapter.upload_and_start(gcode.stored_path, gcode.filename)
    except Exception as exc:
        logger.exception("failed to start job on %s", printer.name)
        printer.last_error = str(exc)
        # Leave job queued so another printer can take it; mark this printer error if live
        if printer.adapter_type.value != "simulated":
            printer.status = PrinterStatus.error
        return
    now = utcnow()
    job.status = JobStatus.printing
    job.started_at = now
    job.actual_printer_id = printer.id
    job.assigned_printer_id = printer.id
    job.progress_percent = 0
    job.spool_id = printer.assigned_spool_id
    printer.status = PrinterStatus.printing
    printer.current_job_id = job.id
    printer.current_file = gcode.filename
    printer.progress_percent = 0
    printer.last_seen_at = now
    printer.target_nozzle = 250
    printer.target_bed = 80
    extra = dict(printer.extra_config or {})
    extra.setdefault("sim", {})
    extra["sim"].update({"status": "printing", "current_file": gcode.filename, "progress_percent": 0})
    printer.extra_config = extra
    if job.production_run_id:
        run = await db.get(ProductionRun, job.production_run_id)
        if run and run.status in {ProductionRunStatus.draft, ProductionRunStatus.queued}:
            run.status = ProductionRunStatus.in_progress
            run.started_at = run.started_at or now


async def assign_jobs(db: AsyncSession) -> None:
    printers = (
        await db.execute(
            select(Printer).where(
                Printer.is_enabled.is_(True),
                Printer.status == PrinterStatus.idle,
            )
        )
    ).scalars().all()
    if not printers:
        return
    jobs = (
        await db.execute(
            select(PrintJob)
            .where(PrintJob.status == JobStatus.queued)
            .order_by(PrintJob.queue_position.asc(), PrintJob.created_at.asc())
        )
    ).scalars().all()
    used: set[UUID] = set()
    for job in jobs:
        for printer in printers:
            if printer.id in used:
                continue
            if not await printer_allowed_for_job(db, job, printer):
                continue
            if not await spool_sufficient(db, printer, job):
                continue
            await start_job_on_printer(db, job, printer)
            if job.status == JobStatus.printing:
                used.add(printer.id)
                break


async def tick(db: AsyncSession) -> None:
    printers = (await db.execute(select(Printer).where(Printer.is_enabled.is_(True)))).scalars().all()
    for printer in printers:
        if printer.adapter_type.value == "simulated":
            printer.last_seen_at = utcnow()
            if printer.status == PrinterStatus.waiting_for_bed_clear:
                extra = dict(printer.extra_config or {})
                extra.setdefault("sim", {})["status"] = "waiting_for_bed_clear"
                printer.extra_config = extra
                printer.nozzle_temp = max(30, printer.target_nozzle * 0.4)
                printer.bed_temp = max(28, printer.target_bed * 0.5)
                continue
            if printer.current_job_id:
                job = await db.get(PrintJob, printer.current_job_id)
                if job and job.status in {JobStatus.printing, JobStatus.paused}:
                    adapter = build_adapter(printer)
                    snap = await adapter.get_status()
                    printer.nozzle_temp = snap.nozzle_temp
                    printer.bed_temp = snap.bed_temp
                    printer.target_nozzle = snap.target_nozzle
                    printer.target_bed = snap.target_bed
                    await update_simulated_job(db, printer, job)
                elif job and job.status in {JobStatus.completed, JobStatus.failed, JobStatus.cancelled}:
                    printer.current_job_id = None
                    if printer.status != PrinterStatus.waiting_for_bed_clear:
                        printer.status = PrinterStatus.idle
            elif printer.status not in {PrinterStatus.waiting_for_bed_clear, PrinterStatus.error}:
                printer.status = PrinterStatus.idle
                printer.progress_percent = 0
                printer.current_file = None
                printer.nozzle_temp = max(24, printer.nozzle_temp * 0.9)
                printer.bed_temp = max(22, printer.bed_temp * 0.9)
        else:
            await poll_live_printer(db, printer)
    await assign_jobs(db)
