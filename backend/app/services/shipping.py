from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Order, OrderStatus, Shipment, utcnow
from app.services.audit import record_audit
from app.services.orders import fulfill_order


class ShippingProvider(Protocol):
    name: str

    async def create_label(self, order: Order, **kwargs: Any) -> dict: ...
    async def postage_price(self, order: Order, **kwargs: Any) -> dict: ...
    async def tracking(self, shipment: Shipment) -> dict: ...


class ManualShippingProvider:
    """Initial adapter: operator enters carrier, tracking, and cost."""

    name = "manual"

    async def create_label(self, order: Order, **kwargs: Any) -> dict:
        return {
            "ok": True,
            "provider": self.name,
            "carrier": kwargs.get("carrier") or "",
            "tracking_number": kwargs.get("tracking_number") or "",
            "cost": float(kwargs.get("cost") or 0),
            "message": "Manual shipment recorded. Connect a carrier adapter to print labels automatically.",
        }

    async def postage_price(self, order: Order, **kwargs: Any) -> dict:
        return {"ok": False, "message": "No carrier rate shop is configured. Enter postage cost manually."}

    async def tracking(self, shipment: Shipment) -> dict:
        return {
            "ok": True,
            "status": shipment.status,
            "tracking_number": shipment.tracking_number,
            "carrier": shipment.carrier,
        }


PROVIDERS: dict[str, type[ManualShippingProvider]] = {"manual": ManualShippingProvider}


def get_shipping_provider(name: str | None) -> ManualShippingProvider:
    return PROVIDERS.get((name or "manual").lower(), ManualShippingProvider)()


async def record_shipment(
    db: AsyncSession,
    order: Order,
    *,
    carrier: str,
    tracking_number: str,
    cost: float = 0,
    notes: str = "",
    actor: str = "operator",
    update_woocommerce: bool = True,
) -> Shipment:
    adapter = get_shipping_provider("manual")
    result = await adapter.create_label(
        order, carrier=carrier, tracking_number=tracking_number, cost=cost
    )
    shipment = Shipment(
        order_id=order.id,
        provider="manual",
        carrier=carrier,
        tracking_number=tracking_number,
        cost=cost,
        status="shipped",
        notes=notes or result.get("message") or "",
        shipped_at=utcnow(),
    )
    db.add(shipment)
    order.carrier = carrier
    order.tracking_number = tracking_number
    order.shipping_cost = cost or order.shipping_cost
    await fulfill_order(db, order, ship=True)
    await record_audit(
        db,
        action="order_shipped",
        entity_type="order",
        entity_id=str(order.id),
        new={"carrier": carrier, "tracking": tracking_number, "cost": cost},
        actor=actor,
    )
    if update_woocommerce and order.woocommerce_id:
        try:
            from app.services.woocommerce import push_tracking

            await push_tracking(order, carrier, tracking_number)
        except Exception:
            pass
    if getattr(order, "shopify_id", None):
        try:
            from app.services.shopify import push_tracking as push_shopify_tracking

            await push_shopify_tracking(order, carrier, tracking_number, db)
        except Exception:
            pass
    return shipment


DEFAULT_PACKAGE = {
    "weight_g": 500.0,
    "length_cm": 20.0,
    "width_cm": 15.0,
    "height_cm": 10.0,
}

SHIPPABLE_STATUSES = {
    OrderStatus.new,
    OrderStatus.awaiting_production,
    OrderStatus.in_production,
    OrderStatus.awaiting_qc,
    OrderStatus.ready_to_ship,
}

DEMO_STORE_ADDRESSES = {
    "RK-1042": {
        "name": "Northline Studio",
        "business_name": "Northline Studio",
        "lines": ["48 Gertrude Street"],
        "suburb": "Fitzroy",
        "state": "VIC",
        "postcode": "3065",
        "phone": "0390001042",
        "email": "ops@northline.example",
        "country": "AU",
        "source": "woocommerce",
    },
    "RK-1048": {
        "name": "Harbour Makerspace",
        "business_name": "Harbour Makerspace",
        "lines": ["12 Darling Drive"],
        "suburb": "Sydney",
        "state": "NSW",
        "postcode": "2000",
        "phone": "0290001048",
        "email": "shop@harbour.example",
        "country": "AU",
        "source": "woocommerce",
    },
}


