from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    AppSetting,
    FilamentProduct,
    NotificationType,
    PurchaseOrder,
    PurchaseOrderLine,
    utcnow,
)
from app.services.filament import (
    DEFAULT_SPEND,
    OPEN_PO,
    audit,
    committed_by_product,
    forecast,
    next_po_reference,
    recommend_rolls,
    stock_snapshot,
    usage_stats,
)
from app.services.notifications import NotifyContext, notify, recently_notified
from app.adapters.suppliers import build_supplier_adapter


async def spend_controls(db: AsyncSession) -> dict:
    row = await db.get(AppSetting, "filament_spend")
    data = dict(DEFAULT_SPEND)
    if row and isinstance(row.value, dict):
        data.update({k: row.value[k] for k in row.value})
    return data


async def save_spend_controls(db: AsyncSession, payload: dict) -> dict:
    merged = await spend_controls(db)
    for key in DEFAULT_SPEND:
        if key in payload and payload[key] is not None:
            merged[key] = payload[key]
    row = await db.get(AppSetting, "filament_spend")
    if row:
        row.value = merged
    else:
        db.add(AppSetting(key="filament_spend", value=merged))
    return merged


def _unit_price(product: FilamentProduct) -> float:
    return float(product.normal_price or product.purchase_cost or 0)


async def existing_open_po_for_product(db: AsyncSession, product_id: UUID) -> PurchaseOrder | None:
    row = (
        await db.execute(
            select(PurchaseOrder)
            .join(PurchaseOrderLine)
            .options(selectinload(PurchaseOrder.lines), selectinload(PurchaseOrder.supplier))
            .where(
                PurchaseOrderLine.product_id == product_id,
                PurchaseOrder.status.in_(OPEN_PO),
            )
            .order_by(PurchaseOrder.created_at.desc())
        )
    ).scalars().first()
    return row


def spending_flags(product: FilamentProduct, rolls: int, unit_price: float, spend: dict, using_backup: bool) -> list[str]:
    flags: list[str] = []
    total = rolls * unit_price
    spool_g = product.preferred_spool_weight_g or product.filament_weight_g or 1000
    ppk = (unit_price / (spool_g / 1000)) if spool_g else 0
    if spend.get("max_po_value") and total > float(spend["max_po_value"]):
        flags.append("over_max_po_value")
    if product.max_po_amount and total > product.max_po_amount:
        flags.append("over_product_max_po")
    if spend.get("max_price_per_spool") and unit_price > float(spend["max_price_per_spool"]):
        flags.append("over_max_price_per_spool")
    if spend.get("max_price_per_kg") and ppk > float(spend["max_price_per_kg"]):
        flags.append("over_max_price_per_kg")
    if product.max_price and unit_price > product.max_price:
        flags.append("over_product_max_price")
    if product.max_price_per_kg and ppk > product.max_price_per_kg:
        flags.append("over_product_max_price_per_kg")
    if product.normal_price and unit_price > 0:
        increase = ((unit_price - product.normal_price) / product.normal_price) * 100
        if increase > float(spend.get("price_increase_tolerance_pct") or 0):
            flags.append("price_increase")
    if using_backup:
        flags.append("backup_supplier")
    typical = max(1, math_ceil_rolls(product))
    if rolls > typical * 3:
        flags.append("unusual_quantity")
    return flags


def math_ceil_rolls(product: FilamentProduct) -> int:
    spool = product.preferred_spool_weight_g or product.filament_weight_g or 1000
    if spool <= 0:
        return 1
    import math

    return max(1, math.ceil((product.target_stock_g - product.min_stock_g) / spool))


async def _create_po(
    db: AsyncSession,
    product: FilamentProduct,
    rolls: int,
    reason: str,
    status: str,
    spend: dict,
    using_backup: bool = False,
) -> PurchaseOrder:
    supplier_id = product.backup_supplier_id if using_backup else product.preferred_supplier_id
    unit = _unit_price(product)
    spool_g = product.preferred_spool_weight_g or product.filament_weight_g
    ppk = (unit / (spool_g / 1000)) if spool_g else 0
    po = PurchaseOrder(
        reference=await next_po_reference(db),
        status=status,
        supplier_id=supplier_id,
        reason=reason,
        auto_created=True,
        approval_required=product.approval_required or status == "awaiting_approval",
        total=round(rolls * unit, 2),
        expected_delivery=utcnow() + timedelta(days=product.lead_time_days or 0),
    )
    db.add(po)
    await db.flush()
    db.add(
        PurchaseOrderLine(
            purchase_order_id=po.id,
            product_id=product.id,
            quantity_ordered=rolls,
            quantity_received=0,
            spool_weight_g=spool_g,
            unit_price=unit,
            price_per_kg=round(ppk, 2),
            supplier_sku=product.supplier_sku,
        )
    )
    await audit(
        db,
        "reorder_triggered",
        "purchase_order",
        po.reference,
        {"product": product.barcode_id, "rolls": rolls, "status": status, "total": po.total},
    )
    return po


