from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.models import (
    GCodeFile,
    JobStatus,
    Part,
    PrintJob,
    ProductionRun,
    ProductionRunItem,
    ProductionRunPrinter,
    ProductionRunStatus,
    User,
)
from app.schemas import ProductionRunIn, ProductionRunOut
from app.serialize import run_out
from app.services.queue import enqueue_jobs_for_item

router = APIRouter(prefix="/production-runs", tags=["production"])

_LOAD = (
    selectinload(ProductionRun.items).selectinload(ProductionRunItem.part),
    selectinload(ProductionRun.items).selectinload(ProductionRunItem.gcode_file),
    selectinload(ProductionRun.printers),
    selectinload(ProductionRun.jobs),
)


@router.get("", response_model=list[ProductionRunOut])
async def list_runs(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    rows = (
        await db.execute(select(ProductionRun).options(*_LOAD).order_by(ProductionRun.created_at.desc()))
    ).scalars().all()
    return [run_out(r) for r in rows]


@router.post("", response_model=ProductionRunOut)
async def create_run(
    payload: ProductionRunIn, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    run = ProductionRun(
        name=payload.name,
        notes=payload.notes,
        status=ProductionRunStatus.queued if payload.start_immediately else ProductionRunStatus.draft,
    )
    db.add(run)
    await db.flush()
    from app.services.codes import next_batch_code

    run.batch_code = await next_batch_code(db, payload.name)
    for pid in payload.printer_ids:
        db.add(ProductionRunPrinter(production_run_id=run.id, printer_id=pid))
    for item_in in payload.items:
        part = await db.get(Part, item_in.part_id)
        if not part:
            raise HTTPException(400, f"Unknown part {item_in.part_id}")
        gcode = None
        if item_in.gcode_file_id:
            gcode = await db.get(GCodeFile, item_in.gcode_file_id)
        if not gcode:
            gcode = (
                await db.execute(
                    select(GCodeFile)
                    .where(GCodeFile.part_id == part.id, GCodeFile.is_archived.is_(False))
                    .order_by(GCodeFile.version.desc())
                )
            ).scalars().first()
        item = ProductionRunItem(
            production_run_id=run.id,
            part_id=part.id,
            gcode_file_id=gcode.id if gcode else None,
            required_qty=item_in.required_qty,
        )
        db.add(item)
        await db.flush()
        if gcode and payload.start_immediately:
            await enqueue_jobs_for_item(db, item, gcode)
    await db.commit()
    run = (
        await db.execute(select(ProductionRun).options(*_LOAD).where(ProductionRun.id == run.id))
    ).scalar_one()
    return run_out(run)


@router.get("/{run_id}", response_model=ProductionRunOut)
async def get_run(run_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    run = (
        await db.execute(select(ProductionRun).options(*_LOAD).where(ProductionRun.id == run_id))
    ).scalar_one_or_none()
    if not run:
        raise HTTPException(404, "Production run not found")
    return run_out(run)


@router.get("/{run_id}/filament-check")
async def run_filament_check(run_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    from app.services.filament import production_filament_check

    run = (
        await db.execute(select(ProductionRun).options(*_LOAD).where(ProductionRun.id == run_id))
    ).scalar_one_or_none()
    if not run:
        raise HTTPException(404, "Production run not found")
    return await production_filament_check(db, run)


@router.post("/{run_id}/pause", response_model=ProductionRunOut)
async def pause_run(run_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    run = await db.get(ProductionRun, run_id)
    if not run:
        raise HTTPException(404, "Not found")
    run.status = ProductionRunStatus.paused
    jobs = (
        await db.execute(
            select(PrintJob).where(
                PrintJob.production_run_id == run.id, PrintJob.status == JobStatus.queued
            )
        )
    ).scalars().all()
    for job in jobs:
        job.status = JobStatus.held
    await db.commit()
    run = (
        await db.execute(select(ProductionRun).options(*_LOAD).where(ProductionRun.id == run_id))
    ).scalar_one()
    return run_out(run)


@router.post("/{run_id}/resume", response_model=ProductionRunOut)
async def resume_run(run_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    run = await db.get(ProductionRun, run_id)
    if not run:
        raise HTTPException(404, "Not found")
    run.status = ProductionRunStatus.in_progress
    jobs = (
        await db.execute(
            select(PrintJob).where(
                PrintJob.production_run_id == run.id, PrintJob.status == JobStatus.held
            )
        )
    ).scalars().all()
    for job in jobs:
        job.status = JobStatus.queued
    await db.commit()
    run = (
        await db.execute(select(ProductionRun).options(*_LOAD).where(ProductionRun.id == run_id))
    ).scalar_one()
    return run_out(run)


@router.post("/{run_id}/cancel", response_model=ProductionRunOut)
async def cancel_run(run_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    run = await db.get(ProductionRun, run_id)
    if not run:
        raise HTTPException(404, "Not found")
    run.status = ProductionRunStatus.cancelled
    jobs = (
        await db.execute(
            select(PrintJob).where(
                PrintJob.production_run_id == run.id,
                PrintJob.status.in_([JobStatus.queued, JobStatus.held]),
            )
        )
    ).scalars().all()
    for job in jobs:
        job.status = JobStatus.cancelled
    await db.commit()
    run = (
        await db.execute(select(ProductionRun).options(*_LOAD).where(ProductionRun.id == run_id))
    ).scalar_one()
    return run_out(run)


@router.post("/{run_id}/requeue-scrap", response_model=ProductionRunOut)
async def requeue_scrap(run_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    run = (
        await db.execute(select(ProductionRun).options(*_LOAD).where(ProductionRun.id == run_id))
    ).scalar_one_or_none()
    if not run:
        raise HTTPException(404, "Not found")
    for item in run.items:
        if item.failed_qc <= 0 or not item.gcode_file:
            continue
        extra = item.failed_qc
        item.required_qty += extra
        item.failed_qc = 0
        await enqueue_jobs_for_item(db, item, item.gcode_file)
    if run.status == ProductionRunStatus.completed:
        run.status = ProductionRunStatus.queued
    await db.commit()
    run = (
        await db.execute(select(ProductionRun).options(*_LOAD).where(ProductionRun.id == run_id))
    ).scalar_one()
    return run_out(run)
