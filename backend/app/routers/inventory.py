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
    QcFailureReason,
    QcStatus,
    User,
    utcnow,
)
from app.schemas import BinIn, BinOut, QcBatchOut, QcIn
from app.services.inventory import adjust_stock, apply_bin_change, get_or_create_stock
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
            failure_reason=b.failure_reason or "",
            result=getattr(b, "result", "") or "",
        )
        for b in rows
    ]


@router.get("/qc/reasons")
async def qc_reasons(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    rows = (await db.execute(select(QcFailureReason).order_by(QcFailureReason.sort_order))).scalars().all()
    return [{"id": str(r.id), "code": r.code, "label": r.label, "is_active": r.is_active} for r in rows]


@router.post("/qc/reasons")
async def add_qc_reason(payload: dict, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    db.add(
        QcFailureReason(
            code=str(payload.get("code") or ""),
            label=str(payload.get("label") or payload.get("code") or "Other"),
            is_active=bool(payload.get("is_active", True)),
        )
    )
    await db.commit()
    return {"ok": True}


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
    if payload.failure_reason:
        batch.failure_reason = payload.failure_reason
    if batch.passed + batch.failed >= batch.quantity:
        batch.status = QcStatus.complete
        batch.inspected_at = utcnow()
        if batch.failed <= 0:
            batch.result = "passed"
        elif batch.passed <= 0:
            batch.result = "failed"
        else:
            batch.result = "partial"
    if payload.passed:
        await adjust_stock(
            db,
            batch.part_id,
            payload.passed,
            reason="qc_pass",
            ref_type="qc_batch",
            ref_id=str(batch.id),
        )
        bin_row = (
            await db.execute(select(PartBin).where(PartBin.part_id == batch.part_id).order_by(PartBin.created_at))
        ).scalars().first()
        if bin_row:
            await apply_bin_change(
                db, bin_row, payload.passed, reason="qc_pass", notes="QC passed", adjust_finished=False
            )
    if payload.failed:
        await adjust_stock(
            db,
            batch.part_id,
            0,
            reason="qc_fail_scrap",
            ref_type="qc_batch",
            ref_id=str(batch.id),
            notes=f"scrapped {payload.failed}" + (f" ({payload.failure_reason})" if payload.failure_reason else ""),
        )
    if batch.production_run_item_id:
        item = await db.get(ProductionRunItem, batch.production_run_item_id)
        if item:
            item.passed_qc += payload.passed
            item.failed_qc += payload.failed
            from app.services.farm_settings import get_mes
            from app.services.queue import enqueue_jobs_for_item
            from app.models import GCodeFile

            mes = await get_mes(db)
            if payload.failed and mes.get("auto_requeue_failed_qc"):
                gcode = item.gcode_file
                if not gcode and item.gcode_file_id:
                    gcode = await db.get(GCodeFile, item.gcode_file_id)
                if gcode:
                    item.required_qty += payload.failed
                    await enqueue_jobs_for_item(db, item, gcode)
    from app.services.audit import record_audit

    await record_audit(
        db,
        action="qc_inspect",
        entity_type="qc_batch",
        entity_id=str(batch.id),
        new={
            "passed": payload.passed,
            "failed": payload.failed,
            "reason": payload.failure_reason,
            "result": batch.result,
        },
        actor=_.email if _ else "operator",
    )
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
        failure_reason=batch.failure_reason or "",
        result=getattr(batch, "result", "") or "",
    )


@router.get("/bins", response_model=list[BinOut])
async def list_bins(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    rows = (await db.execute(select(PartBin).options(selectinload(PartBin.part)))).scalars().all()
    return [_bin_out(b) for b in rows]


def _bin_out(b: PartBin, part_sku: str | None = None) -> BinOut:
    sku = part_sku if part_sku is not None else (b.part.sku if b.part else None)
    return BinOut(
        id=b.id,
        name=b.name,
        location=b.location,
        part_id=b.part_id,
        part_sku=sku,
        qr_token=b.qr_token,
        public_code=b.public_code,
        kind=b.kind or "finished_part",
        quantity_on_hand=b.quantity_on_hand or 0,
        quantity_reserved=b.quantity_reserved or 0,
        quantity_available=max(0, (b.quantity_on_hand or 0) - (b.quantity_reserved or 0)),
    )


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
    return _bin_out(bin_row, part.sku if part else None)


@router.get("/bins/{bin_id}")
async def get_bin(bin_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    from app.models import BinMovement

    bin_row = (
        await db.execute(select(PartBin).options(selectinload(PartBin.part)).where(PartBin.id == bin_id))
    ).scalar_one_or_none()
    if not bin_row:
        raise HTTPException(404, "Bin not found")
    moves = (
        await db.execute(
            select(BinMovement).where(BinMovement.bin_id == bin_row.id).order_by(BinMovement.created_at.desc()).limit(80)
        )
    ).scalars().all()
    return {
        **_bin_out(bin_row).model_dump(mode="json"),
        "movements": [
            {
                "id": str(m.id),
                "quantity": m.quantity,
                "reason": m.reason,
                "notes": m.notes,
                "actor": m.actor,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in moves
        ],
    }


@router.post("/bins/{bin_id}/adjust")
async def adjust_bin(
    bin_id: UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.services.inventory import apply_bin_change

    bin_row = (
        await db.execute(select(PartBin).options(selectinload(PartBin.part)).where(PartBin.id == bin_id))
    ).scalar_one_or_none()
    if not bin_row:
        raise HTTPException(404, "Bin not found")
    reason = str(payload.get("reason") or "adjust")
    notes = str(payload.get("notes") or "")
    if "count" in payload and payload["count"] is not None:
        delta = int(payload["count"]) - (bin_row.quantity_on_hand or 0)
        reason = "count"
    else:
        delta = int(payload.get("quantity") or 0)
    await apply_bin_change(db, bin_row, delta, reason=reason, notes=notes, actor=user.email)
    await db.commit()
    bin_row = (
        await db.execute(select(PartBin).options(selectinload(PartBin.part)).where(PartBin.id == bin_id))
    ).scalar_one()
    return _bin_out(bin_row)


@router.post("/bins/{bin_id}/move")
async def move_bin_stock(
    bin_id: UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.services.inventory import apply_bin_change

    qty = int(payload.get("quantity") or 0)
    dest_id = payload.get("to_bin_id")
    if qty <= 0 or not dest_id:
        raise HTTPException(400, "quantity and to_bin_id required")
    src = (
        await db.execute(select(PartBin).options(selectinload(PartBin.part)).where(PartBin.id == bin_id))
    ).scalar_one_or_none()
    dest = (
        await db.execute(select(PartBin).options(selectinload(PartBin.part)).where(PartBin.id == UUID(str(dest_id))))
    ).scalar_one_or_none()
    if not src or not dest:
        raise HTTPException(404, "Bin not found")
    if src.quantity_available < qty:
        raise HTTPException(400, "Not enough available quantity in source bin")
    await apply_bin_change(db, src, -qty, reason="move_out", notes=f"to {dest.name}", actor=user.email, adjust_finished=False)
    if dest.part_id is None:
        dest.part_id = src.part_id
    await apply_bin_change(db, dest, qty, reason="move_in", notes=f"from {src.name}", actor=user.email, adjust_finished=False)
    await db.commit()
    return {"ok": True}
