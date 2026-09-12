from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.adapters import build_adapter
from app.db import get_db
from app.deps import get_current_user
from app.models import (
    FilamentSpool,
    GCodeFile,
    JobStatus,
    PrintJob,
    Printer,
    PrinterStatus,
    ProductionRunItem,
    User,
    utcnow,
)
from app.schemas import JobAction, JobOut
from app.serialize import job_out
from app.services.queue import next_queue_position, reorder_job, set_job_position
from app.services.scheduler import complete_job, start_job_on_printer

router = APIRouter(prefix="/queue", tags=["queue"])

_JOB_LOAD = (
    selectinload(PrintJob.gcode_file),
    selectinload(PrintJob.part),
    selectinload(PrintJob.assigned_printer),
    selectinload(PrintJob.actual_printer),
    selectinload(PrintJob.production_run),
    selectinload(PrintJob.spool),
)


async def _job(db: AsyncSession, job_id: UUID) -> PrintJob:
    job = (
        await db.execute(select(PrintJob).options(*_JOB_LOAD).where(PrintJob.id == job_id))
    ).scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.get("", response_model=list[JobOut])
async def list_jobs(
    status: str | None = None,
    history: bool = Query(False),
    printer_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(PrintJob).options(*_JOB_LOAD)
    if status:
        stmt = stmt.where(PrintJob.status == JobStatus(status))
    elif not history:
        stmt = stmt.where(
            PrintJob.status.in_(
                [JobStatus.queued, JobStatus.held, JobStatus.printing, JobStatus.paused]
            )
        )
    if printer_id:
        stmt = stmt.where(
            (PrintJob.assigned_printer_id == printer_id) | (PrintJob.actual_printer_id == printer_id)
        )
    stmt = stmt.order_by(PrintJob.queue_position.asc(), PrintJob.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [job_out(j) for j in rows]


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    return job_out(await _job(db, job_id))


@router.post("/{job_id}/pause", response_model=JobOut)
async def pause_job(job_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    job = await _job(db, job_id)
    if job.status == JobStatus.queued:
        job.status = JobStatus.held
    elif job.status == JobStatus.printing:
        printer = await db.get(Printer, job.actual_printer_id or job.assigned_printer_id)
        if printer:
            try:
                await build_adapter(printer).pause()
            except Exception as exc:
                raise HTTPException(400, f"Printer pause failed: {exc}")
            printer.status = PrinterStatus.paused
        job.status = JobStatus.paused
        job.paused_at = utcnow()
    else:
        raise HTTPException(400, "Job cannot be paused in its current state")
    await db.commit()
    return job_out(await _job(db, job.id))


@router.post("/{job_id}/resume", response_model=JobOut)
async def resume_job(job_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    job = await _job(db, job_id)
    if job.status == JobStatus.held:
        job.status = JobStatus.queued
    elif job.status == JobStatus.paused:
        printer = await db.get(Printer, job.actual_printer_id or job.assigned_printer_id)
        if printer:
            try:
                await build_adapter(printer).resume()
            except Exception as exc:
                raise HTTPException(400, f"Printer resume failed: {exc}")
            printer.status = PrinterStatus.printing
        if job.paused_at:
            job.pause_seconds += (utcnow() - job.paused_at).total_seconds()
            job.paused_at = None
        job.status = JobStatus.printing
    else:
        raise HTTPException(400, "Job is not paused")
    await db.commit()
    return job_out(await _job(db, job.id))


@router.post("/{job_id}/cancel", response_model=JobOut)
async def cancel_job(job_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    job = await _job(db, job_id)
    if job.status in {JobStatus.completed, JobStatus.cancelled}:
        raise HTTPException(400, "Job already finished")
    if job.status in {JobStatus.printing, JobStatus.paused}:
        printer = await db.get(Printer, job.actual_printer_id or job.assigned_printer_id)
        if printer:
            try:
                await build_adapter(printer).cancel()
            except Exception:
                pass
            printer.status = PrinterStatus.waiting_for_bed_clear
            printer.current_job_id = None
    job.status = JobStatus.cancelled
    job.completed_at = utcnow()
    await db.commit()
    return job_out(await _job(db, job.id))


@router.post("/{job_id}/reorder", response_model=JobOut)
async def reorder(job_id: UUID, payload: JobAction, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    if payload.position is not None:
        await set_job_position(db, job_id, payload.position)
    await db.commit()
    return job_out(await _job(db, job_id))


@router.post("/{job_id}/move-up", response_model=JobOut)
async def move_up(job_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    await reorder_job(db, job_id, "up")
    await db.commit()
    return job_out(await _job(db, job_id))


@router.post("/{job_id}/move-down", response_model=JobOut)
async def move_down(job_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    await reorder_job(db, job_id, "down")
    await db.commit()
    return job_out(await _job(db, job_id))


@router.post("/{job_id}/move", response_model=JobOut)
async def move_job(job_id: UUID, payload: JobAction, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    job = await _job(db, job_id)
    if not payload.printer_id:
        raise HTTPException(400, "printer_id is required")
    target = await db.get(Printer, payload.printer_id)
    if not target:
        raise HTTPException(404, "Target printer not found")
    if job.status in {JobStatus.printing, JobStatus.paused}:
        current = await db.get(Printer, job.actual_printer_id or job.assigned_printer_id)
        if current:
            try:
                await build_adapter(current).cancel()
            except Exception:
                pass
            current.status = PrinterStatus.waiting_for_bed_clear
            current.current_job_id = None
        job.status = JobStatus.queued
        job.started_at = None
        job.progress_percent = 0
        job.actual_printer_id = None
        job.queue_position = await next_queue_position(db)
    job.assigned_printer_id = target.id
    await db.commit()
    return job_out(await _job(db, job.id))


@router.post("/{job_id}/override-filament", response_model=JobOut)
async def override_filament(job_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    job = await _job(db, job_id)
    job.filament_override = True
    job.hold_reason = None
    await db.commit()
    return job_out(await _job(db, job.id))


@router.get("/{job_id}/filament-check")
async def job_filament_status(
    job_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    from app.services.filament import job_filament_check

    job = await _job(db, job_id)
    printer = None
    if job.assigned_printer_id or job.actual_printer_id:
        printer = await db.get(Printer, job.actual_printer_id or job.assigned_printer_id)
    if not printer:
        return {
            "ok": False,
            "required_g": job.estimated_filament_grams,
            "available_g": 0,
            "reasons": ["Job is not assigned to a printer yet."],
        }
    spool = await db.get(FilamentSpool, printer.assigned_spool_id) if printer.assigned_spool_id else None
    return job_filament_check(job, printer, spool, job.gcode_file)


@router.post("/{job_id}/override-compatibility", response_model=JobOut)
async def override_compatibility(
    job_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    from app.models import UserRole
    from app.services.audit import record_audit

    if user.role not in {UserRole.admin, UserRole.operator}:
        raise HTTPException(403, "Only administrators and production operators can override compatibility")
    job = await _job(db, job_id)
    job.compatibility_override = True
    if job.status == JobStatus.held and job.hold_reason in {"incompatible", "supervision_required"}:
        job.status = JobStatus.queued
        job.hold_reason = None
    await record_audit(
        db,
        action="compatibility_override",
        entity_type="job",
        entity_id=str(job.id),
        previous={"reason": job.incompatibility_reason},
        actor=user.email,
    )
    await db.commit()
    return job_out(await _job(db, job_id))
