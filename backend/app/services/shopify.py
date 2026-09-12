from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import AppSetting, Order, OrderLine, OrderStatus, Printer, Product
from app.security import decrypt_secret
from app.services.orders import apply_inventory_to_order, create_production_for_order

logger = logging.getLogger("farmos.shopify")

DEFAULT_API_VERSION = "2024-10"


def normalize_shop(shop: str) -> str:
    value = (shop or "").strip()
    value = value.replace("https://", "").replace("http://", "").split("/")[0].strip()
    if value and "." not in value:
        value = f"{value}.myshopify.com"
    return value.lower()


def shopify_numeric_id(value: Any) -> str | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    if "gid://" in text:
        text = text.rsplit("/", 1)[-1]
    text = text.strip()
    return text if text.isdigit() else None


def verify_webhook_hmac(raw_body: bytes, header: str | None, secret: str) -> bool:
    if not secret or not header:
        return False
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    computed = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(computed, header.strip())


async def shopify_config(db: AsyncSession | None = None) -> dict[str, str]:
    settings = get_settings()
    shop = settings.shopify_shop
    token = settings.shopify_access_token
    secret = settings.shopify_webhook_secret
    version = settings.shopify_api_version or DEFAULT_API_VERSION
    if db is not None:
        stored = await db.get(AppSetting, "integrations")
        val = stored.value if stored and isinstance(stored.value, dict) else {}
        shop = shop or str(val.get("shopify_shop") or "")
        if not token and val.get("shopify_access_token_enc"):
            token = decrypt_secret(str(val["shopify_access_token_enc"])) or ""
        if not secret and val.get("shopify_webhook_secret_enc"):
            secret = decrypt_secret(str(val["shopify_webhook_secret_enc"])) or ""
        version = str(val.get("shopify_api_version") or version or DEFAULT_API_VERSION)
    return {
        "shop": normalize_shop(shop),
        "token": token or "",
        "secret": secret or "",
        "api_version": version or DEFAULT_API_VERSION,
    }


def shopify_configured(cfg: dict[str, str] | None = None) -> bool:
    if cfg is None:
        settings = get_settings()
        return bool(normalize_shop(settings.shopify_shop) and settings.shopify_access_token)
    return bool(cfg.get("shop") and cfg.get("token"))


def _admin_url(cfg: dict[str, str], path: str) -> str:
    return f"https://{cfg['shop']}/admin/api/{cfg['api_version']}/{path.lstrip('/')}"


def _headers(cfg: dict[str, str]) -> dict[str, str]:
    return {"X-Shopify-Access-Token": cfg["token"], "Content-Type": "application/json"}


async def _match_product(db: AsyncSession, item: dict[str, Any]) -> Product | None:
    sku = (item.get("sku") or "").strip()
    if sku:
        product = (await db.execute(select(Product).where(Product.sku == sku))).scalar_one_or_none()
        if product:
            return product
    product_id = shopify_numeric_id(item.get("product_id") or item.get("product_gid"))
    if product_id:
        return (
            await db.execute(select(Product).where(Product.shopify_product_id == product_id))
        ).scalar_one_or_none()
    return None


def _customer_name(payload: dict[str, Any]) -> str:
    customer = payload.get("customer") or {}
    name = f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip()
    if name:
        return name
    billing = payload.get("billing_address") or {}
    name = f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip()
    if name:
        return name
    company = customer.get("company") or billing.get("company")
    return str(company or payload.get("email") or "Shopify customer")


def _shipping_total(payload: dict[str, Any]) -> float:
    money = (payload.get("total_shipping_price_set") or {}).get("shop_money") or {}
    amount = money.get("amount")
    if amount not in (None, ""):
        try:
            return float(amount)
        except (TypeError, ValueError):
            pass
    total = 0.0
    for line in payload.get("shipping_lines") or []:
        try:
            total += float(line.get("price") or 0)
        except (TypeError, ValueError):
            continue
    return total


