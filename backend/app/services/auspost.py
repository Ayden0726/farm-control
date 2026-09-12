"""Australia Post Shipping & Tracking API v1 helpers.

Official docs: Shipping and Tracking REST API
Test: https://digitalapi.auspost.com.au/test/shipping/v1/
Live: https://digitalapi.auspost.com.au/shipping/v1/
Auth: HTTP Basic (API key : password) plus Account-Number header.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

logger = logging.getLogger("farmos.auspost")

TEST_BASE = "https://digitalapi.auspost.com.au/test/shipping/v1"
LIVE_BASE = "https://digitalapi.auspost.com.au/shipping/v1"

AU_STATES = {
    "NSW": "NSW",
    "NEW SOUTH WALES": "NSW",
    "VIC": "VIC",
    "VICTORIA": "VIC",
    "QLD": "QLD",
    "QUEENSLAND": "QLD",
    "SA": "SA",
    "SOUTH AUSTRALIA": "SA",
    "WA": "WA",
    "WESTERN AUSTRALIA": "WA",
    "TAS": "TAS",
    "TASMANIA": "TAS",
    "NT": "NT",
    "NORTHERN TERRITORY": "NT",
    "ACT": "ACT",
    "AUSTRALIAN CAPITAL TERRITORY": "ACT",
}

PRODUCTS: list[dict[str, str]] = [
    {"id": "AUS_PARCEL_REGULAR", "name": "Parcel Post", "group": "Parcel Post"},
    {"id": "AUS_PARCEL_EXPRESS", "name": "Express Post", "group": "Express Post"},
    {"id": "AUS_PARCEL_REGULAR_SATCHEL_SMALL", "name": "Parcel Post satchel (small)", "group": "Parcel Post"},
    {"id": "AUS_PARCEL_REGULAR_SATCHEL_MEDIUM", "name": "Parcel Post satchel (medium)", "group": "Parcel Post"},
    {"id": "AUS_PARCEL_EXPRESS_SATCHEL_SMALL", "name": "Express Post satchel (small)", "group": "Express Post"},
    {"id": "AUS_PARCEL_EXPRESS_SATCHEL_MEDIUM", "name": "Express Post satchel (medium)", "group": "Express Post"},
]

PRODUCT_BY_ID = {row["id"]: row for row in PRODUCTS}
DEFAULT_PRODUCT_ID = "AUS_PARCEL_REGULAR"
LABEL_LAYOUT = "A6-1pp"


class AusPostError(Exception):
    def __init__(self, message: str, status_code: int = 400, details: list[str] | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or []


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_au_state(value: str) -> str:
    raw = _clean(value).upper().replace(".", "")
    if not raw:
        return ""
    return AU_STATES.get(raw, raw if raw in AU_STATES.values() else "")


def normalize_postcode(value: str) -> str:
    digits = re.sub(r"\D", "", _clean(value))
    return digits[:4] if len(digits) >= 4 else digits


def _full_name(*parts: Any, fallback: str = "") -> str:
    joined = " ".join(_clean(p) for p in parts if _clean(p)).strip()
    return joined or fallback


def _lines(*parts: Any) -> list[str]:
    return [_clean(p) for p in parts if _clean(p)]


def empty_address() -> dict[str, Any]:
    return {
        "name": "",
        "business_name": "",
        "lines": [],
        "suburb": "",
        "state": "",
        "postcode": "",
        "phone": "",
        "email": "",
        "country": "AU",
        "source": "",
    }


def address_from_woocommerce(payload: dict[str, Any]) -> dict[str, Any]:
    """Map a WooCommerce order (or shipping+billing dicts) to a FarmOS AU address."""
    shipping = payload.get("shipping") or {}
    billing = payload.get("billing") or {}
    if not isinstance(shipping, dict):
        shipping = {}
    if not isinstance(billing, dict):
        billing = {}
    name = _full_name(
        shipping.get("first_name") or billing.get("first_name"),
        shipping.get("last_name") or billing.get("last_name"),
        fallback=_clean(shipping.get("company") or billing.get("company") or payload.get("customer_name")),
    )
    email = _clean(billing.get("email") or payload.get("customer_email") or payload.get("email"))
    phone = _clean(shipping.get("phone") or billing.get("phone") or payload.get("phone"))
    addr = empty_address()
    addr.update(
        {
            "name": name,
            "business_name": _clean(shipping.get("company") or billing.get("company")),
            "lines": _lines(shipping.get("address_1") or billing.get("address_1"), shipping.get("address_2") or billing.get("address_2")),
            "suburb": _clean(shipping.get("city") or billing.get("city")),
            "state": normalize_au_state(shipping.get("state") or billing.get("state") or ""),
            "postcode": normalize_postcode(shipping.get("postcode") or billing.get("postcode") or ""),
            "phone": phone,
            "email": email,
            "country": _clean(shipping.get("country") or billing.get("country") or "AU").upper() or "AU",
            "source": "woocommerce",
        }
    )
    return addr


def address_from_shopify(payload: dict[str, Any]) -> dict[str, Any]:
    """Map a Shopify order (or shipping_address dict) to a FarmOS AU address."""
    inner = payload.get("order") if isinstance(payload.get("order"), dict) else payload
    shipping = inner.get("shipping_address") or {}
    billing = inner.get("billing_address") or {}
    customer = inner.get("customer") or {}
    if not isinstance(shipping, dict):
        shipping = {}
    if not isinstance(billing, dict):
        billing = {}
    if not isinstance(customer, dict):
        customer = {}
    name = _full_name(
        shipping.get("first_name") or billing.get("first_name") or customer.get("first_name"),
        shipping.get("last_name") or billing.get("last_name") or customer.get("last_name"),
        fallback=_clean(shipping.get("name") or shipping.get("company") or inner.get("email")),
    )
    email = _clean(
        inner.get("email")
        or inner.get("contact_email")
        or customer.get("email")
        or billing.get("email")
    )
    phone = _clean(shipping.get("phone") or billing.get("phone") or customer.get("phone") or inner.get("phone"))
    state = normalize_au_state(
        shipping.get("province_code") or shipping.get("province") or billing.get("province_code") or billing.get("province") or ""
    )
    addr = empty_address()
    addr.update(
        {
            "name": name,
            "business_name": _clean(shipping.get("company") or billing.get("company")),
            "lines": _lines(shipping.get("address1") or billing.get("address1"), shipping.get("address2") or billing.get("address2")),
            "suburb": _clean(shipping.get("city") or billing.get("city")),
            "state": state,
            "postcode": normalize_postcode(shipping.get("zip") or billing.get("zip") or shipping.get("postal_code") or ""),
            "phone": phone,
            "email": email,
            "country": _clean(shipping.get("country_code") or shipping.get("country") or "AU").upper() or "AU",
            "source": "shopify",
        }
    )
    return addr


def address_from_store_payload(payload: dict[str, Any], source: str = "") -> dict[str, Any]:
    source_l = (source or _clean(payload.get("source"))).lower()
    if source_l == "shopify":
        return address_from_shopify(payload)
    if source_l == "woocommerce":
        return address_from_woocommerce(payload)
    if payload.get("shipping_address") or (
        isinstance(payload.get("order"), dict) and payload["order"].get("shipping_address")
    ):
        return address_from_shopify(payload)
    return address_from_woocommerce(payload)


def merge_address(base: dict[str, Any] | None, override: dict[str, Any] | None) -> dict[str, Any]:
    addr = empty_address()
    for src in (base or {}, override or {}):
        for key in ("name", "business_name", "suburb", "phone", "email", "country", "source"):
            if _clean(src.get(key)):
                addr[key] = _clean(src.get(key))
        if src.get("state"):
            addr["state"] = normalize_au_state(str(src.get("state")))
        if src.get("postcode") or src.get("zip"):
            addr["postcode"] = normalize_postcode(str(src.get("postcode") or src.get("zip")))
        if src.get("lines"):
            lines = src.get("lines")
            if isinstance(lines, str):
                addr["lines"] = _lines(*lines.split("\n"))
            elif isinstance(lines, list):
                addr["lines"] = _lines(*lines)
        else:
            extra = _lines(src.get("line1") or src.get("address_1") or src.get("address1"), src.get("line2") or src.get("address_2") or src.get("address2"))
            if extra:
                addr["lines"] = extra
    addr["country"] = (addr.get("country") or "AU").upper()
    if addr["country"] in {"AUSTRALIA", "AUS"}:
        addr["country"] = "AU"
    return addr


def validate_au_address(addr: dict[str, Any], *, who: str = "address") -> list[str]:
    errors: list[str] = []
    if not _clean(addr.get("name")) and not _clean(addr.get("business_name")):
        errors.append(f"{who}: name is required.")
    if not addr.get("lines"):
        errors.append(f"{who}: street line is required.")
    if not _clean(addr.get("suburb")):
        errors.append(f"{who}: suburb is required for Australian addresses.")
    state = normalize_au_state(str(addr.get("state") or ""))
    if not state:
        errors.append(f"{who}: state must be NSW, VIC, QLD, SA, WA, TAS, NT, or ACT.")
    postcode = normalize_postcode(str(addr.get("postcode") or ""))
    if len(postcode) != 4:
        errors.append(f"{who}: postcode must be four digits.")
    return errors


def auspost_party(addr: dict[str, Any]) -> dict[str, Any]:
    lines = [line for line in (addr.get("lines") or []) if _clean(line)][:3]
    party: dict[str, Any] = {
        "name": _clean(addr.get("name")) or _clean(addr.get("business_name")) or "Recipient",
        "lines": lines or ["Address on file"],
        "suburb": _clean(addr.get("suburb")),
        "state": normalize_au_state(str(addr.get("state") or "")),
        "postcode": normalize_postcode(str(addr.get("postcode") or "")),
        "country": "AU",
    }
    if _clean(addr.get("business_name")):
        party["business_name"] = _clean(addr.get("business_name"))
    if _clean(addr.get("phone")):
        party["phone"] = _clean(addr.get("phone"))
    if _clean(addr.get("email")):
        party["email"] = _clean(addr.get("email"))
    return party


def product_group(product_id: str) -> str:
    row = PRODUCT_BY_ID.get(product_id) or PRODUCT_BY_ID[DEFAULT_PRODUCT_ID]
    return row["group"]


def build_shipment_payload(
    *,
    from_addr: dict[str, Any],
    to_addr: dict[str, Any],
    product_id: str,
    weight_g: float,
    length_cm: float,
    width_cm: float,
    height_cm: float,
    reference: str,
    contents: str,
    email_tracking: bool = True,
) -> dict[str, Any]:
    pid = product_id if product_id in PRODUCT_BY_ID else DEFAULT_PRODUCT_ID
    weight_kg = max(0.01, round(float(weight_g or 500) / 1000.0, 3))
    item: dict[str, Any] = {
        "item_reference": (reference or "ORDER")[:50],
        "product_id": pid,
        "length": max(1, int(round(float(length_cm or 20)))),
        "height": max(1, int(round(float(height_cm or 10)))),
        "width": max(1, int(round(float(width_cm or 15)))),
        "weight": weight_kg,
        "contains_dangerous_goods": False,
        "authority_to_leave": False,
        "allow_partial_delivery": False,
        "item_description": (contents or "3D printed parts")[:50],
    }
    if contents:
        item["item_contents"] = [{"description": contents[:40], "quantity": 1, "value": 1, "weight": weight_kg}]
    shipment: dict[str, Any] = {
        "shipment_reference": (reference or "ORDER")[:50],
        "customer_reference_1": (reference or "")[:50],
        "email_tracking_enabled": bool(email_tracking),
        "from": auspost_party(from_addr),
        "to": auspost_party(to_addr),
        "items": [item],
    }
    return {"shipments": [shipment]}


def parse_auspost_errors(body: Any, status_code: int) -> AusPostError:
    messages: list[str] = []
    if isinstance(body, dict):
        errors = body.get("errors") or body.get("error") or []
        if isinstance(errors, dict):
            errors = [errors]
        if isinstance(errors, str):
            messages.append(errors)
        elif isinstance(errors, list):
            for err in errors:
                if isinstance(err, str):
                    messages.append(err)
                    continue
                if not isinstance(err, dict):
                    continue
                field = _clean(err.get("field") or err.get("name") or "")
                msg = _clean(err.get("message") or err.get("error") or err.get("code") or "")
                if field and msg:
                    messages.append(f"{field}: {msg}")
                elif msg:
                    messages.append(msg)
        if not messages and body.get("message"):
            messages.append(str(body["message"]))
    joined = " ".join(messages).lower()
    if status_code == 401:
        return AusPostError(
            "Australia Post rejected the credentials (HTTP 401). Check the API key, password, and account number in Settings.",
            status_code=401,
            details=messages,
        )
    if "postcode" in joined:
        return AusPostError(
            "Australia Post rejected the postcode. Australian addresses need a 4-digit postcode that matches the suburb.",
            status_code=status_code,
            details=messages,
        )
    if "suburb" in joined or "state" in joined:
        return AusPostError(
            "Australia Post rejected the suburb or state. Use the official suburb name, an AU state code, and a matching postcode.",
            status_code=status_code,
            details=messages,
        )
    headline = messages[0] if messages else f"Australia Post returned HTTP {status_code}."
    return AusPostError(headline, status_code=status_code, details=messages)


def extract_tracking(shipment: dict[str, Any]) -> tuple[str, str]:
    consignment = _clean(shipment.get("shipment_id"))
    tracking = ""
    for item in shipment.get("items") or []:
        if not isinstance(item, dict):
            continue
        details = item.get("tracking_details") or {}
        consignment = _clean(details.get("consignment_id")) or consignment
        tracking = _clean(details.get("article_id") or details.get("consignment_id")) or tracking
    return consignment, tracking


class AusPostClient:
    def __init__(
        self,
        *,
        api_key: str,
        password: str,
        account_number: str,
        sandbox: bool = True,
        base_url: str = "",
        timeout: float = 30.0,
    ):
        self.api_key = api_key
        self.password = password
        self.account_number = account_number
        self.sandbox = sandbox
        raw = (base_url or "").rstrip("/")
        if raw:
            self.base_url = raw
        else:
            self.base_url = TEST_BASE if sandbox else LIVE_BASE
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.password and self.account_number)

    def _headers(self) -> dict[str, str]:
        return {
            "Account-Number": self.account_number,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        accept: str = "application/json",
    ) -> httpx.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = self._headers()
        headers["Accept"] = accept
        async with httpx.AsyncClient(timeout=self.timeout, auth=(self.api_key, self.password)) as client:
            resp = await client.request(method, url, headers=headers, json=json)
        if resp.status_code >= 400:
            body: Any
            try:
                body = resp.json()
            except Exception:
                body = {"message": resp.text[:400]}
            logger.warning("AusPost %s %s failed: %s", method, path, resp.status_code)
            raise parse_auspost_errors(body, resp.status_code)
        return resp

    async def create_shipments(self, payload: dict[str, Any]) -> dict[str, Any]:
        resp = await self._request("POST", "shipments", json=payload)
        return resp.json()

    async def create_labels(self, shipment_ids: list[str], product_id: str) -> dict[str, Any]:
        group = product_group(product_id)
        body = {
            "wait_for_label_url": True,
            "unlabelled_articles_only": False,
            "preferences": [
                {
                    "type": "PRINT",
                    "groups": [
                        {
                            "group": group,
                            "layout": LABEL_LAYOUT,
                            "branded": True,
                            "left_offset": 0,
                            "top_offset": 0,
                        }
                    ],
                }
            ],
            "shipments": [{"shipment_id": sid} for sid in shipment_ids],
        }
        resp = await self._request("POST", "labels", json=body)
        return resp.json()

    async def fetch_label_pdf(self, label_id: str) -> bytes:
        resp = await self._request("GET", f"labels/{label_id}", accept="application/pdf")
        content_type = (resp.headers.get("content-type") or "").lower()
        if "pdf" in content_type or resp.content[:4] == b"%PDF":
            return resp.content
        try:
            body = resp.json()
        except Exception:
            body = {}
        url = ""
        if isinstance(body, dict):
            labels = body.get("labels") or []
            if labels and isinstance(labels[0], dict):
                url = _clean(labels[0].get("url"))
            url = url or _clean(body.get("url"))
        if url:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                pdf = await client.get(url)
            if pdf.status_code >= 400 or pdf.content[:4] != b"%PDF":
                raise AusPostError("Australia Post label URL did not return a PDF.")
            return pdf.content
        raise AusPostError("Australia Post did not return a label PDF.")
