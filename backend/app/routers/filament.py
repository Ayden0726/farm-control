from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.models import DryingStatus, FilamentProduct, FilamentSpool, Printer, User
from app.schemas import SpoolIn, SpoolOut
from app.services.filament import cost_per_kg, next_spool_number, spool_code
from app.util import new_qr_token

router = APIRouter(prefix="/filament", tags=["filament"])


def _spool_out(spool: FilamentSpool) -> SpoolOut:
    cpk = spool.cost_per_kg or (
        (spool.cost / (spool.initial_weight_g / 1000)) if spool.initial_weight_g else 0
    )
    return SpoolOut(
        id=spool.id,
        name=spool.name,
        manufacturer=spool.manufacturer,
        material=spool.material,
        color=spool.color,
        initial_weight_g=spool.initial_weight_g,
        remaining_weight_g=spool.remaining_weight_g,
        cost=spool.cost,
        cost_per_kg=round(cpk, 2),
        purchase_date=spool.purchase_date,
        assigned_printer_id=spool.assigned_printer_id,
        assigned_printer_name=spool.assigned_printer.name if spool.assigned_printer else None,
        drying_status=spool.drying_status.value,
        low_stock_threshold_g=spool.low_stock_threshold_g,
        qr_token=spool.qr_token,
        is_archived=spool.is_archived,
        notes=spool.notes,
        is_low=spool.remaining_weight_g <= spool.low_stock_threshold_g,
        public_code=spool.public_code,
        product_id=spool.product_id,
        barcode_id=spool.product.barcode_id if spool.product else None,
        is_sealed=bool(getattr(spool, "is_sealed", True)),
        is_empty=bool(getattr(spool, "is_empty", False)),
        consumed_g=getattr(spool, "consumed_g", 0) or 0,
        location_name=spool.location.name if spool.location else None,
    )


@router.get("", response_model=list[SpoolOut])
async def list_spools(
    include_archived: bool = False,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(FilamentSpool).options(
        selectinload(FilamentSpool.assigned_printer),
        selectinload(FilamentSpool.location),
        selectinload(FilamentSpool.product),
    )
    if not include_archived:
        stmt = stmt.where(FilamentSpool.is_archived.is_(False))
    rows = (await db.execute(stmt.order_by(FilamentSpool.material, FilamentSpool.color))).scalars().all()
    return [_spool_out(s) for s in rows]


@router.post("", response_model=SpoolOut)
async def create_spool(payload: SpoolIn, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    remaining = payload.remaining_weight_g if payload.remaining_weight_g is not None else payload.initial_weight_g
    n = await next_spool_number(db)
    spool = FilamentSpool(
        name=payload.name,
        manufacturer=payload.manufacturer,
        material=payload.material,
        color=payload.color,
        initial_weight_g=payload.initial_weight_g,
        remaining_weight_g=remaining,
        cost=payload.cost,
        cost_per_kg=cost_per_kg(payload.cost, payload.initial_weight_g),
        purchase_date=payload.purchase_date,
        assigned_printer_id=payload.assigned_printer_id,
        drying_status=DryingStatus(payload.drying_status),
        low_stock_threshold_g=payload.low_stock_threshold_g,
        notes=payload.notes,
        qr_token=new_qr_token(),
        public_code=spool_code(n),
        is_sealed=False,
        date_received=payload.purchase_date,
        consumed_g=max(0.0, payload.initial_weight_g - remaining),
    )
    product = (
        await db.execute(
            select(FilamentProduct).where(
                FilamentProduct.manufacturer == payload.manufacturer,
                FilamentProduct.material == payload.material,
                FilamentProduct.color == payload.color,
            )
        )
    ).scalars().first()
    if product:
        spool.product_id = product.id
    db.add(spool)
    await db.flush()
    if payload.assigned_printer_id:
        printer = await db.get(Printer, payload.assigned_printer_id)
        if printer:
            printer.assigned_spool_id = spool.id
    await db.commit()
    spool = (
        await db.execute(
            select(FilamentSpool)
            .options(
                selectinload(FilamentSpool.assigned_printer),
                selectinload(FilamentSpool.location),
                selectinload(FilamentSpool.product),
            )
            .where(FilamentSpool.id == spool.id)
        )
    ).scalar_one()
    return _spool_out(spool)


@router.patch("/{spool_id}", response_model=SpoolOut)
async def update_spool(
    spool_id: UUID, payload: SpoolIn, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    spool = await db.get(FilamentSpool, spool_id)
    if not spool:
        raise HTTPException(404, "Spool not found")
    data = payload.model_dump()
    drying = data.pop("drying_status")
    remaining = data.pop("remaining_weight_g")
    for k, v in data.items():
        setattr(spool, k, v)
    spool.drying_status = DryingStatus(drying)
    if remaining is not None:
        spool.remaining_weight_g = remaining
    await db.commit()
    spool = (
        await db.execute(
            select(FilamentSpool)
            .options(
                selectinload(FilamentSpool.assigned_printer),
                selectinload(FilamentSpool.location),
                selectinload(FilamentSpool.product),
            )
            .where(FilamentSpool.id == spool.id)
        )
    ).scalar_one()
    return _spool_out(spool)


@router.post("/{spool_id}/archive", response_model=SpoolOut)
async def archive_spool(spool_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    spool = await db.get(FilamentSpool, spool_id)
    if not spool:
        raise HTTPException(404, "Spool not found")
    spool.is_archived = True
    if spool.assigned_printer_id:
        printer = await db.get(Printer, spool.assigned_printer_id)
        if printer and printer.assigned_spool_id == spool.id:
            printer.assigned_spool_id = None
        spool.assigned_printer_id = None
    await db.commit()
    spool = (
        await db.execute(
            select(FilamentSpool)
            .options(
                selectinload(FilamentSpool.assigned_printer),
                selectinload(FilamentSpool.location),
                selectinload(FilamentSpool.product),
            )
            .where(FilamentSpool.id == spool.id)
        )
    ).scalar_one()
    return _spool_out(spool)