async def import_shopify_payload(db: AsyncSession, payload: dict[str, Any]) -> Order | None:
    if payload.get("order") and isinstance(payload["order"], dict) and "line_items" in payload["order"]:
        payload = payload["order"]
    shopify_id = shopify_numeric_id(payload.get("id") or payload.get("admin_graphql_api_id"))
    if not shopify_id:
        return None
    if payload.get("cancelled_at"):
        logger.info("Skipping cancelled Shopify order %s", shopify_id)
        return None
    existing = (
        await db.execute(select(Order).where(Order.shopify_id == shopify_id))
    ).scalar_one_or_none()
    if existing:
        return existing
    reference = str(payload.get("name") or payload.get("order_number") or f"SH-{shopify_id}")
    order = Order(
        reference=reference,
        customer_name=_customer_name(payload),
        customer_email=str(payload.get("email") or (payload.get("customer") or {}).get("email") or ""),
        notes=str(payload.get("note") or ""),
        source="shopify",
        shopify_id=shopify_id,
        status=OrderStatus.new,
        revenue=float(payload.get("total_price") or 0),
        shipping_cost=_shipping_total(payload),
        payment_fee=0,
        due_at=None,
    )
    db.add(order)
    await db.flush()
    from app.services.codes import next_order_code

    order.public_code = await next_order_code(db, order.reference)
    for item in payload.get("line_items") or []:
        product = await _match_product(db, item)
        if not product:
            logger.info(
                "Shopify line skipped (unknown product sku=%s id=%s)",
                item.get("sku"),
                item.get("product_id"),
            )
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
        order.notes = (order.notes + "\nNo matching products found on this Shopify order.").strip()
        return order
    await apply_inventory_to_order(db, order)
    printers = (
        await db.execute(select(Printer.id).where(Printer.is_enabled.is_(True)))
    ).scalars().all()
    if any(n.to_produce > 0 for n in order.part_needs) and printers:
        await create_production_for_order(db, order, list(printers))
    return order


async def pull_recent_orders(db: AsyncSession) -> list[Order]:
    cfg = await shopify_config(db)
    if not shopify_configured(cfg):
        return []
    imported: list[Order] = []
    async with httpx.AsyncClient(timeout=25.0) as client:
        resp = await client.get(
            _admin_url(cfg, "orders.json"),
            headers=_headers(cfg),
            params={"status": "open", "limit": 50, "fulfillment_status": "unfulfilled"},
        )
        if resp.status_code >= 400:
            logger.warning("Shopify list failed: %s %s", resp.status_code, resp.text[:200])
            return []
        for payload in resp.json().get("orders") or []:
            order = await import_shopify_payload(db, payload)
            if order:
                imported.append(order)
    return imported


async def push_tracking(order: Order, carrier: str, tracking: str, db: AsyncSession | None = None) -> bool:
    if not order.shopify_id:
        return False
    cfg = await shopify_config(db)
    if not shopify_configured(cfg):
        return False
    note = f"Shipped via {carrier}. Tracking: {tracking}"
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            fo = await client.get(
                _admin_url(cfg, f"orders/{order.shopify_id}/fulfillment_orders.json"),
                headers=_headers(cfg),
            )
            fulfillment_orders = fo.json().get("fulfillment_orders") if fo.status_code < 400 else []
            open_fos = [
                row
                for row in fulfillment_orders or []
                if str(row.get("status") or "") in {"open", "in_progress", "scheduled"}
            ]
            if open_fos:
                body = {
                    "fulfillment": {
                        "line_items_by_fulfillment_order": [
                            {"fulfillment_order_id": row["id"]} for row in open_fos
                        ],
                        "tracking_info": {"number": tracking, "company": carrier or "Other"},
                        "notify_customer": True,
                    }
                }
                resp = await client.post(_admin_url(cfg, "fulfillments.json"), headers=_headers(cfg), json=body)
                if resp.status_code < 400:
                    return True
                logger.warning("Shopify fulfillment failed: %s %s", resp.status_code, resp.text[:200])
            existing_note = ""
            loaded = await client.get(_admin_url(cfg, f"orders/{order.shopify_id}.json"), headers=_headers(cfg))
            if loaded.status_code < 400:
                existing_note = str((loaded.json().get("order") or {}).get("note") or "")
            combined = (existing_note + "\n" + note).strip()
            resp = await client.put(
                _admin_url(cfg, f"orders/{order.shopify_id}.json"),
                headers=_headers(cfg),
                json={"order": {"id": int(order.shopify_id), "note": combined, "tags": "farmos-shipped"}},
            )
            return resp.status_code < 400
    except Exception:
        logger.warning("Shopify tracking update failed", exc_info=True)
        return False
