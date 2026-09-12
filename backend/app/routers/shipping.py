from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user, require_perm
from app.models import Order, OrderLine, OrderPartNeed, User
from app.services.auspost import AusPostError, merge_address
from app.services.shipping import (
    create_auspost_label,
    create_farmos_preview,
    get_shipping_settings,
    list_shippable_orders,
    public_shipping_settings,
    read_auspost_pdf,
    save_shipping_settings,
    serialize_shippable_order,
)

router = APIRouter(prefix="/shipping", tags=["shipping"])


class ShippingSettingsIn(BaseModel):
    auspost_api_key: str | None = None
    auspost_password: str | None = None
    auspost_account_number: str | None = None
    sandbox: bool | None = None
    default_service: str | None = None
    from_address: dict | None = None
    last_package: dict | None = None


class LabelIn(BaseModel):
    order_id: UUID
    service: str = "AUS_PARCEL_REGULAR"
    weight_g: float = Field(default=500, gt=0, le=22000)
    length_cm: float = Field(default=20, gt=0, le=200)
    width_cm: float = Field(default=15, gt=0, le=200)
    height_cm: float = Field(default=10, gt=0, le=200)
    contents: str = "3D printed parts"
    reference: str = ""
    to_address: dict | None = None
    page: str = "a6"
    persist: bool = True


def _http_error(exc: AusPostError) -> HTTPException:
    detail = exc.message
    if exc.details:
        extra = "; ".join(exc.details[:6])
        if extra and extra not in detail:
            detail = f"{detail} {extra}"
    return HTTPException(exc.status_code or 400, detail)


async def _load_order(db: AsyncSession, order_id: UUID) -> Order:
    order = (
        await db.execute(
            select(Order)
            .options(
                selectinload(Order.lines).selectinload(OrderLine.product),
                selectinload(Order.part_needs).selectinload(OrderPartNeed.part),
                selectinload(Order.shipments),
            )
            .where(Order.id == order_id)
        )
    ).scalar_one_or_none()
    if not order:
        raise HTTPException(404, "Order not found")
    return order


@router.get("/orders")
async def shipping_orders(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    settings = await get_shipping_settings(db)
    rows = await list_shippable_orders(db)
    await db.commit()
    return {
        "orders": [await serialize_shippable_order(db, order, settings) for order in rows],
        "auspost_configured": bool(settings.get("configured")),
        "sandbox": bool(settings.get("sandbox", True)),
        "from_address": settings.get("from_address") or {},
        "products": settings.get("products") or [],
        "default_service": settings.get("default_service"),
        "last_package": settings.get("last_package"),
    }


@router.get("/orders/{order_id}")
async def shipping_order(
    order_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    settings = await get_shipping_settings(db)
    order = await _load_order(db, order_id)
    return await serialize_shippable_order(db, order, settings)


@router.get("/settings")
async def shipping_settings_get(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    raw = await get_shipping_settings(db)
    return public_shipping_settings(raw)


@router.patch("/settings")
async def shipping_settings_patch(
    payload: ShippingSettingsIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    raw = await save_shipping_settings(db, payload.model_dump(exclude_unset=True))
    await db.commit()
    return public_shipping_settings(raw)


@router.post("/preview-label")
async def preview_label(
    payload: LabelIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    settings = await get_shipping_settings(db)
    order = await _load_order(db, payload.order_id)
    from_addr = merge_address({}, settings.get("from_address") or {})
    to_addr = merge_address(
        order.shipping_address if isinstance(order.shipping_address, dict) else {},
        payload.to_address,
    )
    result = await create_farmos_preview(
        db,
        order,
        from_addr=from_addr,
        to_addr=to_addr,
        service=payload.service,
        weight_g=payload.weight_g,
        length_cm=payload.length_cm,
        width_cm=payload.width_cm,
        height_cm=payload.height_cm,
        contents=payload.contents,
        reference=payload.reference or order.reference,
        page=payload.page,
        persist=payload.persist,
    )
    await db.commit()
    return result


@router.post("/auspost/shipments")
async def auspost_shipments(
    payload: LabelIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_perm("packing")),
):
    settings = await get_shipping_settings(db)
    order = await _load_order(db, payload.order_id)
    try:
        result = await create_auspost_label(
            db,
            order,
            settings=settings,
            to_addr=payload.to_address or {},
            service=payload.service,
            weight_g=payload.weight_g,
            length_cm=payload.length_cm,
            width_cm=payload.width_cm,
            height_cm=payload.height_cm,
            contents=payload.contents,
            reference=payload.reference or order.reference,
            actor=user.email,
        )
    except AusPostError as exc:
        raise _http_error(exc) from exc
    await db.commit()
    return result


@router.get("/auspost/labels/{shipment_id}")
async def auspost_label_pdf(
    shipment_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    try:
        data, filename = await read_auspost_pdf(db, shipment_id)
    except AusPostError as exc:
        raise _http_error(exc) from exc
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
