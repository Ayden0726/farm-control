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
    Notification,
    NotificationType,
    Order,
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
from app.services.farm_settings import auto_part_ejection_enabled
from app.services.notifications import NotifyContext, notify, print_complete_copy, recently_notified

async def _ctx_for_job(db: AsyncSession, job: PrintJob, printer: Printer) -> NotifyContext:
    run_name = None
    if job.production_run_id:
        run = await db.get(ProductionRun, job.production_run_id)
        run_name = run.name if run else None
    gcode = await db.get(GCodeFile, job.gcode_file_id) if job.gcode_file_id else None
    filename = printer.current_file or (gcode.filename if gcode else None) or "print"
    return NotifyContext(
        printer_id=printer.id,
        printer_name=printer.name,
        job_id=job.id,
        job_label=filename,
        production_run_id=job.production_run_id,
        production_run_name=run_name,
        quantity=job.quantity_produced,
    )


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
    assume_ejection = (not failed) and await auto_part_ejection_enabled(db)
    extra = dict(printer.extra_config or {})
    extra.setdefault("sim", {})
    if assume_ejection:
        printer.status = PrinterStatus.idle
        printer.current_file = None
        printer.progress_percent = 0
        extra["sim"]["status"] = "idle"
        extra["sim"]["progress_percent"] = 0
        extra["sim"]["current_file"] = None
    else:
        printer.status = PrinterStatus.waiting_for_bed_clear
        printer.progress_percent = 100 if not failed else printer.progress_percent
        extra["sim"]["status"] = "waiting_for_bed_clear"
    printer.extra_config = extra
    printer.time_remaining_seconds = 0
    duration = int(_elapsed_print_seconds(job, now))
    printer.total_print_seconds += duration
    printer.total_jobs += 1

    if failed:
        job.status = JobStatus.failed
        job.fail_reason = reason or "Print failed"
        printer.failed_jobs += 1
        printer.last_error = job.fail_reason
        ctx = await _ctx_for_job(db, job, printer)
        ctx.duration_seconds = duration
        await notify(
            db,
            NotificationType.print_failed,
            f"{printer.name} — Print Failed",
            (
                f"{ctx.job_label} failed on {printer.name}.\n\n"
                f"Reason: {job.fail_reason}\n"
                f"Production Run: {ctx.production_run_name or '—'}\n\n"
                "The printer is waiting for bed clear before it can take another job."
            ),
            severity="error",
            entity_type="job",
            entity_id=job.id,
            ctx=ctx,
        )
        await notify(
            db,
            NotificationType.bed_needs_clearing,
            f"{printer.name} — Bed needs clearing",
            f"Remove the failed print from {printer.name} before the next queued job can start.",
            severity="warning",
            entity_type="printer",
            entity_id=printer.id,
            ctx=ctx,
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
    if job.part_id:
        try:
            from app.models import Part
            from app.services.costing import estimate_part_cost

            part = await db.get(Part, job.part_id)
            if part:
                await estimate_part_cost(db, part, persist=True)
        except Exception:
            logger.debug("part cost snapshot failed", exc_info=True)

    spool = None
    if printer.assigned_spool_id:
        spool = await db.get(FilamentSpool, printer.assigned_spool_id)
    if spool and job.estimated_filament_grams:
        from app.services.filament import consume_for_job

        await consume_for_job(db, spool, job, printer)
        if spool.remaining_weight_g <= spool.low_stock_threshold_g:
            await notify(
                db,
                NotificationType.filament_low,
                f"Low filament: {spool.public_code or spool.name}",
                f"{spool.remaining_weight_g:.0f} g remaining of {spool.material} {spool.color} on {printer.name}.",
                severity="warning",
                entity_type="spool",
                entity_id=spool.id,
                ctx=NotifyContext(printer_id=printer.id, printer_name=printer.name),
            )

    ctx = await _ctx_for_job(db, job, printer)
    ctx.duration_seconds = duration
    ctx.extra = {"quantity": job.quantity_produced, "completed_at": now.isoformat()}
    try:
        from app.services.farm_settings import get_mes
        from app.services.camera import fetch_snapshot

        mes = await get_mes(db)
        if mes.get("include_camera_in_notifications"):
            data, status = await fetch_snapshot(printer)
            if data:
                dest = __import__("app.config", fromlist=["get_settings"]).get_settings().snapshots_dir / f"job-{job.id}.jpg"
                dest.write_bytes(data)
                ctx.extra["snapshot_path"] = str(dest)
                ctx.extra["camera_status"] = status
    except Exception:
        logger.debug("optional camera snapshot for notification failed", exc_info=True)
    title, body = print_complete_copy(
        printer.name,
        ctx.job_label or "print",
        ctx.production_run_name,
        job.quantity_produced,
        duration,
        now,
        assume_ejection=assume_ejection,
    )
    await notify(
        db,
        NotificationType.print_completed,
        title,
        body,
        entity_type="job",
        entity_id=job.id,
        ctx=ctx,
    )
    if not assume_ejection:
        await notify(
            db,
            NotificationType.bed_needs_clearing,
            f"{printer.name} — Bed needs clearing",
            (
                f"{ctx.job_label} is finished on {printer.name}.\n\n"
                "Status: Waiting for Bed Clear\n"
                "Confirm the bed is empty to release the next queued job."
            ),
            severity="warning",
            entity_type="printer",
            entity_id=printer.id,
            ctx=ctx,
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
            f"{run.name} — Production complete",
            f"All required prints for {run.name} have finished. QC may still be outstanding.",
            entity_type="production_run",
            entity_id=run.id,
            ctx=NotifyContext(production_run_id=run.id, production_run_name=run.name),
        )
        orders = (await db.execute(select(Order).where(Order.production_run_id == run.id))).scalars().all()
        for order in orders:
            await notify(
                db,
                NotificationType.order_production_complete,
                f"Order {order.reference} finished production",
                f"Printing for order {order.reference} ({order.customer_name or 'customer'}) is complete. QC and fulfilment may still be outstanding.",
                entity_type="order",
                entity_id=order.id,
                ctx=NotifyContext(
                    order_id=order.id,
                    order_reference=order.reference,
                    production_run_id=run.id,
                    production_run_name=run.name,
                ),
            )
            from app.services.orders import refresh_order_status

            await db.refresh(order, attribute_names=["part_needs", "production_run", "lines"])
            await refresh_order_status(db, order)


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
        if printer.status != PrinterStatus.offline:
            await notify(
                db,
                NotificationType.printer_offline,
                f"{printer.name} went offline unexpectedly",
                str(exc),
                severity="error",
                entity_type="printer",
                entity_id=printer.id,
                ctx=NotifyContext(printer_id=printer.id, printer_name=printer.name),
            )
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
                f"{printer.name} went offline unexpectedly",
                snap.error or f"{printer.name} stopped responding. Check power, network, and the printer adapter.",
                severity="error",
                entity_type="printer",
                entity_id=printer.id,
                ctx=NotifyContext(printer_id=printer.id, printer_name=printer.name),
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
        if printer.status != PrinterStatus.error:
            await notify(
                db,
                NotificationType.printer_error,
                f"{printer.name} reported an error",
                snap.error or f"{printer.name} entered an error state.",
                severity="error",
                entity_type="printer",
                entity_id=printer.id,
                ctx=NotifyContext(printer_id=printer.id, printer_name=printer.name),
            )
        printer.status = PrinterStatus.error
    elif snap.status == "printing":
        printer.status = PrinterStatus.printing
    elif snap.status == "paused":
        printer.status = PrinterStatus.paused
    else:
        printer.status = PrinterStatus.idle


async def gcode_compatible(db: AsyncSession, gcode_id: UUID, printer_id: UUID) -> bool:
    from app.services.compatibility import allowlist_ok, gcode_printer_issues

    printer = await db.get(Printer, printer_id)
    gcode = await db.get(GCodeFile, gcode_id)
    if not printer:
        return False
    if not await allowlist_ok(db, gcode_id, printer_id):
        return False
    return not gcode_printer_issues(gcode, printer)


async def printer_allowed_for_job(db: AsyncSession, job: PrintJob, printer: Printer) -> bool:
    from app.services.compatibility import format_incompatibility, job_printer_issues, unattended_blocks

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
    issues = await job_printer_issues(db, job, printer)
    if issues:
        job.incompatibility_reason = format_incompatibility(printer.name, issues)
        if job.compatibility_override:
            return True
        return False
    block = await unattended_blocks(db, job, printer)
    if block and not job.compatibility_override:
        job.hold_reason = job.hold_reason or "supervision_required"
        return False
    if job.incompatibility_reason:
        job.incompatibility_reason = ""
    return True


async def spool_sufficient(db: AsyncSession, printer: Printer, job: PrintJob) -> bool:
    from app.models import GCodeFile
    from app.services.filament import job_filament_check

    spool = await db.get(FilamentSpool, printer.assigned_spool_id) if printer.assigned_spool_id else None
    gcode = await db.get(GCodeFile, job.gcode_file_id) if job.gcode_file_id else None
    check = job_filament_check(job, printer, spool, gcode)
    job.filament_required_g = check["required_g"]
    job.filament_available_g = check["available_g"]
    if check["ok"]:
        if job.hold_reason == "insufficient_filament":
            job.hold_reason = None
        return True
    job.hold_reason = "insufficient_filament"
    if not await recently_notified(db, NotificationType.filament_low.value, printer.id, hours=6):
        await notify(
            db,
            NotificationType.filament_low,
            f"{printer.name}: insufficient filament",
            " ".join(check["reasons"]),
            severity="warning",
            entity_type="printer",
            entity_id=printer.id,
            ctx=NotifyContext(printer_id=printer.id, printer_name=printer.name, job_id=job.id),
        )
    return False


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
    await _maybe_notify_maintenance(db, printers)
    await assign_jobs(db)
    await _maybe_reorder(db)
    await _maybe_backup(db)
    try:
        from app.services.maintenance_rules import evaluate_maintenance

        await evaluate_maintenance(db)
    except Exception:
        logger.exception("maintenance evaluation failed")


async def _maybe_notify_maintenance(db: AsyncSession, printers: list[Printer]) -> None:
    from datetime import timedelta
    cutoff = utcnow() - timedelta(hours=24)
    for printer in printers:
        hours = printer.total_print_seconds / 3600.0
        remaining = (printer.maintenance_interval_hours or 200) - hours
        if remaining > 5:
            continue
        recent = (
            await db.execute(
                select(Notification).where(
                    Notification.type == NotificationType.maintenance_due.value,
                    Notification.printer_id == printer.id,
                    Notification.created_at >= cutoff,
                )
            )
        ).scalars().first()
        if recent:
            continue
        await notify(
            db,
            NotificationType.maintenance_due,
            f"{printer.name} — maintenance due",
            (
                f"{printer.name} has {hours:.1f} print hours against a {printer.maintenance_interval_hours:.0f} hour interval "
                f"({remaining:.1f} h remaining)."
            ),
            severity="warning",
            entity_type="printer",
            entity_id=printer.id,
            ctx=NotifyContext(printer_id=printer.id, printer_name=printer.name),
        )


async def _maybe_reorder(db: AsyncSession) -> None:
    from datetime import datetime, timezone

    from app.models import AppSetting
    from app.services.reorder import run_reorder_pass

    row = await db.get(AppSetting, "filament_reorder_last")
    last = None
    if row and isinstance(row.value, dict) and row.value.get("at"):
        try:
            last = datetime.fromisoformat(str(row.value["at"]).replace("Z", "+00:00"))
        except ValueError:
            last = None
    now = utcnow()
    if last and (now - last).total_seconds() < 60:
        return
    await run_reorder_pass(db)
    try:
        from app.services.hardware import run_hardware_reorder_pass

        await run_hardware_reorder_pass(db)
    except Exception:
        logger.exception("hardware reorder failed")


async def _maybe_backup(db: AsyncSession) -> None:
    from app.models import AppSetting

    row = await db.get(AppSetting, "last_scheduled_backup")
    last = None
    if row and isinstance(row.value, dict) and row.value.get("at"):
        try:
            last = datetime.fromisoformat(str(row.value["at"]).replace("Z", "+00:00"))
        except ValueError:
            last = None
    now = utcnow()
    if last and (now - last).total_seconds() < 86400:
        return
    try:
        from app.services.backups import create_backup, notify_failed_backups

        await create_backup(db, kind="scheduled")
        if row:
            row.value = {"at": now.isoformat()}
        else:
            db.add(AppSetting(key="last_scheduled_backup", value={"at": now.isoformat()}))
        await notify_failed_backups(db)
    except Exception:
        logger.exception("scheduled backup failed")
