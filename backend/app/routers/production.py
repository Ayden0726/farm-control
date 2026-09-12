from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.models import (
    FilamentTransaction,
    GCodeFile,
    JobStatus,
    Notification,
    Order,
    Part,
    PrintJob,
    Printer,
    ProductionPlan,
    ProductionRun,
    ProductionRunItem,
    ProductionRunPrinter,
    ProductionRunStatus,
    QcBatch,
    User,
)
from app.schemas import ProductionProductIn, ProductionRunIn, ProductionRunOut
from app.serialize import run_out
from app.services.production_expand import run_items_for_product
from app.services.queue import enqueue_jobs_for_item
from app.services.schedule_plan import needed_by_utc

router = APIRouter(prefix="/production-runs", tags=["production"])

_LOAD = (
    selectinload(ProductionRun.items).selectinload(ProductionRunItem.part),
    selectinload(ProductionRun.items).selectinload(ProductionRunItem.gcode_file),
    selectinload(ProductionRun.printers),
    selectinload(ProductionRun.jobs),
)


def _item_specs(payload_items) -> list[tuple[UUID, UUID | None, int]]:
    specs: list[tuple[UUID, UUID | None, int]] = []
    for item_in in payload_items:
        specs.append((item_in.part_id, item_in.gcode_file_id, max(1, item_in.required_qty)))
    return specs


async def _specs_from_product(
    db: AsyncSession, product_id: UUID, quantity: int, include_optional: bool
) -> tuple[list[tuple[UUID, UUID | None, int]], dict]:
    expanded = await run_items_for_product(db, product_id, quantity, include_optional)
    if not expanded:
        raise HTTPException(404, "Product not found")
    specs: list[tuple[UUID, UUID | None, int]] = []
    for row in expanded["items"]:
        gcode_id = UUID(row["gcode_file_id"]) if row["gcode_file_id"] else None
        specs.append((UUID(row["part_id"]), gcode_id, int(row["required_qty"])))
    return specs, expanded


async def _append_items(
    db: AsyncSession,
    run: ProductionRun,
    specs: list[tuple[UUID, UUID | None, int]],
    start: bool,
) -> None:
    loaded = (
        await db.execute(
            select(ProductionRunItem).where(ProductionRunItem.production_run_id == run.id)
        )
    ).scalars().all()
    existing = {(item.part_id, item.gcode_file_id): item for item in loaded}
    for part_id, gcode_id, qty in specs:
        part = await db.get(Part, part_id)
        if not part:
            raise HTTPException(400, f"Unknown part {part_id}")
        gcode = await db.get(GCodeFile, gcode_id) if gcode_id else None
        if gcode_id and not gcode:
            raise HTTPException(400, "Unknown G-code file")
        if not gcode:
            gcode = (
                await db.execute(
                    select(GCodeFile)
                    .where(GCodeFile.part_id == part.id, GCodeFile.is_archived.is_(False))
                    .order_by(GCodeFile.production_approved.desc(), GCodeFile.version.desc())
                )
            ).scalars().first()
        key = (part.id, gcode.id if gcode else None)
        item = existing.get(key)
        if item:
            item.required_qty += qty
        else:
            item = ProductionRunItem(
                production_run_id=run.id,
                part_id=part.id,
                gcode_file_id=gcode.id if gcode else None,
                required_qty=qty,
            )
            db.add(item)
            existing[key] = item
        await db.flush()
        if gcode and start:
            await enqueue_jobs_for_item(db, item, gcode)


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
        needed_by=needed_by_utc(payload.needed_by),
    )
    db.add(run)
    await db.flush()
    from app.services.codes import next_batch_code

    run.batch_code = await next_batch_code(db, payload.name)
    for pid in payload.printer_ids:
        db.add(ProductionRunPrinter(production_run_id=run.id, printer_id=pid))
    specs = _item_specs(payload.items)
    extra = None
    if payload.product_id:
        product_specs, extra = await _specs_from_product(
            db, payload.product_id, payload.product_qty, payload.include_optional
        )
        run.product_id = payload.product_id
        if extra and extra.get("product_sku") and (
            not payload.name.strip() or payload.name.startswith("Flex Rack 5")
        ):
            run.name = f"{extra['product_sku']} × {extra['quantity']}"
        if not specs:
            specs = product_specs
    if not specs:
        raise HTTPException(400, "Add at least one part or a catalog product")
    await _append_items(db, run, specs, payload.start_immediately)
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