def apply_store_shipping_address(order: Order, payload: dict[str, Any], source: str) -> dict[str, Any]:
    from app.services.auspost import address_from_store_payload, merge_address

    mapped = address_from_store_payload(payload, source)
    current = order.shipping_address if isinstance(getattr(order, "shipping_address", None), dict) else {}
    merged = merge_address(current, mapped)
    if not merged.get("email"):
        merged["email"] = order.customer_email or merged.get("email") or ""
    if not merged.get("name"):
        merged["name"] = order.customer_name or merged.get("name") or ""
    order.shipping_address = merged
    return merged


async def backfill_demo_shipping_addresses(db: AsyncSession) -> None:
    rows = (await db.execute(select(Order))).scalars().all()
    for order in rows:
        existing = getattr(order, "shipping_address", None)
        if isinstance(existing, dict) and (existing.get("suburb") or existing.get("postcode")):
            continue
        demo = DEMO_STORE_ADDRESSES.get(order.reference)
        if demo:
            order.shipping_address = dict(demo)


async def get_shipping_settings(db: AsyncSession) -> dict[str, Any]:
    from app.config import get_settings
    from app.models import AppSetting
    from app.security import decrypt_secret
    from app.services.auspost import DEFAULT_PRODUCT_ID, PRODUCTS

    settings = get_settings()
    row = await db.get(AppSetting, "shipping")
    stored = dict(row.value) if row and isinstance(row.value, dict) else {}
    company = await db.get(AppSetting, "company_name")
    company_name = company.value if company and isinstance(company.value, str) else "Print Farm"

    api_key = settings.auspost_api_key or (decrypt_secret(stored.get("auspost_api_key_enc")) or "")
    password = settings.auspost_password or (decrypt_secret(stored.get("auspost_password_enc")) or "")
    account = settings.auspost_account_number or str(stored.get("auspost_account_number") or "")
    sandbox = bool(settings.auspost_sandbox) if settings.auspost_api_key else bool(stored.get("sandbox", True))
    from_addr = stored.get("from_address") if isinstance(stored.get("from_address"), dict) else {}
    if not from_addr.get("name"):
        from_addr = {
            **{
                "name": company_name,
                "business_name": company_name,
                "lines": [],
                "suburb": "",
                "state": "",
                "postcode": "",
                "phone": "",
                "email": "",
                "country": "AU",
            },
            **from_addr,
        }
    last_package = stored.get("last_package") if isinstance(stored.get("last_package"), dict) else {}
    package = {**DEFAULT_PACKAGE, **{k: last_package[k] for k in DEFAULT_PACKAGE if k in last_package}}
    default_service = str(stored.get("default_service") or DEFAULT_PRODUCT_ID)
    env_override = bool(settings.auspost_api_key or settings.auspost_password or settings.auspost_account_number)
    return {
        "configured": bool(api_key and password and account),
        "sandbox": bool(sandbox),
        "base_url": (settings.auspost_base_url or "").rstrip("/"),
        "api_key": api_key,
        "password": password,
        "account_number": account,
        "api_key_set": bool(api_key),
        "password_set": bool(password),
        "account_number_set": bool(account),
        "env_override": env_override,
        "from_address": from_addr,
        "default_service": default_service,
        "last_package": package,
        "products": PRODUCTS,
        "stored": stored,
    }


def public_shipping_settings(raw: dict[str, Any]) -> dict[str, Any]:
    from app.services.auspost import TEST_BASE, LIVE_BASE

    sandbox = bool(raw.get("sandbox", True))
    base = raw.get("base_url") or (TEST_BASE if sandbox else LIVE_BASE)
    return {
        "configured": bool(raw.get("configured")),
        "sandbox": sandbox,
        "base_url": base,
        "api_key_set": bool(raw.get("api_key_set")),
        "password_set": bool(raw.get("password_set")),
        "account_number_set": bool(raw.get("account_number_set")),
        "account_number_hint": _mask(str(raw.get("account_number") or "")),
        "env_override": bool(raw.get("env_override")),
        "from_address": raw.get("from_address") or {},
        "default_service": raw.get("default_service"),
        "last_package": raw.get("last_package") or dict(DEFAULT_PACKAGE),
        "products": raw.get("products") or [],
    }


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "••••"
    return "••••" + value[-4:]


