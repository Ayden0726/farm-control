from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.adapters.suppliers import build_supplier_adapter, public_supplier
from app.db import get_db
from app.deps import get_current_user
from app.models import (
    FilamentProduct,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
    User,
    utcnow,
)
from app.security import encrypt_secret
from app.services.filament import (
    audit,
    committed_by_product,
    cost_per_kg,
    create_spools_from_receive,
    kg,
    next_po_reference,
    recommend_rolls,
    stock_snapshot,
)
from app.services.reorder import run_reorder_pass, save_spend_controls, spend_controls

router = APIRouter(prefix="/purchasing", tags=["purchasing"])


class SupplierIn(BaseModel):
    name: str
    website: str = ""
    notes: str = ""
    adapter_type: str = "url"
    credentials: dict | None = None
    is_active: bool = True


class PoLineIn(BaseModel):
    product_id: UUID
    quantity: int = Field(ge=1, le=500)
    unit_price: float | None = None


class PoIn(BaseModel):
    supplier_id: UUID | None = None
    notes: str = ""
    reason: str = "Manual purchase order"
    lines: list[PoLineIn]


class ReceivePoIn(BaseModel):
    line_id: UUID | None = None
    product_id: UUID | None = None
    quantity: int = Field(ge=1, le=500)
    cost_per_spool: float | None = None
    location_id: UUID | None = None
    drying_status: str = "needs_drying"


class ModifyPoIn(BaseModel):
    quantity: int | None = Field(default=None, ge=1, le=500)
    unit_price: float | None = None
    supplier_id: UUID | None = None
    notes: str | None = None


class SpendIn(BaseModel):
    monthly_budget: float | None = None
    max_po_value: float | None = None
    max_price_per_kg: float | None = None
    max_price_per_spool: float | None = None
    price_increase_tolerance_pct: float | None = None
    require_approval_price_increase: bool | None = None
    require_approval_backup_supplier: bool | None = None
    require_approval_unusual_qty: bool | None = None
    never_auto_order_unknown: bool | None = True
    full_auto_enabled: bool | None = None


def _po_out(po: PurchaseOrder) -> dict:
    lines = []
    for line in po.lines:
        product = line.product
        lines.append(
            {
                "id": str(line.id),
                "product_id": str(line.product_id),
                "barcode_id": product.barcode_id if product else None,
                "filament": (
                    f"{product.manufacturer} {product.material} — {product.color}" if product else ""
                ),
                "material": product.material if product else None,
                "color": product.color if product else None,
                "spool_size_label": product.spool_size_label if product else None,
                "quantity_ordered": line.quantity_ordered,
                "quantity_received": line.quantity_received,
                "outstanding": max(0, line.quantity_ordered - line.quantity_received),
                "spool_weight_g": line.spool_weight_g,
                "unit_price": line.unit_price,
                "price_per_kg": line.price_per_kg,
                "line_total": round(line.unit_price * line.quantity_ordered, 2),
                "supplier_sku": line.supplier_sku,
                "supplier_url": product.supplier_url if product else "",
            }
        )
    return {
        "id": str(po.id),
        "reference": po.reference,
        "status": po.status,
        "supplier_id": str(po.supplier_id) if po.supplier_id else None,
        "supplier_name": po.supplier.name if po.supplier else None,
        "supplier_website": po.supplier.website if po.supplier else None,
        "reason": po.reason,
        "notes": po.notes,
        "tracking": po.tracking,
        "total": po.total,
        "created_at": po.created_at.isoformat() if po.created_at else None,
        "ordered_at": po.ordered_at.isoformat() if po.ordered_at else None,
        "expected_delivery": po.expected_delivery.isoformat() if po.expected_delivery else None,
        "approved_at": po.approved_at.isoformat() if po.approved_at else None,
        "auto_created": po.auto_created,
        "approval_required": po.approval_required,
        "lines": lines,
    }


async def _load_po(db: AsyncSession, po_id: UUID) -> PurchaseOrder:
    po = (
        await db.execute(
            select(PurchaseOrder)
            .options(
                selectinload(PurchaseOrder.supplier),
                selectinload(PurchaseOrder.lines).selectinload(PurchaseOrderLine.product),
            )
            .where(PurchaseOrder.id == po_id)
        )
    ).scalar_one_or_none()
    if not po:
        raise HTTPException(404, "Purchase order not found")
    return po