@router.delete("/{run_id}")
async def delete_run(run_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    run = await db.get(ProductionRun, run_id)
    if not run:
        raise HTTPException(404, "Production run not found")
    label = run.batch_code or run.name
    active = (
        await db.execute(
            select(PrintJob).where(
                PrintJob.production_run_id == run.id,
                PrintJob.status.in_([JobStatus.printing, JobStatus.paused]),
            )
        )
    ).scalars().all()
    if active:
        raise HTTPException(
            400,
            f"Cannot delete {label}: {len(active)} job(s) are still on a printer. "
            "Wait for those plates to finish, then try again.",
        )
    assigned = (
        await db.execute(
            select(Printer).where(
                Printer.current_job_id.in_(select(PrintJob.id).where(PrintJob.production_run_id == run.id))
            )
        )
    ).scalars().all()
    if assigned:
        names = ", ".join(p.name for p in assigned[:4])
        raise HTTPException(
            400,
            f"Cannot delete {label}: {names} still has a job from this run. "
            "Wait for the plate to finish, then try again.",
        )
    await db.execute(
        update(PrintJob)
        .where(
            PrintJob.production_run_id == run.id,
            PrintJob.status.in_([JobStatus.queued, JobStatus.held]),
        )
        .values(status=JobStatus.cancelled)
    )
    item_ids = (
        await db.execute(select(ProductionRunItem.id).where(ProductionRunItem.production_run_id == run.id))
    ).scalars().all()
    await db.execute(
        update(PrintJob)
        .where(PrintJob.production_run_id == run.id)
        .values(production_run_id=None, production_run_item_id=None)
    )
    if item_ids:
        await db.execute(
            update(QcBatch).where(QcBatch.production_run_item_id.in_(item_ids)).values(production_run_item_id=None)
        )
        await db.execute(
            update(PrintJob).where(PrintJob.production_run_item_id.in_(item_ids)).values(production_run_item_id=None)
        )
    await db.execute(update(Order).where(Order.production_run_id == run.id).values(production_run_id=None))
    await db.execute(
        update(ProductionPlan).where(ProductionPlan.production_run_id == run.id).values(production_run_id=None)
    )
    await db.execute(
        update(FilamentTransaction)
        .where(FilamentTransaction.production_run_id == run.id)
        .values(production_run_id=None)
    )
    await db.execute(
        update(Notification).where(Notification.production_run_id == run.id).values(production_run_id=None)
    )
    try:
        await db.delete(run)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            400,
            f"Cannot delete {label}: it is still referenced by farm records. Cancel remaining work instead.",
        ) from exc
    return {"ok": True, "deleted": True, "name": run.name, "batch_code": run.batch_code}


@router.post("/{run_id}/add-product")
async def add_product_to_run(
    run_id: UUID,
    payload: ProductionProductIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    run = await db.get(ProductionRun, run_id)
    if not run:
        raise HTTPException(404, "Production run not found")
    if run.status in {ProductionRunStatus.completed, ProductionRunStatus.cancelled}:
        raise HTTPException(400, "Cannot add a product to a completed or cancelled run")
    specs, expanded = await _specs_from_product(
        db, payload.product_id, payload.quantity, payload.include_optional
    )
    if not specs:
        raise HTTPException(400, f"{expanded.get('product_sku') or 'Product'} has no BOM parts to produce")
    if not run.product_id:
        run.product_id = payload.product_id
    start = run.status in {
        ProductionRunStatus.queued,
        ProductionRunStatus.in_progress,
        ProductionRunStatus.draft,
    }
    await _append_items(db, run, specs, start)
    if run.status == ProductionRunStatus.draft and start:
        run.status = ProductionRunStatus.queued
    await db.commit()
    run = (
        await db.execute(select(ProductionRun).options(*_LOAD).where(ProductionRun.id == run.id))
    ).scalar_one()
    return {
        "run": run_out(run),
        "added": len(specs),
        "missing_gcode": expanded.get("missing_gcode") or [],
        "optional_skipped": expanded.get("optional_skipped") or [],
        "multi_file_parts": expanded.get("multi_file_parts") or [],
        "product_sku": expanded.get("product_sku"),
    }


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
