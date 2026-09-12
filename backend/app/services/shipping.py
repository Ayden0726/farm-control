from __future__ import annotations

from typing import Any, Protocol

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
    return shipment
