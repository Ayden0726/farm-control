from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.models import (
    BomItem,
    Order,
    OrderLine,
    OrderPartNeed,
    Printer,
    User,
)
from app.schemas import OrderIn, OrderLineOut, OrderOut, OrderPartNeedOut
from app.services.orders import apply_inventory_to_order, create_production_for_order, fulfill_order
from app.services.woocommerce import import_woocommerce_payload, pull_recent_orders, woocommerce_configured
from app.services.shopify import (
    import_shopify_payload,
    pull_recent_orders as pull_shopify_orders,
    shopify_config,
    shopify_configured,
    verify_webhook_hmac,
)

router = APIRouter(tags=["orders"])


def _order_out(order: Order) -> OrderOut:
    return OrderOut(
        id=order.id,
        reference=order.reference,
        customer_name=order.customer_name,
        customer_email=order.customer_email,
        notes=order.notes,
        source=order.source,
        woocommerce_id=order.woocommerce_id,
        shopify_id=getattr(order, "shopify_id", None),
        status=order.status.value,
        shipping_status=order.shipping_status,
        shipped_at=order.shipped_at,
        production_run_id=order.production_run_id,
        created_at=order.created_at,
        lines=[
            OrderLineOut(
                product_id=line.product_id,
                product_sku=line.product.sku if line.product else "",
                product_name=line.product.name if line.product else "",
                quantity=line.quantity,
            )
            for line in order.lines
        ],
        part_needs=[
            OrderPartNeedOut(
                part_id=n.part_id,
                part_sku=n.part.sku if n.part else "",
                part_name=n.part.name if n.part else "",
                required_qty=n.required_qty,
                reserved_qty=n.reserved_qty,
                to_produce=n.to_produce,
            )
            for n in order.part_needs
        ],
        public_code=getattr(order, "public_code", None),
        packing_status=getattr(order, "packing_status", None) or "unpacked",
        packed_at=getattr(order, "packed_at", None),
        packing_override=bool(getattr(order, "packing_override", False)),
        packing_notes=getattr(order, "packing_notes", "") or "",
        revenue=getattr(order, "revenue", 0) or 0,
        shipping_cost=getattr(order, "shipping_cost", 0) or 0,
        payment_fee=getattr(order, "payment_fee", 0) or 0,
        carrier=getattr(order, "carrier", "") or "",
        tracking_number=getattr(order, "tracking_number", "") or "",
        due_at=getattr(order, "due_at", None),
        shipping_address=getattr(order, "shipping_address", None) if isinstance(getattr(order, "shipping_address", None), dict) else None,
    )


_LOAD = (
    selectinload(Order.lines).selectinload(OrderLine.product),
    selectinload(Order.part_needs).selectinload(OrderPartNeed.part),
)


