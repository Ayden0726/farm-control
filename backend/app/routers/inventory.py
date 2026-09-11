from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.models import (
    Part,
    PartBin,
    PrintJob,
    ProductionRunItem,
    QcBatch,
    QcStatus,
    User,
    utcnow,
)
from app.schemas import BinIn, BinOut, QcBatchOut, QcIn
from app.services.inventory import adjust_stock, get_or_create_stock
from app.util import new_qr_token

router = APIRouter(tags=["inventory"])


@router.get("/inventory")
async def inventory(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    parts = (await db.execute(select(Part).order_by(Part.sku))).scalars().all()
    out = []
    for part in parts:
        stock = await get_or_create_stock(db, part.id)
        awaiting = (
            await db.execute(
                select(QcBatch).where(QcBatch.part_id == part.id, QcBatch.status == QcStatus.awaiting_qc)
            )
        ).scalars().all()
        out.append(
            {
                "part_id": str(part.id),
                "sku": part.sku,
                "name": part.name,
                "quantity_on_hand": stock.quantity_on_hand,
                "quantity_reserved": stock.quantity_reserved,
                "quantity_available": stock.quantity_available,
                "awaiting_qc": sum(b.quantity - b.passed - b.failed for b in awaiting),
            }
        )
    return out


@router.get("/qc", response_model=list[QcBatchOut])
async def list_qc(
    awaiting_only: bool = True,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(QcBatch).options(selectinload(QcBatch.part), selectinload(QcBatch.job).selectinload(PrintJob.gcode_file))
    if awaiting_only:
        stmt = stmt.where(QcBatch.status == QcStatus.awaiting_qc)
    stmt = stmt.order_by(QcBatch.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [
        QcBatchOut(
            id=b.id,
            job_id=b.job_id,
            part_id=b.part_id,
            part_sku=b.part.sku if b.part else None,
            part_name=b.part.name if b.part else None,
            quantity=b.quantity,
            passed=b.passed,
            failed=b.failed,
            status=b.status.value,
            notes=b.notes,
            created_at=b.created_at,
            inspected_at=b.inspected_at,
            gcode_filename=b.job.gcode_file.filename if b.job and b.job.gcode_file else None,
        )
        for b in rows
    ]


@router.post("/qc/{batch_id}", response_model=QcBatchOut)
async def inspect_qc(
    batch_id: UUID, payload: QcIn, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    batch = (
        await db.execute(
            select(QcBatch)
            .options(selectinload(QcBatch.part), selectinload(QcBatch.job).selectinload(PrintJob.gcode_file))
            .where(QcBatch.id == batch_id)
        )
    ).scalar_one_or_none()
    if not batch:
        raise HTTPException(404, "QC batch not found")
    if payload.passed + payload.failed > batch.quantity:
        raise HTTPException(400, "Passed + failed cannot exceed printed quantity")
    if payload.passed + payload.failed < 1:
        raise HTTPException(400, "Enter how many parts passed or failed")
    already = batch.passed + batch.failed
    remaining = batch.quantity - already
    if payload.passed + payload.failed > remaining:
        raise HTTPException(400, "Counts exceed remaining uninspected parts")
    batch.passed += payload.passed
    batch.failed += payload.failed
    batch.notes = payload.notes or batch.notes
    if batch.passed + batch.failed >= batch.quantity:
        batch.status = QcStatus.complete
        batch.inspected_at = utcnow()
    if payload.passed:
        await adjust_stock(
            db,
            batch.part_id,
            payload.passed,
            reason="qc_pass",
            ref_type="qc_batch",
            ref_id=str(batch.id),
        )
    if payload.failed:
        await adjust_stock(
            db,
            batch.part_id,
            0,
            reason="qc_fail_scrap",
            ref_type="qc_batch",
            ref_id=str(batch.id),
            notes=f"scrapped {payload.failed}",
        )
    if batch.production_run_item_id:
        item = await db.get(ProductionRunItem, batch.production_run_item_id)
        if item:
            item.passed_qc += payload.passed
            item.failed_qc += payload.failed
    await db.commit()
    batch = (
        await db.execute(
            select(QcBatch)
            .options(selectinload(QcBatch.part), selectinload(QcBatch.job).selectinload(PrintJob.gcode_file))
            .where(QcBatch.id == batch_id)
        )
    ).scalar_one()
    return QcBatchOut(
        id=batch.id,
        job_id=batch.job_id,
        part_id=batch.part_id,
        part_sku=batch.part.sku if batch.part else None,
        part_name=batch.part.name if batch.part else None,
        quantity=batch.quantity,
        passed=batch.passed,
        failed=batch.failed,
        status=batch.status.value,
        notes=batch.notes,
        created_at=batch.created_at,
        inspected_at=batch.inspected_at,
        gcode_filename=batch.job.gcode_file.filename if batch.job and batch.job.gcode_file else None,
    )


@router.get("/bins", response_model=list[BinOut])
async def list_bins(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    rows = (await db.execute(select(PartBin).options(selectinload(PartBin.part)))).scalars().all()
    return [
        BinOut(
            id=b.id,
            name=b.name,
            location=b.location,
            part_id=b.part_id,
            part_sku=b.part.sku if b.part else None,
            qr_token=b.qr_token,
            public_code=b.public_code,
            kind=b.kind or "finished_part",
        )
        for b in rows
    ]


@router.post("/bins", response_model=BinOut)
async def create_bin(payload: BinIn, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    bin_row = PartBin(
        name=payload.name,
        location=payload.location,
        part_id=payload.part_id,
        qr_token=new_qr_token(),
        kind="finished_part",
    )
    db.add(bin_row)
    await db.flush()
    from app.services.barcodes import bin_public_code, unique_public_code

    bin_row.public_code = await unique_public_code(db, PartBin, "public_code", bin_public_code(bin_row.name))
    await db.commit()
    await db.refresh(bin_row)
    part = await db.get(Part, bin_row.part_id) if bin_row.part_id else None
    return BinOut(
        id=bin_row.id,
        name=bin_row.name,
        location=bin_row.location,
        part_id=bin_row.part_id,
        part_sku=part.sku if part else None,
        qr_token=bin_row.qr_token,
        public_code=bin_row.public_code,
        kind=bin_row.kind or "finished_part",
    )
