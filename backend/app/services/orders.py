from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    BomItem,
    GCodeFile,
    NotificationType,
    Order,
    OrderPartNeed,
    OrderStatus,
    ProductionRun,
    ProductionRunPrinter,
    ProductionRunStatus,
    utcnow,
)
from app.services.inventory import consume_reserved, get_or_create_stock, release_reservation, reserve_parts
from app.services.notifications import notify
from app.services.queue import enqueue_jobs_for_item


async def explode_bom(db: AsyncSession, lines: list[tuple[UUID, int]]) -> dict[UUID, int]:
    needs: dict[UUID, int] = defaultdict(int)
    for product_id, qty in lines:
        result = await db.execute(select(BomItem).where(BomItem.product_id == product_id, BomItem.is_optional.is_(False)))
        for item in result.scalars():
            needs[item.part_id] += item.quantity * qty
    return dict(needs)


async def apply_inventory_to_order(db: AsyncSession, order: Order) -> None:
    lines = [(line.product_id, line.quantity) for line in order.lines]
    needs = await explode_bom(db, lines)
    existing = {n.part_id: n for n in order.part_needs}
    for part_id, required in needs.items():
        row = existing.get(part_id)
        if not row:
            row = OrderPartNeed(order_id=order.id, part_id=part_id, required_qty=required)
            db.add(row)
            order.part_needs.append(row)
            await db.flush()
        else:
            # Release old reservation if required changed
            if row.reserved_qty:
                await release_reservation(db, part_id, row.reserved_qty)
                row.reserved_qty = 0
            row.required_qty = required
        reserved = await reserve_parts(db, part_id, required)
        row.reserved_qty = reserved
        row.to_produce = max(0, required - reserved)
    await db.flush()
    missing = sum(n.to_produce for n in order.part_needs)
    reserved_all = all(n.to_produce == 0 for n in order.part_needs) and order.part_needs
    if reserved_all:
        order.status = OrderStatus.awaiting_qc if False else OrderStatus.ready_to_ship
        # Parts already in finished inventory — no print required
        order.status = OrderStatus.ready_to_ship
        await notify(
            db,
            NotificationType.order_ready,
            f"Order {order.reference} ready to ship",
            "All required parts were reserved from finished-part inventory.",
            severity="info",
            entity_type="order",
            entity_id=order.id,
        )
    elif missing:
        order.status = OrderStatus.awaiting_production
    else:
        order.status = OrderStatus.new


async def create_production_for_order(
    db: AsyncSession,
    order: Order,
    printer_ids: list[UUID],
    name: str | None = None,
) -> ProductionRun | None:
    missing = [n for n in order.part_needs if n.to_produce > 0]
    if not missing:
        return None
    run = ProductionRun(
        name=name or f"Order {order.reference}",
        status=ProductionRunStatus.queued,
        notes=f"Auto-created for order {order.reference}",
        started_at=utcnow(),
    )
    db.add(run)
    await db.flush()
    for pid in printer_ids:
        db.add(ProductionRunPrinter(production_run_id=run.id, printer_id=pid))
    for need in missing:
        gcode = (
            await db.execute(
                select(GCodeFile)
                .where(GCodeFile.part_id == need.part_id, GCodeFile.is_archived.is_(False))
                .order_by(GCodeFile.version.desc())
            )
        ).scalars().first()
        item = ProductionRunItem(
            production_run_id=run.id,
            part_id=need.part_id,
            gcode_file_id=gcode.id if gcode else None,
            required_qty=need.to_produce,
        )
        db.add(item)
        await db.flush()
        if gcode:
            await enqueue_jobs_for_item(db, item, gcode)
    order.production_run_id = run.id
    order.status = OrderStatus.in_production
    await db.flush()
    return run


async def refresh_order_status(db: AsyncSession, order: Order) -> None:
    if order.status in {OrderStatus.shipped, OrderStatus.cancelled}:
        return
    if not order.part_needs:
        return
    # If production run exists, inspect QC/print progress
    waiting_qc = False
    still_producing = False
    if order.production_run_id:
        run = await db.get(ProductionRun, order.production_run_id)
        if run:
            for item in run.items:
                if item.printed_qty < item.required_qty:
                    still_producing = True
                if item.passed_qc + item.failed_qc < item.printed_qty:
                    waiting_qc = True
    all_covered = all(
        n.reserved_qty + (0 if not order.production_run else _passed_for(order, n.part_id)) >= n.required_qty
        for n in order.part_needs
    )
    if still_producing:
        order.status = OrderStatus.in_production
    elif waiting_qc:
        order.status = OrderStatus.awaiting_qc
    elif order.status != OrderStatus.shipped:
        # Check stock coverage
        covered = True
        for n in order.part_needs:
            stock = await get_or_create_stock(db, n.part_id)
            if stock.quantity_on_hand < n.required_qty and n.reserved_qty < n.required_qty:
                # production may have passed QC into stock
                if stock.quantity_available + n.reserved_qty < n.required_qty:
                    covered = False
        if covered and not still_producing:
            if order.status != OrderStatus.ready_to_ship:
                order.status = OrderStatus.ready_to_ship
                await notify(
                    db,
                    NotificationType.order_ready,
                    f"Order {order.reference} ready for fulfilment",
                    "Required parts are in finished inventory.",
                    entity_type="order",
                    entity_id=order.id,
                )


def _passed_for(order: Order, part_id: UUID) -> int:
    if not order.production_run:
        return 0
    for item in order.production_run.items:
        if item.part_id == part_id:
            return item.passed_qc
    return 0


async def fulfill_order(db: AsyncSession, order: Order, ship: bool = True) -> Order:
    for need in order.part_needs:
        qty = need.reserved_qty or need.required_qty
        stock = await get_or_create_stock(db, need.part_id)
        consume = min(qty, stock.quantity_on_hand)
        if consume:
            await consume_reserved(db, need.part_id, min(consume, stock.quantity_reserved or consume))
            if stock.quantity_reserved < consume:
                # consume_reserved already reduced on_hand for reserved; if we consumed more than reserved:
                pass
        need.reserved_qty = 0
    if ship:
        order.status = OrderStatus.shipped
        order.shipping_status = "shipped"
        order.shipped_at = utcnow()
    else:
        order.shipping_status = "fulfilled"
        order.status = OrderStatus.ready_to_ship
    await db.flush()
    return order
