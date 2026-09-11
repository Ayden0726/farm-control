"""Modular filament supplier adapters.

Suppliers are not assumed to expose an API. The default adapter stores SKU,
product URL, and expected price, and can open the supplier page. Adapters that
support cart/order APIs can register additional capabilities. Full Auto ordering
is never implied by registration — FarmOS still requires the Full Auto spend
control to be enabled before any adapter places an order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from app.models import FilamentProduct, Supplier
from app.security import decrypt_secret


@dataclass
class SupplierQuote:
    sku: str
    url: str
    unit_price: float | None
    available: bool | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlaceOrderResult:
    ok: bool
    external_id: str | None = None
    tracking: str = ""
    message: str = ""
    status: str = "ordered"


class SupplierAdapter(Protocol):
    name: str
    capabilities: list[str]

    async def lookup(self, product: FilamentProduct) -> SupplierQuote: ...
    async def place_order(self, product: FilamentProduct, quantity: int, unit_price: float) -> PlaceOrderResult: ...


class UrlSupplierAdapter:
    """No API. Price and URL are stored on the filament product."""

    name = "url"
    capabilities = ["product_url", "stored_price"]

    def __init__(self, supplier: Supplier, secrets: dict[str, Any] | None = None):
        self.supplier = supplier
        self.secrets = secrets or {}

    async def lookup(self, product: FilamentProduct) -> SupplierQuote:
        return SupplierQuote(
            sku=product.supplier_sku,
            url=product.supplier_url,
            unit_price=product.normal_price or product.purchase_cost or None,
            available=None,
        )

    async def place_order(self, product: FilamentProduct, quantity: int, unit_price: float) -> PlaceOrderResult:
        return PlaceOrderResult(
            ok=False,
            message=(
                "This supplier has no order API. Open the supplier page and place the order, "
                "then mark the purchase order as Ordered in FarmOS."
            ),
            status="approved",
        )


class ManualSupplierAdapter(UrlSupplierAdapter):
    name = "manual"
    capabilities = ["stored_price"]


class HttpSupplierAdapter:
    """Placeholder for a future HTTP/REST supplier. Never spends money unless called."""

    name = "http"
    capabilities = [
        "product_url",
        "stored_price",
        "price_lookup",
        "availability",
        "cart",
        "order_create",
        "order_status",
        "tracking",
    ]

    def __init__(self, supplier: Supplier, secrets: dict[str, Any] | None = None):
        self.supplier = supplier
        self.secrets = secrets or {}

    async def lookup(self, product: FilamentProduct) -> SupplierQuote:
        return SupplierQuote(
            sku=product.supplier_sku,
            url=product.supplier_url,
            unit_price=product.normal_price or product.purchase_cost or None,
            available=None,
            raw={"adapter": "http", "configured": bool(self.secrets.get("api_key"))},
        )

    async def place_order(self, product: FilamentProduct, quantity: int, unit_price: float) -> PlaceOrderResult:
        if not self.secrets.get("api_key"):
            return PlaceOrderResult(
                ok=False,
                message="HTTP supplier adapter has no API credentials. Store them on the supplier record.",
                status="approved",
            )
        return PlaceOrderResult(
            ok=False,
            message="HTTP supplier order endpoint is not configured for this vendor yet.",
            status="approved",
        )


ADAPTERS: dict[str, type] = {
    "url": UrlSupplierAdapter,
    "manual": ManualSupplierAdapter,
    "http": HttpSupplierAdapter,
}


def supplier_secrets(supplier: Supplier) -> dict[str, Any]:
    raw = decrypt_secret(supplier.credentials_encrypted)
    if not raw:
        return {}
    import json

    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def build_supplier_adapter(supplier: Supplier) -> UrlSupplierAdapter:
    cls = ADAPTERS.get(supplier.adapter_type or "url", UrlSupplierAdapter)
    return cls(supplier, supplier_secrets(supplier))


def public_supplier(supplier: Supplier) -> dict[str, Any]:
    return {
        "id": str(supplier.id),
        "name": supplier.name,
        "website": supplier.website,
        "notes": supplier.notes,
        "adapter_type": supplier.adapter_type,
        "capabilities": supplier.capabilities or ADAPTERS.get(supplier.adapter_type, UrlSupplierAdapter).capabilities,
        "is_active": supplier.is_active,
        "has_credentials": bool(supplier.credentials_encrypted),
    }