@router.get("/suppliers")
async def list_suppliers(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    rows = (await db.execute(select(Supplier).order_by(Supplier.name))).scalars().all()
    return [public_supplier(s) for s in rows]


@router.post("/suppliers")
async def create_supplier(payload: SupplierIn, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    import json

    if payload.adapter_type not in {"url", "manual", "http"}:
        raise HTTPException(400, "adapter_type must be url, manual, or http")
    row = Supplier(
        name=payload.name,
        website=payload.website,
        notes=payload.notes,
        adapter_type=payload.adapter_type,
        capabilities=[],
        is_active=payload.is_active,
        credentials_encrypted=encrypt_secret(json.dumps(payload.credentials)) if payload.credentials else None,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return public_supplier(row)


@router.patch("/suppliers/{supplier_id}")
async def update_supplier(
    supplier_id: UUID, payload: SupplierIn, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    import json

    row = await db.get(Supplier, supplier_id)
    if not row:
        raise HTTPException(404, "Supplier not found")
    row.name = payload.name
    row.website = payload.website
    row.notes = payload.notes
    row.adapter_type = payload.adapter_type
    row.is_active = payload.is_active
    if payload.credentials:
        row.credentials_encrypted = encrypt_secret(json.dumps(payload.credentials))
    await db.commit()
    return public_supplier(row)


@router.get("/spend")
async def get_spend(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    return await spend_controls(db)


@router.put("/spend")
async def put_spend(payload: SpendIn, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    data = await save_spend_controls(db, payload.model_dump(exclude_none=True))
    await db.commit()
    return data


@router.post("/evaluate")
async def evaluate_now(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    results = await run_reorder_pass(db)
    await db.commit()
    return {"created": results}


@router.get("")
async def list_pos(status: str | None = None, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    stmt = (
        select(PurchaseOrder)
        .options(
            selectinload(PurchaseOrder.supplier),
            selectinload(PurchaseOrder.lines).selectinload(PurchaseOrderLine.product),
        )
        .order_by(PurchaseOrder.created_at.desc())
    )
    if status:
        stmt = stmt.where(PurchaseOrder.status == status)
    rows = (await db.execute(stmt)).scalars().all()
    return [_po_out(p) for p in rows]


@router.post("")
async def create_po(payload: PoIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    if not payload.lines:
        raise HTTPException(400, "Add at least one line")
    po = PurchaseOrder(
        reference=await next_po_reference(db),
        status="draft",
        supplier_id=payload.supplier_id,
        reason=payload.reason,
        notes=payload.notes,
        auto_created=False,
        approval_required=True,
    )
    db.add(po)
    await db.flush()
    total = 0.0
    for line in payload.lines:
        product = await db.get(FilamentProduct, line.product_id)
        if not product:
            raise HTTPException(400, "Unknown filament product")
        unit = line.unit_price if line.unit_price is not None else (product.normal_price or product.purchase_cost)
        spool_g = product.preferred_spool_weight_g or product.filament_weight_g
        db.add(
            PurchaseOrderLine(
                purchase_order_id=po.id,
                product_id=product.id,
                quantity_ordered=line.quantity,
                spool_weight_g=spool_g,
                unit_price=unit,
                price_per_kg=cost_per_kg(unit, spool_g),
                supplier_sku=product.supplier_sku,
            )
        )
        total += unit * line.quantity
    po.total = round(total, 2)
    await audit(db, "po_created", "purchase_order", po.reference, {"total": po.total}, actor=user.email)
    await db.commit()
    return _po_out(await _load_po(db, po.id))


@router.get("/{po_id}")
async def get_po(po_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    po = await _load_po(db, po_id)
    committed_map = await committed_by_product(db)
    data = _po_out(po)
    line_extra = []
    for line, raw in zip(data["lines"], po.lines):
        product = raw.product
        if not product:
            line_extra.append(line)
            continue
        snap = await stock_snapshot(db, product, committed_map)
        rec = recommend_rolls(product, snap["available_g"])
        line["current_stock_kg"] = snap["physical_kg"]
        line["committed_kg"] = snap["committed_kg"]
        line["available_kg"] = snap["available_kg"]
        line["target_kg"] = kg(product.target_stock_g)
        line["min_kg"] = kg(product.min_stock_g)
        line["recommend"] = rec
        line_extra.append(line)
    data["lines"] = line_extra
    return data


@router.post("/{po_id}/approve")
async def approve_po(po_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    po = await _load_po(db, po_id)
    if po.status not in {"suggested", "draft", "awaiting_approval"}:
        raise HTTPException(400, f"Cannot approve a purchase order in status {po.status}")
    po.status = "approved"
    po.approved_at = utcnow()
    await audit(db, "po_approved", "purchase_order", po.reference, actor=user.email)
    await db.commit()
    return _po_out(await _load_po(db, po.id))


@router.post("/{po_id}/reject")
async def reject_po(po_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    po = await _load_po(db, po_id)
    if po.status in {"delivered", "cancelled"}:
        raise HTTPException(400, "Order is already closed")
    po.status = "cancelled"
    po.rejected_at = utcnow()
    po.closed_at = utcnow()
    await audit(db, "po_rejected", "purchase_order", po.reference, actor=user.email)
    await db.commit()
    return _po_out(await _load_po(db, po.id))


@router.post("/{po_id}/modify")
async def modify_po(
    po_id: UUID, payload: ModifyPoIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    po = await _load_po(db, po_id)
    if payload.supplier_id:
        po.supplier_id = payload.supplier_id
    if payload.notes is not None:
        po.notes = payload.notes
    if payload.quantity is not None or payload.unit_price is not None:
        for line in po.lines:
            if payload.quantity is not None:
                line.quantity_ordered = payload.quantity
            if payload.unit_price is not None:
                line.unit_price = payload.unit_price
                line.price_per_kg = cost_per_kg(line.unit_price, line.spool_weight_g)
    po.total = round(sum(ln.unit_price * ln.quantity_ordered for ln in po.lines), 2)
    if po.status == "suggested":
        po.status = "draft"
    await audit(db, "po_modified", "purchase_order", po.reference, actor=user.email)
    await db.commit()
    return _po_out(await _load_po(db, po.id))


@router.post("/{po_id}/mark-ordered")
async def mark_ordered(po_id: UUID, tracking: str = "", db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    po = await _load_po(db, po_id)
    if po.status not in {"approved", "ordered"}:
        raise HTTPException(400, "Approve the order before marking it ordered.")
    po.status = "ordered"
    po.ordered_at = utcnow()
    if tracking:
        po.tracking = tracking
    await audit(db, "po_ordered", "purchase_order", po.reference, actor=user.email)
    await db.commit()
    return _po_out(await _load_po(db, po.id))


@router.post("/{po_id}/place-order")
async def place_order(po_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    po = await _load_po(db, po_id)
    spend = await spend_controls(db)
    if po.status not in {"approved"}:
        raise HTTPException(400, "Only approved purchase orders can be sent to a supplier adapter.")
    if not po.supplier:
        raise HTTPException(400, "No supplier on this order")
    adapter = build_supplier_adapter(po.supplier)
    messages = []
    all_ok = True
    for line in po.lines:
        result = await adapter.place_order(line.product, line.quantity_ordered, line.unit_price)
        messages.append(result.message)
        all_ok = all_ok and result.ok
        if result.tracking:
            po.tracking = result.tracking
    if all_ok:
        po.status = "ordered"
        po.ordered_at = utcnow()
    else:
        po.notes = ((po.notes or "") + "\n" + " ".join(messages)).strip()
        if not spend.get("full_auto_enabled"):
            raise HTTPException(
                400,
                po.notes or "Supplier has no order API. Open the supplier page and place the order manually.",
            )
    await db.commit()
    return _po_out(await _load_po(db, po.id))


@router.post("/{po_id}/ship")
async def mark_shipped(po_id: UUID, tracking: str = "", db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    po = await _load_po(db, po_id)
    po.status = "shipped"
    if tracking:
        po.tracking = tracking
    await db.commit()
    return _po_out(await _load_po(db, po.id))


@router.post("/{po_id}/receive")
async def receive_po(
    po_id: UUID, payload: ReceivePoIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    po = await _load_po(db, po_id)
    if po.status in {"cancelled", "delivered"}:
        raise HTTPException(400, "This purchase order is closed")
    line = None
    if payload.line_id:
        line = next((ln for ln in po.lines if ln.id == payload.line_id), None)
    elif payload.product_id:
        line = next((ln for ln in po.lines if ln.product_id == payload.product_id), None)
    elif len(po.lines) == 1:
        line = po.lines[0]
    if not line or not line.product:
        raise HTTPException(400, "Which line is being received?")
    outstanding = max(0, line.quantity_ordered - line.quantity_received)
    if payload.quantity > outstanding:
        raise HTTPException(400, f"Only {outstanding} rolls are still outstanding on this line.")
    cost = payload.cost_per_spool if payload.cost_per_spool is not None else line.unit_price
    try:
        spools = await create_spools_from_receive(
            db,
            line.product,
            payload.quantity,
            cost,
            supplier_id=po.supplier_id,
            purchase_order_id=po.id,
            location_id=payload.location_id,
            actor=user.email,
            drying_status=payload.drying_status,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    line.quantity_received += payload.quantity
    ordered = sum(ln.quantity_ordered for ln in po.lines)
    received = sum(ln.quantity_received for ln in po.lines)
    if received >= ordered:
        po.status = "delivered"
        po.closed_at = utcnow()
    else:
        po.status = "partially_received"
    await audit(
        db,
        "po_received",
        "purchase_order",
        po.reference,
        {"quantity": payload.quantity, "outstanding": ordered - received},
        actor=user.email,
    )
    await db.commit()
    po = await _load_po(db, po.id)
    from app.routers.filament_ops import _spool_detail
    from sqlalchemy.orm import selectinload
    from app.models import FilamentSpool

    loaded = (
        await db.execute(
            select(FilamentSpool)
            .options(
                selectinload(FilamentSpool.assigned_printer),
                selectinload(FilamentSpool.location),
                selectinload(FilamentSpool.product),
            )
            .where(FilamentSpool.id.in_([s.id for s in spools]))
        )
    ).scalars().all()
    return {
        "purchase_order": _po_out(po),
        "message": f"{len(loaded)} New Rolls Created",
        "spools": [_spool_detail(s) for s in loaded],
        "print_path": "/labels/print?kind=spool&ids=" + ",".join(str(s.id) for s in loaded),
    }


@router.post("/{po_id}/close")
async def close_po(po_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    po = await _load_po(db, po_id)
    po.closed_at = utcnow()
    if po.status == "partially_received":
        po.status = "delivered"
    await audit(db, "po_closed", "purchase_order", po.reference, actor=user.email)
    await db.commit()
    return _po_out(await _load_po(db, po.id))