@router.get("/orders", response_model=list[OrderOut])
async def list_orders(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    rows = (
        await db.execute(select(Order).options(*_LOAD).order_by(Order.created_at.desc()))
    ).scalars().all()
    return [_order_out(o) for o in rows]


@router.post("/orders", response_model=OrderOut)
async def create_order(
    payload: OrderIn, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    order = Order(
        reference=payload.reference,
        customer_name=payload.customer_name,
        customer_email=payload.customer_email,
        notes=payload.notes,
        source="manual",
    )
    db.add(order)
    await db.flush()
    from app.services.codes import next_order_code

    order.public_code = await next_order_code(db, order.reference)
    for line in payload.lines:
        db.add(OrderLine(order_id=order.id, product_id=line.product_id, quantity=line.quantity))
    await db.flush()
    order = (await db.execute(select(Order).options(*_LOAD).where(Order.id == order.id))).scalar_one()
    await apply_inventory_to_order(db, order)
    if payload.create_production and any(n.to_produce > 0 for n in order.part_needs):
        printer_ids = payload.printer_ids
        if not printer_ids:
            printer_ids = list(
                (await db.execute(select(Printer.id).where(Printer.is_enabled.is_(True)))).scalars().all()
            )
        await create_production_for_order(db, order, printer_ids)
    await db.commit()
    order = (
        await db.execute(select(Order).options(*_LOAD).where(Order.id == order.id))
    ).scalar_one()
    return _order_out(order)


@router.post("/orders/{order_id}/cancel", response_model=OrderOut)
async def cancel_order(
    order_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    from app.models import OrderStatus
    from app.services.audit import record_audit
    from app.services.inventory import release_reservation

    order = (await db.execute(select(Order).options(*_LOAD).where(Order.id == order_id))).scalar_one_or_none()
    if not order:
        raise HTTPException(404, "Order not found")
    if order.status == OrderStatus.shipped:
        raise HTTPException(400, "Shipped orders cannot be cancelled")
    for need in order.part_needs:
        if need.reserved_qty:
            await release_reservation(db, need.part_id, need.reserved_qty)
            need.reserved_qty = 0
    order.status = OrderStatus.cancelled
    await record_audit(
        db, action="order_cancelled", entity_type="order", entity_id=str(order.id), actor=user.email
    )
    await db.commit()
    order = (await db.execute(select(Order).options(*_LOAD).where(Order.id == order_id))).scalar_one()
    return _order_out(order)


@router.get("/orders/{order_id}", response_model=OrderOut)
async def get_order(order_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    order = (await db.execute(select(Order).options(*_LOAD).where(Order.id == order_id))).scalar_one_or_none()
    if not order:
        raise HTTPException(404, "Order not found")
    return _order_out(order)


@router.post("/orders/{order_id}/fulfill", response_model=OrderOut)
async def mark_fulfilled(
    order_id: UUID, ship: bool = True, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    order = (await db.execute(select(Order).options(*_LOAD).where(Order.id == order_id))).scalar_one_or_none()
    if not order:
        raise HTTPException(404, "Order not found")
    await fulfill_order(db, order, ship=ship)
    await db.commit()
    order = (await db.execute(select(Order).options(*_LOAD).where(Order.id == order_id))).scalar_one()
    return _order_out(order)


@router.post("/woocommerce/sync")
async def woo_sync(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    if not woocommerce_configured():
        raise HTTPException(
            400,
            "WooCommerce is not configured. Set WOOCOMMERCE_URL, WOOCOMMERCE_KEY and WOOCOMMERCE_SECRET.",
        )
    imported = await pull_recent_orders(db)
    await db.commit()
    return {"imported": len(imported), "ids": [str(o.id) for o in imported]}


@router.post("/woocommerce/webhook")
async def woo_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_wc_webhook_topic: str | None = Header(default=None, alias="X-WC-Webhook-Topic"),
):
    payload = await request.json()
    topic = x_wc_webhook_topic or ""
    if "order" not in topic and "id" not in payload:
        return {"ok": True, "ignored": True}
    order = await import_woocommerce_payload(db, payload)
    await db.commit()
    return {"ok": True, "order_id": str(order.id) if order else None}


@router.post("/shopify/sync")
async def shopify_sync(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    cfg = await shopify_config(db)
    if not shopify_configured(cfg):
        raise HTTPException(
            400,
            "Shopify is not configured. Set SHOPIFY_SHOP and SHOPIFY_ACCESS_TOKEN, or save them in Settings.",
        )
    imported = await pull_shopify_orders(db)
    await db.commit()
    return {"imported": len(imported), "ids": [str(o.id) for o in imported]}


@router.post("/shopify/webhook")
async def shopify_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_shopify_topic: str | None = Header(default=None, alias="X-Shopify-Topic"),
    x_shopify_hmac_sha256: str | None = Header(default=None, alias="X-Shopify-Hmac-Sha256"),
):
    raw = await request.body()
    cfg = await shopify_config(db)
    if cfg.get("secret"):
        if not verify_webhook_hmac(raw, x_shopify_hmac_sha256, cfg["secret"]):
            raise HTTPException(401, "Invalid Shopify webhook signature")
    topic = (x_shopify_topic or "").lower()
    if topic and "orders/" not in topic and "order" not in topic:
        return {"ok": True, "ignored": True}
    import json

    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "Shopify webhook body was not JSON")
    order = await import_shopify_payload(db, payload)
    await db.commit()
    return {"ok": True, "order_id": str(order.id) if order else None}