async def save_shipping_settings(db: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    from app.models import AppSetting
    from app.security import encrypt_secret
    from app.services.auspost import DEFAULT_PRODUCT_ID, PRODUCT_BY_ID, merge_address

    row = await db.get(AppSetting, "shipping")
    stored = dict(row.value) if row and isinstance(row.value, dict) else {}
    if "from_address" in payload and payload["from_address"] is not None:
        stored["from_address"] = merge_address(stored.get("from_address") if isinstance(stored.get("from_address"), dict) else {}, payload["from_address"])
    if payload.get("default_service"):
        service = str(payload["default_service"])
        stored["default_service"] = service if service in PRODUCT_BY_ID else stored.get("default_service") or DEFAULT_PRODUCT_ID
    if "sandbox" in payload and payload["sandbox"] is not None:
        stored["sandbox"] = bool(payload["sandbox"])
    if payload.get("auspost_api_key"):
        stored["auspost_api_key_enc"] = encrypt_secret(str(payload["auspost_api_key"]).strip())
    if payload.get("auspost_password"):
        stored["auspost_password_enc"] = encrypt_secret(str(payload["auspost_password"]).strip())
    if payload.get("auspost_account_number") is not None:
        stored["auspost_account_number"] = str(payload.get("auspost_account_number") or "").strip()
    if payload.get("last_package"):
        pkg = payload["last_package"]
        stored["last_package"] = {
            "weight_g": float(pkg.get("weight_g") or DEFAULT_PACKAGE["weight_g"]),
            "length_cm": float(pkg.get("length_cm") or DEFAULT_PACKAGE["length_cm"]),
            "width_cm": float(pkg.get("width_cm") or DEFAULT_PACKAGE["width_cm"]),
            "height_cm": float(pkg.get("height_cm") or DEFAULT_PACKAGE["height_cm"]),
        }
    if row:
        row.value = stored
    else:
        db.add(AppSetting(key="shipping", value=stored))
    await db.flush()
    return await get_shipping_settings(db)


def auspost_client_from_settings(raw: dict[str, Any]):
    from app.services.auspost import AusPostClient

    return AusPostClient(
        api_key=str(raw.get("api_key") or ""),
        password=str(raw.get("password") or ""),
        account_number=str(raw.get("account_number") or ""),
        sandbox=bool(raw.get("sandbox", True)),
        base_url=str(raw.get("base_url") or ""),
    )


async def estimated_weight_g(db: AsyncSession, order: Order) -> float:
    from app.models import GCodeFile, OrderPartNeed

    total = 0.0
    found = False
    needs = list(order.part_needs or [])
    if not needs:
        loaded = (
            await db.execute(select(OrderPartNeed).where(OrderPartNeed.order_id == order.id))
        ).scalars().all()
        needs = list(loaded)
    for need in needs:
        gcode = (
            await db.execute(
                select(GCodeFile)
                .where(GCodeFile.part_id == need.part_id, GCodeFile.is_archived.is_(False))
                .order_by(GCodeFile.version.desc())
            )
        ).scalars().first()
        grams = float(getattr(gcode, "estimated_filament_grams", 0) or 0) if gcode else 0.0
        if grams > 0:
            total += grams * max(int(need.required_qty or 1), 1)
            found = True
    if found:
        return max(50.0, round(total + 80.0, 0))
    return float(DEFAULT_PACKAGE["weight_g"])


def order_items_summary(order: Order) -> list[str]:
    lines: list[str] = []
    for line in order.lines or []:
        product = getattr(line, "product", None)
        name = (product.name if product else "") or (product.sku if product else "") or "Item"
        lines.append(f"{line.quantity} × {name}")
    if not lines:
        for need in order.part_needs or []:
            part = getattr(need, "part", None)
            name = (part.name if part else "") or (part.sku if part else "") or "Part"
            lines.append(f"{need.required_qty} × {name}")
    return lines


def shipment_ready_rank(order: Order) -> tuple[int, str]:
    status = order.status
    packed = (order.packing_status or "") == "packed"
    if status == OrderStatus.ready_to_ship or packed:
        return (0, order.reference)
    if status in {OrderStatus.awaiting_qc, OrderStatus.in_production}:
        return (1, order.reference)
    return (2, order.reference)


async def list_shippable_orders(db: AsyncSession) -> list[Order]:
    from sqlalchemy.orm import selectinload

    from app.models import OrderLine, OrderPartNeed

    await backfill_demo_shipping_addresses(db)
    rows = (
        await db.execute(
            select(Order)
            .options(
                selectinload(Order.lines).selectinload(OrderLine.product),
                selectinload(Order.part_needs).selectinload(OrderPartNeed.part),
                selectinload(Order.shipments),
            )
            .where(Order.status.in_(list(SHIPPABLE_STATUSES)))
            .order_by(Order.created_at.desc())
        )
    ).scalars().all()
    return sorted(rows, key=shipment_ready_rank)


def serialize_shipment(row: Shipment) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "order_id": str(row.order_id),
        "provider": row.provider,
        "carrier": row.carrier,
        "service": getattr(row, "service", "") or "",
        "tracking_number": row.tracking_number or "",
        "consignment_id": getattr(row, "consignment_id", "") or "",
        "auspost_shipment_id": getattr(row, "auspost_shipment_id", "") or "",
        "auspost_label_id": getattr(row, "auspost_label_id", "") or "",
        "status": row.status,
        "weight_g": getattr(row, "weight_g", 0) or 0,
        "length_cm": getattr(row, "length_cm", 0) or 0,
        "width_cm": getattr(row, "width_cm", 0) or 0,
        "height_cm": getattr(row, "height_cm", 0) or 0,
        "label_url": row.label_url or "",
        "has_pdf": bool(getattr(row, "label_path", "") or row.label_url),
        "notes": row.notes or "",
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def serialize_shippable_order(db: AsyncSession, order: Order, settings: dict[str, Any]) -> dict[str, Any]:
    from app.services.auspost import merge_address

    addr = merge_address({}, order.shipping_address if isinstance(order.shipping_address, dict) else {})
    if not addr.get("name"):
        addr["name"] = order.customer_name or ""
    if not addr.get("email"):
        addr["email"] = order.customer_email or ""
    weight = await estimated_weight_g(db, order)
    items = order_items_summary(order)
    shipments = [serialize_shipment(s) for s in sorted(order.shipments or [], key=lambda s: s.created_at or utcnow(), reverse=True)]
    packed = (order.packing_status or "") == "packed"
    ready = order.status == OrderStatus.ready_to_ship or packed
    return {
        "id": str(order.id),
        "reference": order.reference,
        "public_code": order.public_code,
        "customer_name": order.customer_name,
        "customer_email": order.customer_email,
        "source": order.source,
        "status": order.status.value,
        "packing_status": order.packing_status or "unpacked",
        "shipping_status": order.shipping_status,
        "carrier": order.carrier or "",
        "tracking_number": order.tracking_number or "",
        "ready_to_ship": ready,
        "has_address": bool(addr.get("suburb") and addr.get("postcode") and addr.get("state")),
        "shipping_address": addr,
        "from_address": settings.get("from_address") or {},
        "items": items,
        "contents": ", ".join(items) or "3D printed parts",
        "suggested_weight_g": weight,
        "package": settings.get("last_package") or dict(DEFAULT_PACKAGE),
        "default_service": settings.get("default_service"),
        "shipments": shipments,
    }


def farmos_label_html(
    *,
    order: Order,
    from_addr: dict[str, Any],
    to_addr: dict[str, Any],
    items: list[str],
    contents: str,
    service_name: str,
    weight_g: float,
    dims: str,
    page: str = "a6",
    barcode_url: str = "",
    qr_url: str = "",
    scan_url: str = "",
) -> str:
    import html as html_mod

    def esc(value: Any) -> str:
        return html_mod.escape("" if value is None else str(value))

    def block(addr: dict[str, Any]) -> str:
        lines = "<br/>".join(esc(x) for x in ([addr.get("name"), addr.get("business_name")] + list(addr.get("lines") or []) + [
            " ".join(p for p in [addr.get("suburb"), addr.get("state"), addr.get("postcode")] if p),
            addr.get("phone"),
            addr.get("email"),
        ]) if x)
        return lines or "—"

    code = order.public_code or f"ORDER-{order.reference}"
    page = "a4" if str(page).lower() == "a4" else "a6"
    if page == "a4":
        page_css = "@page { size: A4; margin: 12mm; }"
        label_css = "width: 100%; max-width: 180mm; min-height: 120mm; margin: 0 auto;"
    else:
        page_css = "@page { size: 105mm 148mm; margin: 4mm; }"
        label_css = "width: 105mm; min-height: 148mm; margin: 0 auto;"
    items_html = "".join(f"<li>{esc(item)}</li>" for item in items) or f"<li>{esc(contents or '3D printed parts')}</li>"
    barcode = f'<img class="barcode" src="{barcode_url}" alt="{esc(code)}" />' if barcode_url else ""
    qr = f'<img class="qr" src="{qr_url}" alt="QR {esc(code)}" />' if qr_url else ""
    scan = f'<div class="scan">{esc(scan_url)}</div>' if scan_url else ""
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Shipping label {esc(order.reference)}</title>
  <style>
    {page_css}
    body {{ font-family: ui-sans-serif, system-ui, sans-serif; background: #fff; color: #111; margin: 0; }}
    .label {{
      {label_css}
      box-sizing: border-box; padding: 6mm; border: 1px solid #111;
      display: flex; flex-direction: column; gap: 4mm;
    }}
    .brand {{ font-size: 10px; letter-spacing: 0.2em; text-transform: uppercase; color: #444; }}
    h1 {{ font-size: 18px; margin: 0; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 4mm; }}
    .box {{ border: 1px solid #ccc; padding: 3mm; font-size: 12px; min-height: 28mm; }}
    .box strong {{ display: block; font-size: 9px; letter-spacing: 0.14em; text-transform: uppercase; margin-bottom: 2mm; color: #555; }}
    .meta {{ font-size: 12px; }}
    ul {{ margin: 0; padding-left: 4mm; font-size: 12px; }}
    .code {{ font-family: ui-monospace, monospace; font-size: 13px; }}
    .scan {{ font-family: ui-monospace, monospace; font-size: 10px; word-break: break-all; color: #444; }}
    .marks {{ display: flex; align-items: flex-end; gap: 4mm; margin-top: auto; }}
    .qr {{ width: 28mm; height: 28mm; }}
    .barcode {{ height: 22mm; max-width: 70mm; }}
    .noprint {{ padding: 10px 14px; display: flex; justify-content: space-between; align-items: center; background: #f4f4f4; }}
    @media print {{
      .noprint {{ display: none; }}
      body {{ background: #fff; }}
      .label {{ border-color: #000; }}
    }}
  </style>
</head>
<body>
  <div class="noprint">
    <div>Print FarmOS shipping label · order {esc(order.reference)}</div>
    <button onclick="window.print()">Print</button>
  </div>
  <article class="label">
    <div class="brand">Print FarmOS · shipping label</div>
    <h1>Order {esc(order.reference)}</h1>
    <div class="grid">
      <div class="box"><strong>From</strong>{block(from_addr)}</div>
      <div class="box"><strong>Ship to</strong>{block(to_addr)}</div>
    </div>
    <div class="meta">
      Service: {esc(service_name or "Shop-floor label")} · Weight: {esc(int(weight_g))} g
      {f" · {esc(dims)}" if dims else ""}
    </div>
    <div>
      <strong>Contents</strong>
      <ul>{items_html}</ul>
    </div>
    <div class="code">{esc(code)}</div>
    {scan}
    <div class="marks">{qr}{barcode}</div>
  </article>
  <script>window.addEventListener("load", () => setTimeout(() => window.print(), 300));</script>
</body>
</html>
"""


async def create_farmos_preview(
    db: AsyncSession,
    order: Order,
    *,
    from_addr: dict[str, Any],
    to_addr: dict[str, Any],
    service: str,
    weight_g: float,
    length_cm: float,
    width_cm: float,
    height_cm: float,
    contents: str,
    reference: str,
    page: str,
    persist: bool = True,
) -> dict[str, Any]:
    import base64

    from app.services.auspost import PRODUCT_BY_ID, merge_address
    from app.services.labels import code128_svg, qr_png_bytes
    from app.services.farm_settings import public_scan_base
    from app.services.qr import qr_payload

    to_addr = merge_address(order.shipping_address if isinstance(order.shipping_address, dict) else {}, to_addr)
    order.shipping_address = to_addr
    code = order.public_code or f"ORDER-{order.reference}"
    try:
        barcode_url = "data:image/svg+xml;base64," + base64.b64encode(code128_svg(code)).decode()
    except Exception:
        barcode_url = ""
    base = await public_scan_base(db)
    payload = qr_payload("order", code, base)
    qr_url = "data:image/png;base64," + base64.b64encode(qr_png_bytes("order", code, base)).decode()
    service_name = (PRODUCT_BY_ID.get(service) or {}).get("name") or "Print FarmOS label"
    dims = f"{int(length_cm)}×{int(width_cm)}×{int(height_cm)} cm"
    html = farmos_label_html(
        order=order,
        from_addr=from_addr,
        to_addr=to_addr,
        items=order_items_summary(order),
        contents=contents,
        service_name=service_name,
        weight_g=weight_g,
        dims=dims,
        page=page,
        barcode_url=barcode_url,
        qr_url=qr_url,
        scan_url=payload if payload.startswith("http") else "",
    )
    shipment = None
    if persist:
        shipment = Shipment(
            order_id=order.id,
            provider="farmos_print",
            carrier="farmos_print",
            service=service,
            tracking_number="",
            status="label_printed",
            notes="Print FarmOS shop-floor label (no Australia Post account required).",
            weight_g=weight_g,
            length_cm=length_cm,
            width_cm=width_cm,
            height_cm=height_cm,
            payload_snapshot={
                "from": from_addr,
                "to": to_addr,
                "contents": contents,
                "reference": reference or order.reference,
                "page": page,
            },
        )
        db.add(shipment)
        await db.flush()
    return {"html": html, "shipment": serialize_shipment(shipment) if shipment else None}


async def create_auspost_label(
    db: AsyncSession,
    order: Order,
    *,
    settings: dict[str, Any],
    to_addr: dict[str, Any],
    service: str,
    weight_g: float,
    length_cm: float,
    width_cm: float,
    height_cm: float,
    contents: str,
    reference: str,
    actor: str,
) -> dict[str, Any]:
    from pathlib import Path

    from app.config import get_settings
    from app.services.auspost import (
        AusPostError,
        DEFAULT_PRODUCT_ID,
        PRODUCT_BY_ID,
        build_shipment_payload,
        extract_tracking,
        merge_address,
        validate_au_address,
    )

    client = auspost_client_from_settings(settings)
    if not client.configured:
        raise AusPostError(
            "Australia Post is not configured. Print FarmOS labels still work. Add API key, password, and account number in Settings to create official labels.",
            status_code=400,
        )
    from_addr = merge_address({}, settings.get("from_address") or {})
    to_addr = merge_address(order.shipping_address if isinstance(order.shipping_address, dict) else {}, to_addr)
    errors = validate_au_address(from_addr, who="Ship-from") + validate_au_address(to_addr, who="Ship-to")
    if errors:
        raise AusPostError(" ".join(errors), status_code=400, details=errors)
    product_id = service if service in PRODUCT_BY_ID else DEFAULT_PRODUCT_ID
    payload = build_shipment_payload(
        from_addr=from_addr,
        to_addr=to_addr,
        product_id=product_id,
        weight_g=weight_g,
        length_cm=length_cm,
        width_cm=width_cm,
        height_cm=height_cm,
        reference=reference or order.reference,
        contents=contents or "3D printed parts",
    )
    created = await client.create_shipments(payload)
    shipments = created.get("shipments") if isinstance(created, dict) else None
    if not shipments:
        raise AusPostError("Australia Post did not return a shipment.")
    ap_shipment = shipments[0]
    ap_id = str(ap_shipment.get("shipment_id") or "")
    consignment, tracking = extract_tracking(ap_shipment)
    labels = await client.create_labels([ap_id], product_id)
    label_rows = labels.get("labels") if isinstance(labels, dict) else []
    label_id = ""
    label_url = ""
    if label_rows and isinstance(label_rows[0], dict):
        label_id = str(label_rows[0].get("request_id") or label_rows[0].get("label_id") or "")
        label_url = str(label_rows[0].get("url") or "")
    pdf = b""
    if label_id:
        try:
            pdf = await client.fetch_label_pdf(label_id)
        except AusPostError:
            pdf = b""
    cfg = get_settings()
    label_path = ""
    if pdf:
        cfg.shipping_labels_dir.mkdir(parents=True, exist_ok=True)
        dest = cfg.shipping_labels_dir / f"auspost-{order.reference}-{ap_id or 'label'}.pdf"
        dest.write_bytes(pdf)
        label_path = str(dest)
    order.shipping_address = to_addr
    if tracking:
        order.tracking_number = tracking
        order.carrier = "Australia Post"
    shipment = Shipment(
        order_id=order.id,
        provider="auspost",
        carrier="Australia Post",
        service=product_id,
        tracking_number=tracking,
        consignment_id=consignment,
        auspost_shipment_id=ap_id,
        auspost_label_id=label_id,
        status="labelled",
        label_url=label_url,
        label_path=label_path,
        notes=f"Australia Post {PRODUCT_BY_ID.get(product_id, {}).get('name', product_id)}",
        weight_g=weight_g,
        length_cm=length_cm,
        width_cm=width_cm,
        height_cm=height_cm,
        payload_snapshot={"request": payload, "shipment": ap_shipment, "labels": labels},
    )
    db.add(shipment)
    stored = settings.get("stored") or {}
    stored["last_package"] = {
        "weight_g": weight_g,
        "length_cm": length_cm,
        "width_cm": width_cm,
        "height_cm": height_cm,
    }
    stored["from_address"] = from_addr
    from app.models import AppSetting

    row = await db.get(AppSetting, "shipping")
    if row:
        current = dict(row.value) if isinstance(row.value, dict) else {}
        current.update({"last_package": stored["last_package"]})
        row.value = current
    await record_audit(
        db,
        action="auspost_label_created",
        entity_type="order",
        entity_id=str(order.id),
        new={"shipment_id": ap_id, "tracking": tracking, "service": product_id},
        actor=actor,
    )
    await db.flush()
    return {
        "shipment": serialize_shipment(shipment),
        "tracking_number": tracking,
        "consignment_id": consignment,
        "message": "Australia Post label created. Download the official PDF to print.",
        "has_pdf": bool(label_path or label_url),
    }


async def read_auspost_pdf(db: AsyncSession, shipment_id) -> tuple[bytes, str]:
    from pathlib import Path

    from app.services.auspost import AusPostError

    row = await db.get(Shipment, shipment_id)
    if not row:
        raise AusPostError("Shipment not found.", status_code=404)
    path = getattr(row, "label_path", "") or ""
    if path and Path(path).is_file():
        return Path(path).read_bytes(), f"auspost-{row.tracking_number or row.id}.pdf"
    if row.label_url:
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(row.label_url)
        if resp.status_code < 400 and (resp.content[:4] == b"%PDF" or "pdf" in (resp.headers.get("content-type") or "").lower()):
            return resp.content, f"auspost-{row.tracking_number or row.id}.pdf"
    if row.auspost_label_id:
        settings = await get_shipping_settings(db)
        client = auspost_client_from_settings(settings)
        if client.configured:
            pdf = await client.fetch_label_pdf(row.auspost_label_id)
            return pdf, f"auspost-{row.tracking_number or row.id}.pdf"
    raise AusPostError("No Australia Post PDF is stored for this shipment.", status_code=404)
