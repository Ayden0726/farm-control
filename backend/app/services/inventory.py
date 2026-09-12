from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BinMovement, FinishedPartStock, PartBin, StockMovement, utcnow


async def get_or_create_stock(db: AsyncSession, part_id: UUID) -> FinishedPartStock:
    stock = await db.get(FinishedPartStock, part_id)
    if stock is None:
        stock = FinishedPartStock(part_id=part_id, quantity_on_hand=0, quantity_reserved=0)
        db.add(stock)
        await db.flush()
    return stock


async def adjust_stock(
    db: AsyncSession,
    part_id: UUID,
    quantity: int,
    reason: str,
    ref_type: str | None = None,
    ref_id: str | None = None,
    notes: str = "",
) -> FinishedPartStock:
    stock = await get_or_create_stock(db, part_id)
    stock.quantity_on_hand = max(0, stock.quantity_on_hand + quantity)
    db.add(
        StockMovement(
            part_id=part_id,
            quantity=quantity,
            reason=reason,
            ref_type=ref_type,
            ref_id=ref_id,
            notes=notes,
            created_at=utcnow(),
        )
    )
    await db.flush()
    return stock


async def reserve_parts(db: AsyncSession, part_id: UUID, quantity: int) -> int:
    stock = await get_or_create_stock(db, part_id)
    available = max(0, stock.quantity_on_hand - stock.quantity_reserved)
    take = min(available, quantity)
    stock.quantity_reserved += take
    remaining = take
    bins = (
        await db.execute(select(PartBin).where(PartBin.part_id == part_id).order_by(PartBin.created_at))
    ).scalars().all()
    for bin_row in bins:
        if remaining <= 0:
            break
        bin_avail = max(0, (bin_row.quantity_on_hand or 0) - (bin_row.quantity_reserved or 0))
        n = min(bin_avail, remaining)
        bin_row.quantity_reserved = (bin_row.quantity_reserved or 0) + n
        remaining -= n
    await db.flush()
    return take


async def release_reservation(db: AsyncSession, part_id: UUID, quantity: int) -> None:
    stock = await get_or_create_stock(db, part_id)
    stock.quantity_reserved = max(0, stock.quantity_reserved - quantity)
    remaining = quantity
    bins = (
        await db.execute(
            select(PartBin)
            .where(PartBin.part_id == part_id, PartBin.quantity_reserved > 0)
            .order_by(PartBin.updated_at.desc())
        )
    ).scalars().all()
    for bin_row in bins:
        if remaining <= 0:
            break
        n = min(bin_row.quantity_reserved or 0, remaining)
        bin_row.quantity_reserved = max(0, (bin_row.quantity_reserved or 0) - n)
        remaining -= n
    await db.flush()


async def consume_reserved(db: AsyncSession, part_id: UUID, quantity: int) -> None:
    stock = await get_or_create_stock(db, part_id)
    stock.quantity_reserved = max(0, stock.quantity_reserved - quantity)
    stock.quantity_on_hand = max(0, stock.quantity_on_hand - quantity)
    remaining = quantity
    bins = (
        await db.execute(
            select(PartBin).where(PartBin.part_id == part_id).order_by(PartBin.created_at)
        )
    ).scalars().all()
    for bin_row in bins:
        if remaining <= 0:
            break
        take = min(bin_row.quantity_on_hand or 0, remaining)
        reserved_take = min(bin_row.quantity_reserved or 0, take)
        bin_row.quantity_reserved = max(0, (bin_row.quantity_reserved or 0) - reserved_take)
        bin_row.quantity_on_hand = max(0, (bin_row.quantity_on_hand or 0) - take)
        remaining -= take
    db.add(
        StockMovement(
            part_id=part_id,
            quantity=-quantity,
            reason="order_fulfill",
            notes="Consumed reserved stock on fulfilment",
        )
    )
    await db.flush()


async def apply_bin_change(
    db: AsyncSession,
    bin_row: PartBin,
    delta: int,
    reason: str,
    notes: str = "",
    actor: str = "operator",
    adjust_finished: bool = True,
) -> PartBin:
    bin_row.quantity_on_hand = max(0, (bin_row.quantity_on_hand or 0) + delta)
    if bin_row.quantity_reserved and bin_row.quantity_reserved > bin_row.quantity_on_hand:
        bin_row.quantity_reserved = bin_row.quantity_on_hand
    db.add(
        BinMovement(
            bin_id=bin_row.id,
            part_id=bin_row.part_id,
            quantity=delta,
            reason=reason,
            notes=notes,
            actor=actor,
        )
    )
    if adjust_finished and bin_row.part_id and delta:
        await adjust_stock(
            db,
            bin_row.part_id,
            delta,
            reason=f"bin_{reason}",
            ref_type="bin",
            ref_id=str(bin_row.id),
            notes=notes,
        )
    await db.flush()
    return bin_row
