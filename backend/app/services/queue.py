from __future__ import annotations

import math
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    GCodeFile,
    JobStatus,
    PrintJob,
    ProductionRun,
    ProductionRunItem,
    ProductionRunStatus,
    utcnow,
)
from app.util import jobs_needed, new_qr_token


async def next_queue_position(db: AsyncSession) -> int:
    result = await db.execute(select(PrintJob.queue_position).order_by(PrintJob.queue_position.desc()).limit(1))
    current = result.scalar_one_or_none()
    return (current or 0) + 1


async def enqueue_jobs_for_item(
    db: AsyncSession,
    item: ProductionRunItem,
    gcode: GCodeFile,
    preferred_printer_id: UUID | None = None,
) -> list[PrintJob]:
    already = await db.execute(
        select(PrintJob).where(
            PrintJob.production_run_item_id == item.id,
            PrintJob.status.in_(
                [JobStatus.queued, JobStatus.held, JobStatus.printing, JobStatus.paused]
            ),
        )
    )
    active = list(already.scalars())
    produced_or_queued = item.printed_qty + sum(j.quantity_produced for j in active)
    still_needed = max(0, item.required_qty - produced_or_queued)
    n = jobs_needed(still_needed, gcode.quantity_per_file)
    created: list[PrintJob] = []
    pos = await next_queue_position(db)
    for _ in range(n):
        job = PrintJob(
            production_run_id=item.production_run_id,
            production_run_item_id=item.id,
            gcode_file_id=gcode.id,
            part_id=item.part_id,
            assigned_printer_id=preferred_printer_id,
            status=JobStatus.queued,
            queue_position=pos,
            quantity_produced=gcode.quantity_per_file,
            estimated_filament_grams=gcode.estimated_filament_grams,
            estimated_time_seconds=gcode.estimated_time_seconds,
            qr_token=new_qr_token(),
        )
        db.add(job)
        created.append(job)
        pos += 1
    if item.production_run_id:
        run = await db.get(ProductionRun, item.production_run_id)
        if run and run.status == ProductionRunStatus.draft:
            run.status = ProductionRunStatus.queued
    await db.flush()
    return created


async def reorder_job(db: AsyncSession, job_id: UUID, direction: str) -> PrintJob | None:
    job = await db.get(PrintJob, job_id)
    if not job or job.status not in {JobStatus.queued, JobStatus.held}:
        return job
    stmt = select(PrintJob).where(PrintJob.status.in_([JobStatus.queued, JobStatus.held]))
    if direction == "up":
        stmt = stmt.where(PrintJob.queue_position < job.queue_position).order_by(
            PrintJob.queue_position.desc()
        )
    else:
        stmt = stmt.where(PrintJob.queue_position > job.queue_position).order_by(
            PrintJob.queue_position.asc()
        )
    other = (await db.execute(stmt.limit(1))).scalar_one_or_none()
    if other:
        job.queue_position, other.queue_position = other.queue_position, job.queue_position
        await db.flush()
    return job


async def set_job_position(db: AsyncSession, job_id: UUID, new_position: int) -> PrintJob | None:
    job = await db.get(PrintJob, job_id)
    if not job:
        return None
    job.queue_position = new_position
    await db.flush()
    return job
