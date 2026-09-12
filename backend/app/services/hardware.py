from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    HardwareItem,
    HardwareMovement,
    NotificationType,
    PurchaseOrder,
    PurchaseOrderLine,
    utcnow,
)
from app.services.audit import record_audit
from app.services.barcodes import unique_public_code
from app.services.filament import next_po_reference
from app.services.notifications import NotifyContext, notify
from app.services.reorder import OPEN_PO, spend_controls


def hardware_public_code(sku: str) -> str:
    slug = "".join(ch for ch in (sku or "HW").upper() if ch.isalnum())[:16] or "HW"
    return f"HW-{slug}"


async def adjust_hardware(
    db: AsyncSession,
    item_id: UUID,
    quantity: float,
    reason: str,
    notes: str = "",
    actor: str = "system",
) -> HardwareItem:
    item = await db.get(HardwareItem, item_id)
    if not item:
        raise ValueError("Hardware item not found")
    item.quantity_on_hand = max(0.0, (item.quantity_on_hand or 0) + quantity)
    db.add(
        HardwareMovement(
            hardware_item_id=item.id,
            quantity=quantity,
            reason=reason,
            notes=notes,
        )
    )
    await record_audit(
        db,
        action="hardware_adjust",
        entity_type="hardware",
        entity_id=str(item.id),
        new={"qty": quantity, "on_hand": item.quantity_on_hand, "reason": reason},
        actor=actor,
    )
    await db.flush()
    return item


async def reserve_hardware(db: AsyncSession, item_id: UUID, quantity: float) -> float:
    item = await db.get(HardwareItem, item_id)
    if not item:
        return 0
    available = item.quantity_available
    take = min(available, quantity)
    item.quantity_reserved = (item.quantity_reserved or 0) + take
    await db.flush()
    return take


async def release_hardware(db: AsyncSession, item_id: UUID, quantity: float) -> None:
    item = await db.get(HardwareItem, item_id)
    if not item:
        return
    item.quantity_reserved = max(0.0, (item.quantity_reserved or 0) - quantity)
    await db.flush()


async def consume_hardware(db: AsyncSession, item_id: UUID, quantity: float, reason: str = "kit") -> None:
    item = await db.get(HardwareItem, item_id)
    if not item:
        return
    take = min(quantity, item.quantity_on_hand or 0)
    reserved_take = min(take, item.quantity_reserved or 0)
    item.quantity_reserved = max(0.0, (item.quantity_reserved or 0) - reserved_take)
    item.quantity_on_hand = max(0.0, (item.quantity_on_hand or 0) - take)
    db.add(
        HardwareMovement(
            hardware_item_id=item.id,
            quantity=-take,
            reason=reason,
        )
    )
    await db.flush()


async def existing_open_po_for_hardware(db: AsyncSession, item_id: UUID) -> PurchaseOrder | None:
    return (
        await db.execute(
            select(PurchaseOrder)
            .join(PurchaseOrderLine)
            .where(
                PurchaseOrderLine.hardware_item_id == item_id,
                PurchaseOrder.status.in_(OPEN_PO),
            )
            .order_by(PurchaseOrder.created_at.desc())
        )
    ).scalars().first()


async def evaluate_hardware_item(db: AsyncSession, item: HardwareItem, spend: dict) -> dict | None:
    if (item.reorder_mode or "off") in {"off", "OFF", ""}:
        return None
    available = item.quantity_available
    if available >= (item.min_stock or 0):
        return None
    existing = await existing_open_po_for_hardware(db, item.id)
    if existing:
        return {"skipped": True, "reason": f"Open PO {existing.reference}", "sku": item.sku}
    need = max(0.0, (item.target_stock or 0) - available)
    qty = max(1, int(round(need or 1)))
    unit = float(item.unit_cost or item.purchase_cost or 0)
    mode = item.reorder_mode
    if mode == "suggest_only":
        status = "suggested"
    elif mode == "create_purchase_order":
        status = "awaiting_approval"
    elif mode == "full_auto":
        status = "approved" if spend.get("full_auto_enabled") else "awaiting_approval"
    else:
        status = "awaiting_approval"
    if item.approval_required and status == "approved":
        status = "awaiting_approval"
    po = PurchaseOrder(
        reference=await next_po_reference(db),
        status=status,
        reason=f"{item.name} available {available:g} below minimum {item.min_stock:g} (target {item.target_stock:g})",
        auto_created=True,
        approval_required=item.approval_required or status == "awaiting_approval",
        total=round(qty * unit, 2),
        supplier_id=item.supplier_id,
    )
    db.add(po)
    await db.flush()
    db.add(
        PurchaseOrderLine(
            purchase_order_id=po.id,
            product_id=None,
            hardware_item_id=item.id,
            line_kind="hardware",
            quantity_ordered=qty,
            unit_price=unit,
            supplier_sku=item.sku,
        )
    )
    await notify(
        db,
        NotificationType.hardware_reorder,
        f"Reorder {item.name}",
        (
            f"{item.sku} — {item.name}\n\n"
            f"Available: {available:g}\nCommitted/reserved: {item.quantity_reserved:g}\n"
            f"Minimum: {item.min_stock:g}\nTarget: {item.target_stock:g}\n\n"
            f"Draft {po.reference}: {qty} units · ${po.total:.2f}"
        ),
        severity="warning",
        entity_type="purchase_order",
        entity_id=po.id,
        ctx=NotifyContext(extra={"purchase_order_id": str(po.id), "sku": item.sku}),
    )
    return {"sku": item.sku, "reference": po.reference, "qty": qty, "status": po.status}


async def run_hardware_reorder_pass(db: AsyncSession) -> list[dict]:
    spend = await spend_controls(db)
    items = (await db.execute(select(HardwareItem).where(HardwareItem.is_active.is_(True)))).scalars().all()
    results = []
    for item in items:
        row = await evaluate_hardware_item(db, item, spend)
        if row:
            results.append(row)
    return results


def item_out(item: HardwareItem) -> dict:
    return {
        "id": str(item.id),
        "sku": item.sku,
        "name": item.name,
        "category": item.category,
        "supplier": item.supplier,
        "supplier_url": item.supplier_url,
        "supplier_id": str(item.supplier_id) if item.supplier_id else None,
        "purchase_cost": item.purchase_cost,
        "unit_cost": item.unit_cost,
        "quantity_on_hand": item.quantity_on_hand,
        "quantity_reserved": item.quantity_reserved,
        "quantity_available": item.quantity_available,
        "min_stock": item.min_stock,
        "target_stock": item.target_stock,
        "storage_location": item.storage_location,
        "reorder_mode": item.reorder_mode,
        "approval_required": item.approval_required,
        "public_code": item.public_code,
        "barcode": item.barcode,
        "notes": item.notes,
        "is_active": item.is_active,
        "low": item.quantity_available < (item.min_stock or 0),
    }
