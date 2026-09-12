from __future__ import annotations

import base64
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.models import FilamentProduct, FilamentSpool, PartBin, Printer, User
from app.services.filament import audit
from app.services.labels import code128_svg, label_html_page, qr_png_bytes
from app.services.notifications import app_base

router = APIRouter(prefix="/labels", tags=["labels"])


class SheetIn(BaseModel):
    kind: str = "product"
    items: list[dict] = Field(default_factory=list)
    # items: [{id, copies}]
    width_mm: float = 54
    height_mm: float = 70
    columns: int = 3
    layout: str = "sheet"


def _data_qr(kind: str, token: str, base: str) -> str:
    raw = qr_png_bytes(kind, token, base)
    return "data:image/png;base64," + base64.b64encode(raw).decode()


def _data_barcode(code: str) -> str:
    raw = code128_svg(code)
    return "data:image/svg+xml;base64," + base64.b64encode(raw).decode()


def _product_card(product: FilamentProduct, qr_url: str, barcode_url: str) -> dict:
    return {
        "title": product.manufacturer,
        "lines": [product.product_name or product.material, product.color, product.spool_size_label],
        "code": product.barcode_id,
        "qr_url": qr_url,
        "barcode_url": barcode_url,
        "kind": "product",
        "id": str(product.id),
    }


def _spool_card(spool: FilamentSpool, qr_url: str) -> dict:
    product = spool.product
    manufacturer = (product.manufacturer if product else spool.manufacturer) or ""
    material = (product.material if product else spool.material) or ""
    color = (product.color if product else spool.color) or ""
    size = (product.spool_size_label if product else "") or (
        f"{spool.initial_weight_g / 1000:.0f} kg" if spool.initial_weight_g >= 1000 else f"{spool.initial_weight_g:.0f} g"
    )
    return {
        "title": manufacturer,
        "lines": [material, color, size],
        "code": spool.public_code or spool.qr_token,
        "qr_url": qr_url,
        "barcode_url": "",
        "kind": "spool",
        "id": str(spool.id),
    }


@router.get("/code128/{code}")
async def code128(code: str, _: User = Depends(get_current_user)):
    try:
        data = code128_svg(code)
    except Exception as exc:
        raise HTTPException(400, f"Could not encode Code 128: {exc}") from exc
    return Response(content=data, media_type="image/svg+xml")


@router.get("/qr/{kind}/{token}")
async def label_qr(kind: str, token: str, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    base = await app_base(db)
    return Response(content=qr_png_bytes(kind, token, base), media_type="image/png")


@router.post("/sheet")
async def label_sheet(
    payload: SheetIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    cards: list[dict] = []
    base = await app_base(db)
    if payload.kind == "product":
        for item in payload.items:
            product = await db.get(FilamentProduct, UUID(str(item["id"])))
            if not product:
                continue
            copies = max(1, int(item.get("copies") or 1))
            qr = _data_qr("product", product.barcode_id, base)
            bar = _data_barcode(product.barcode_id)
            for _ in range(copies):
                cards.append(_product_card(product, qr, bar))
        await audit(db, "labels_generated", "product", "sheet", {"count": len(cards)}, actor=user.email)
    elif payload.kind == "spool":
        for item in payload.items:
            spool = (
                await db.execute(
                    select(FilamentSpool)
                    .options(selectinload(FilamentSpool.product))
                    .where(FilamentSpool.id == UUID(str(item["id"])))
                )
            ).scalar_one_or_none()
            if not spool:
                continue
            copies = max(1, int(item.get("copies") or 1))
            token = spool.public_code or spool.qr_token
            qr = _data_qr("spool", token, base)
            for _ in range(copies):
                cards.append(_spool_card(spool, qr))
        await audit(db, "labels_generated", "spool", "sheet", {"count": len(cards)}, actor=user.email)
    elif payload.kind == "printer":
        for item in payload.items:
            printer = await db.get(Printer, UUID(str(item["id"])))
            if not printer:
                continue
            token = printer.public_code or printer.qr_token
            cards.append(
                {
                    "title": printer.name,
                    "lines": [printer.model, printer.public_code or ""],
                    "code": token,
                    "qr_url": _data_qr("printer", token, base),
                    "barcode_url": _data_barcode(token),
                    "kind": "printer",
                    "id": str(printer.id),
                }
            )
        await audit(db, "labels_generated", "printer", "sheet", {"count": len(cards)}, actor=user.email)
    elif payload.kind in {"bin", "finished_part", "production"}:
        for item in payload.items:
            bin_row = await db.get(PartBin, UUID(str(item["id"])))
            if not bin_row:
                continue
            token = bin_row.public_code or bin_row.qr_token
            cards.append(
                {
                    "title": bin_row.name,
                    "lines": [bin_row.location or bin_row.kind, bin_row.kind],
                    "code": token,
                    "qr_url": _data_qr("bin", token, base),
                    "barcode_url": _data_barcode(token),
                    "kind": "bin",
                    "id": str(bin_row.id),
                }
            )
        await audit(db, "labels_generated", "bin", "sheet", {"count": len(cards)}, actor=user.email)
    else:
        raise HTTPException(400, "Unknown label kind")
    await db.commit()
    html = label_html_page(
        "Print FarmOS labels",
        cards,
        width_mm=payload.width_mm,
        height_mm=payload.height_mm,
        columns=payload.columns,
        layout=payload.layout,
    )
    return {"html": html, "count": len(cards), "cards": cards}


@router.get("/preview", response_class=HTMLResponse)
async def preview_sheet(
    kind: str = "product",
    ids: str = Query(""),
    copies: int = 1,
    width_mm: float = 54,
    height_mm: float = 70,
    columns: int = 3,
    layout: str = "sheet",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    items = [{"id": i, "copies": copies} for i in ids.split(",") if i]
    payload = SheetIn(kind=kind, items=items, width_mm=width_mm, height_mm=height_mm, columns=columns, layout=layout)
    data = await label_sheet(payload, db, user)
    return HTMLResponse(data["html"])
