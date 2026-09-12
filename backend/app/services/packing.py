from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    BomHardwareItem,
    BomItem,
    Order,
    OrderLine,
    OrderStatus,
    PackingCheck,
    utcnow,
)
from app.services.audit import record_audit
from app.services.inventory import get_or_create_stock
from app.services.kits import kit_requirements


async def packing_list(db: AsyncSession, order: Order) -> list[dict]:
    await db.refresh(order, attribute_names=["lines", "part_needs"])
    items: list[dict] = []
    for line in order.lines:
        product = line.product
        if product is None:
            continue
        items.append(
            {
                "label": f"{line.quantity} × {product.name}",
                "kind": "product",
                "required_qty": line.quantity,
                "sku": product.sku,
            }
        )
        reqs = await kit_requirements(db, product, line.quantity)
        for req in reqs:
            items.append(
                {
                    "label": f"{int(req['required'])} × {req['name'] or req['sku']}",
                    "kind": req["kind"],
                    "required_qty": req["required"],
                    "sku": req["sku"],
                    "available": req["available"],
                    "missing": not req["ok"],
                }
            )
    existing = (
        await db.execute(select(PackingCheck).where(PackingCheck.order_id == order.id))
    ).scalars().all()
    by_label = {c.label: c for c in existing}
    out = []
    for item in items:
        check = by_label.get(item["label"])
        out.append(
            {
                **item,
                "confirmed": bool(check.confirmed) if check else False,
                "confirmed_qty": check.confirmed_qty if check else 0,
                "check_id": str(check.id) if check else None,
            }
        )
    return out


async def ensure_checks(db: AsyncSession, order: Order) -> list[PackingCheck]:
    listing = await packing_list(db, order)
    existing = (
        await db.execute(select(PackingCheck).where(PackingCheck.order_id == order.id))
    ).scalars().all()
    labels = {c.label for c in existing}
    for item in listing:
        if item["label"] in labels:
            continue
        db.add(
            PackingCheck(
                order_id=order.id,
                label=item["label"],
                kind=item["kind"],
                required_qty=item["required_qty"],
                missing=bool(item.get("missing")),
            )
        )
    await db.flush()
    return list(
        (await db.execute(select(PackingCheck).where(PackingCheck.order_id == order.id))).scalars().all()
    )


async def confirm_item(db: AsyncSession, order: Order, check_id: UUID, qty: float | None = None) -> PackingCheck:
    check = await db.get(PackingCheck, check_id)
    if not check or check.order_id != order.id:
        raise ValueError("Unknown packing line")
    check.confirmed = True
    check.confirmed_qty = qty if qty is not None else check.required_qty
    check.missing = False
    await db.flush()
    return check


async def mark_packed(
    db: AsyncSession,
    order: Order,
    *,
    override: bool = False,
    notes: str = "",
    actor: str = "operator",
) -> Order:
    checks = await ensure_checks(db, order)
    missing = [c for c in checks if not c.confirmed]
    if missing and not override:
        raise ValueError(
            "Cannot mark packed until every required item is confirmed: "
            + ", ".join(c.label for c in missing[:6])
        )
    if missing and override:
        order.packing_override = True
        await record_audit(
            db,
            action="packing_override",
            entity_type="order",
            entity_id=str(order.id),
            previous={"unconfirmed": [c.label for c in missing]},
            new={"notes": notes},
            actor=actor,
        )
    order.packed_at = utcnow()
    order.packing_status = "packed"
    order.packing_notes = notes or order.packing_notes
    if order.status not in {OrderStatus.shipped, OrderStatus.cancelled}:
        order.status = OrderStatus.ready_to_ship
    await record_audit(
        db,
        action="order_packed",
        entity_type="order",
        entity_id=str(order.id),
        new={"override": override, "notes": notes},
        actor=actor,
    )
    return order
