from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models import Order, OrderLine, OrderStatus, Printer, Product
from app.services.orders import apply_inventory_to_order, create_production_for_order

logger = logging.getLogger("farmos.woocommerce")


def woocommerce_configured(url: str | None = None, key: str | None = None, secret: str | None = None) -> bool:
    settings = get_settings()
    return bool(url or settings.woocommerce_url) and bool(key or settings.woocommerce_key) and bool(
        secret or settings.woocommerce_secret
    )


async def fetch_woocommerce_order(order_id: int) -> dict[str, Any] | None:
    settings = get_settings()
    if not woocommerce_configured():
        return None
    url = settings.woocommerce_url.rstrip("/")
    auth = (settings.woocommerce_key, settings.woocommerce_secret)
    async with httpx.AsyncClient(timeout=20.0, auth=auth) as client:
        resp = await client.get(f"{url}/wp-json/wc/v3/orders/{order_id}")
        if resp.status_code >= 400:
            logger.warning("WooCommerce fetch failed: %s %s", resp.status_code, resp.text[:200])
            return None
        return resp.json()


async def import_woocommerce_payload(db: AsyncSession, payload: dict[str, Any]) -> Order | None:
    woo_id = int(payload.get("id") or 0)
    if not woo_id:
        return None
    existing = (
        await db.execute(select(Order).where(Order.woocommerce_id == woo_id))
    ).scalar_one_or_none()
    if existing:
        from app.services.shipping import apply_store_shipping_address

        apply_store_shipping_address(existing, payload, "woocommerce")
        return existing
    billing = payload.get("billing") or {}
    customer = f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip() or payload.get(
        "billing", {}
    ).get("company") or "WooCommerce customer"
    order = Order(
        reference=str(payload.get("number") or f"WC-{woo_id}"),
        customer_name=customer,
        customer_email=billing.get("email") or "",
        notes=payload.get("customer_note") or "",
        source="woocommerce",
        woocommerce_id=woo_id,
        status=OrderStatus.new,
        revenue=float(payload.get("total") or 0),
        shipping_cost=float(payload.get("shipping_total") or 0),
        payment_fee=0,
        due_at=None,
    )
    db.add(order)
    await db.flush()
    from app.services.codes import next_order_code
    from app.services.shipping import apply_store_shipping_address

    order.public_code = await next_order_code(db, order.reference)
    apply_store_shipping_address(order, payload, "woocommerce")
    for item in payload.get("line_items") or []:
        sku = (item.get("sku") or "").strip()
        product = None
        if sku:
            product = (
                await db.execute(select(Product).where(Product.sku == sku))
            ).scalar_one_or_none()
        if not product and item.get("product_id"):
            product = (
                await db.execute(
                    select(Product).where(Product.woocommerce_product_id == int(item["product_id"]))
                )
            ).scalar_one_or_none()
        if not product:
            logger.info("WooCommerce line skipped (unknown product sku=%s)", sku)
            continue
        db.add(
            OrderLine(
                order_id=order.id,
                product_id=product.id,
                quantity=int(item.get("quantity") or 1),
            )
        )
    await db.flush()
    await db.refresh(order, attribute_names=["lines", "part_needs"])
    if not order.lines:
        order.notes = (order.notes + "\nNo matching products found on this WooCommerce order.").strip()
        return order
    await apply_inventory_to_order(db, order)
    printers = (
        await db.execute(select(Printer.id).where(Printer.is_enabled.is_(True)))
    ).scalars().all()
    if any(n.to_produce > 0 for n in order.part_needs) and printers:
        await create_production_for_order(db, order, list(printers))
    return order


async def pull_recent_orders(db: AsyncSession) -> list[Order]:
    settings = get_settings()
    if not woocommerce_configured():
        return []
    url = settings.woocommerce_url.rstrip("/")
    auth = (settings.woocommerce_key, settings.woocommerce_secret)
    imported: list[Order] = []
    async with httpx.AsyncClient(timeout=20.0, auth=auth) as client:
        resp = await client.get(f"{url}/wp-json/wc/v3/orders", params={"per_page": 20, "status": "processing"})
        if resp.status_code >= 400:
            logger.warning("WooCommerce list failed: %s", resp.status_code)
            return []
        for payload in resp.json():
            order = await import_woocommerce_payload(db, payload)
            if order:
                imported.append(order)
    return imported


async def push_tracking(order, carrier: str, tracking: str) -> bool:
    """Best-effort WooCommerce note/status update when a shipment is recorded."""
    settings = get_settings()
    if not order.woocommerce_id or not woocommerce_configured():
        return False
    url = settings.woocommerce_url.rstrip("/")
    auth = (settings.woocommerce_key, settings.woocommerce_secret)
    body = {
        "status": "completed",
        "meta_data": [
            {"key": "_farmos_carrier", "value": carrier},
            {"key": "_farmos_tracking", "value": tracking},
        ],
        "customer_note": False,
    }
    try:
        async with httpx.AsyncClient(timeout=20.0, auth=auth) as client:
            resp = await client.put(f"{url}/wp-json/wc/v3/orders/{order.woocommerce_id}", json=body)
            if resp.status_code < 400:
                await client.post(
                    f"{url}/wp-json/wc/v3/orders/{order.woocommerce_id}/notes",
                    json={"note": f"Shipped via {carrier}. Tracking: {tracking}", "customer_note": True},
                )
                return True
    except Exception:
        logger.warning("WooCommerce tracking update failed", exc_info=True)
    return False
