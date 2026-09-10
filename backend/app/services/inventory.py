from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FinishedPartStock, StockMovement, utcnow


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
    await db.flush()
    return take


async def release_reservation(db: AsyncSession, part_id: UUID, quantity: int) -> None:
    stock = await get_or_create_stock(db, part_id)
    stock.quantity_reserved = max(0, stock.quantity_reserved - quantity)
    await db.flush()


async def consume_reserved(db: AsyncSession, part_id: UUID, quantity: int) -> None:
    stock = await get_or_create_stock(db, part_id)
    stock.quantity_reserved = max(0, stock.quantity_reserved - quantity)
    stock.quantity_on_hand = max(0, stock.quantity_on_hand - quantity)
    db.add(
        StockMovement(
            part_id=part_id,
            quantity=-quantity,
            reason="order_fulfill",
            notes="Consumed reserved stock on fulfilment",
        )
    )
    await db.flush()