async def notify_reorder(db: AsyncSession, product: FilamentProduct, po: PurchaseOrder, snap: dict, rec: dict) -> None:
    if await recently_notified(db, NotificationType.filament_reorder.value, None, hours=12):
        # still notify per-product via extra entity, skip only exact dupes
        pass
    cost = po.total
    body = (
        f"{product.manufacturer} {product.material} — {product.color}\n\n"
        f"Available: {snap['available_kg']} kg\n"
        f"Minimum: {snap['min_stock_g'] / 1000:.1f} kg\n"
        f"Target: {snap['target_stock_g'] / 1000:.1f} kg\n\n"
        f"Recommended: {rec['rolls']} × {rec['spool_g'] / 1000:.0f} kg rolls\n"
        f"Estimated cost: ${cost:.2f}\n\n"
        f"{rec['reason']}"
    )
    await notify(
        db,
        NotificationType.filament_reorder,
        f"{product.color} {product.material} reorder required",
        body,
        severity="warning",
        entity_type="purchase_order",
        entity_id=po.id,
        ctx=NotifyContext(extra={"purchase_order_id": str(po.id), "reference": po.reference}),
    )


async def evaluate_product(db: AsyncSession, product: FilamentProduct, committed_map: dict, spend: dict) -> dict | None:
    if product.reorder_mode in {"off", "OFF"}:
        return None
    snap = await stock_snapshot(db, product, committed_map)
    rec = recommend_rolls(product, snap["available_g"])
    stats = await usage_stats(db, product.id)
    fc = await forecast(db, product, snap, stats)
    if not rec["needed"] and not fc.get("will_stockout_before_delivery"):
        return None
    if not rec["needed"]:
        rec = recommend_rolls(product, snap["available_g"])
        if not rec["needed"]:
            rec = {
                **rec,
                "needed": True,
                "rolls": max(product.min_reorder_qty or 1, 1),
                "reason": "Lead time would exhaust stock before a replacement arrives.",
            }
    existing = await existing_open_po_for_product(db, product.id)
    if existing:
        return {
            "product_id": str(product.id),
            "skipped": True,
            "reason": f"Open purchase order {existing.reference} already covers this product.",
            "purchase_order_id": str(existing.id),
        }
    using_backup = False
    flags = spending_flags(product, rec["rolls"], _unit_price(product), spend, using_backup)
    mode = product.reorder_mode
    if mode == "suggest_only":
        status = "suggested"
    elif mode == "create_purchase_order":
        status = "awaiting_approval"
    elif mode == "approve_and_order":
        status = "approved"
    elif mode == "full_auto":
        if not spend.get("full_auto_enabled"):
            status = "awaiting_approval"
        else:
            status = "approved"
    else:
        status = "awaiting_approval"
    if flags and mode == "full_auto":
        status = "awaiting_approval"
    po = await _create_po(db, product, rec["rolls"], rec["reason"], status, spend, using_backup)
    await notify_reorder(db, product, po, snap, rec)
    result = {
        "product_id": str(product.id),
        "barcode_id": product.barcode_id,
        "rolls": rec["rolls"],
        "status": po.status,
        "purchase_order_id": str(po.id),
        "reference": po.reference,
        "flags": flags,
    }
    if po.status == "approved" and mode in {"approve_and_order", "full_auto"} and spend.get("full_auto_enabled") and mode == "full_auto":
        if product.preferred_supplier_id:
            from app.models import Supplier

            supplier = await db.get(Supplier, product.preferred_supplier_id)
            if supplier:
                adapter = build_supplier_adapter(supplier)
                placed = await adapter.place_order(product, rec["rolls"], _unit_price(product))
                if placed.ok:
                    po.status = "ordered"
                    po.ordered_at = utcnow()
                    po.tracking = placed.tracking
                    po.notes = (po.notes + "\n" + placed.message).strip()
                    result["ordered"] = True
                else:
                    po.notes = placed.message
                    result["order_message"] = placed.message
    return result


async def run_reorder_pass(db: AsyncSession) -> list[dict]:
    spend = await spend_controls(db)
    committed_map = await committed_by_product(db)
    products = (await db.execute(select(FilamentProduct).where(FilamentProduct.is_active.is_(True)))).scalars().all()
    results = []
    for product in products:
        row = await evaluate_product(db, product, committed_map, spend)
        if row:
            results.append(row)
    row = await db.get(AppSetting, "filament_reorder_last")
    stamp = utcnow().isoformat()
    if row:
        row.value = {"at": stamp, "created": len(results)}
    else:
        db.add(AppSetting(key="filament_reorder_last", value={"at": stamp, "created": len(results)}))
    return results
