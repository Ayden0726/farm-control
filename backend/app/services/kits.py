from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    AssemblyKit,
    AssemblyKitLine,
    BomHardwareItem,
    BomItem,
    Order,
    Product,
)
from app.services.codes import next_kit_code
from app.services.hardware import consume_hardware, release_hardware, reserve_hardware
from app.services.inventory import consume_reserved, get_or_create_stock, release_reservation, reserve_parts


STATUSES = [
    "parts_required",
    "parts_available",
    "kit_ready",
    "assembly",
    "qc",
    "ready_to_pack",
]


async def kit_requirements(db: AsyncSession, product: Product, quantity: int) -> list[dict]:
    product = (
        await db.execute(
            select(Product)
            .options(
                selectinload(Product.bom_items).selectinload(BomItem.part),
                selectinload(Product.bom_hardware).selectinload(BomHardwareItem.hardware_item),
            )
            .where(Product.id == product.id)
        )
    ).scalar_one()
    rows: list[dict] = []
    for item in product.bom_items or []:
        need = (item.quantity or 1) * quantity
        stock = await get_or_create_stock(db, item.part_id)
        rows.append(
            {
                "kind": "part",
                "part_id": str(item.part_id),
                "hardware_item_id": None,
                "sku": item.part.sku if item.part else "",
                "name": item.part.name if item.part else "",
                "required": need,
                "available": stock.quantity_available,
                "ok": stock.quantity_available >= need,
            }
        )
    hardware = (
        await db.execute(
            select(BomHardwareItem)
            .options(selectinload(BomHardwareItem.hardware_item))
            .where(BomHardwareItem.product_id == product.id)
        )
    ).scalars().all()
    for item in hardware:
        need = (item.quantity or 1) * quantity
        hw = item.hardware_item
        avail = hw.quantity_available if hw else 0
        rows.append(
            {
                "kind": "hardware",
                "part_id": None,
                "hardware_item_id": str(item.hardware_item_id),
                "sku": hw.sku if hw else "",
                "name": hw.name if hw else "",
                "required": need,
                "available": avail,
                "ok": avail >= need,
            }
        )
    return rows


def kit_status_from_lines(lines: list[dict]) -> str:
    if all(r["ok"] for r in lines) and lines:
        return "kit_ready"
    if any(r["available"] > 0 for r in lines):
        return "parts_available"
    return "parts_required"


async def create_kit(
    db: AsyncSession,
    product_id: UUID,
    quantity: int = 1,
    order_id: UUID | None = None,
) -> AssemblyKit:
    product = await db.get(Product, product_id)
    if not product:
        raise ValueError("Unknown product")
    reqs = await kit_requirements(db, product, quantity)
    kit = AssemblyKit(
        public_code=await next_kit_code(db),
        product_id=product.id,
        order_id=order_id,
        quantity=quantity,
        status=kit_status_from_lines(reqs),
    )
    db.add(kit)
    await db.flush()
    for row in reqs:
        db.add(
            AssemblyKitLine(
                kit_id=kit.id,
                kind=row["kind"],
                part_id=UUID(row["part_id"]) if row["part_id"] else None,
                hardware_item_id=UUID(row["hardware_item_id"]) if row["hardware_item_id"] else None,
                required_qty=row["required"],
                available_qty=row["available"],
            )
        )
    await db.flush()
    return kit


async def refresh_kit(db: AsyncSession, kit: AssemblyKit) -> AssemblyKit:
    product = await db.get(Product, kit.product_id)
    reqs = await kit_requirements(db, product, kit.quantity) if product else []
    by_key = {(r["kind"], r["part_id"], r["hardware_item_id"]): r for r in reqs}
    for line in kit.lines:
        key = (
            line.kind,
            str(line.part_id) if line.part_id else None,
            str(line.hardware_item_id) if line.hardware_item_id else None,
        )
        match = by_key.get(key)
        if match:
            line.available_qty = match["available"]
    if kit.status in {"parts_required", "parts_available", "kit_ready"}:
        kit.status = kit_status_from_lines(reqs)
    return kit


async def reserve_kit(db: AsyncSession, kit: AssemblyKit) -> AssemblyKit:
    await refresh_kit(db, kit)
    if kit.status not in {"kit_ready", "parts_available"}:
        raise ValueError("Not all components are available to reserve this kit")
    for line in kit.lines:
        need = line.required_qty - line.reserved_qty
        if need <= 0:
            continue
        if line.kind == "part" and line.part_id:
            taken = await reserve_parts(db, line.part_id, int(need))
            line.reserved_qty += taken
        elif line.kind == "hardware" and line.hardware_item_id:
            taken = await reserve_hardware(db, line.hardware_item_id, need)
            line.reserved_qty += taken
    if all(line.reserved_qty >= line.required_qty for line in kit.lines):
        kit.status = "kit_ready"
        from app.models import utcnow

        kit.reserved_at = utcnow()
    else:
        kit.status = "parts_available"
    return kit


async def advance_kit(db: AsyncSession, kit: AssemblyKit, status: str) -> AssemblyKit:
    if status not in STATUSES:
        raise ValueError("Unknown kit status")
    kit.status = status
    if status == "assembly":
        from app.models import utcnow

        kit.assembled_at = utcnow()
    if status in {"ready_to_pack", "qc"}:
        for line in kit.lines:
            if line.kind == "part" and line.part_id and line.reserved_qty:
                await consume_reserved(db, line.part_id, int(line.reserved_qty))
                line.reserved_qty = 0
            elif line.kind == "hardware" and line.hardware_item_id and line.reserved_qty:
                await consume_hardware(db, line.hardware_item_id, line.reserved_qty, reason="kit_assemble")
                line.reserved_qty = 0
    return kit


def kit_out(kit: AssemblyKit) -> dict:
    return {
        "id": str(kit.id),
        "public_code": kit.public_code,
        "product_id": str(kit.product_id),
        "product_sku": kit.product.sku if kit.product else "",
        "product_name": kit.product.name if kit.product else "",
        "order_id": str(kit.order_id) if kit.order_id else None,
        "quantity": kit.quantity,
        "status": kit.status,
        "notes": kit.notes,
        "reserved_at": kit.reserved_at.isoformat() if kit.reserved_at else None,
        "assembled_at": kit.assembled_at.isoformat() if kit.assembled_at else None,
        "lines": [
            {
                "id": str(ln.id),
                "kind": ln.kind,
                "sku": (ln.part.sku if ln.part else None) or (ln.hardware_item.sku if ln.hardware_item else ""),
                "name": (ln.part.name if ln.part else None) or (ln.hardware_item.name if ln.hardware_item else ""),
                "required_qty": ln.required_qty,
                "reserved_qty": ln.reserved_qty,
                "available_qty": ln.available_qty,
            }
            for ln in kit.lines
        ],
    }
