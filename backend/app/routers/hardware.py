from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user, require_perm
from app.models import HardwareItem, HardwareMovement, User
from app.services.barcodes import unique_public_code
from app.services.hardware import (
    adjust_hardware,
    hardware_public_code,
    item_out,
    run_hardware_reorder_pass,
)

router = APIRouter(prefix="/hardware", tags=["hardware"])


class HardwareIn(BaseModel):
    sku: str
    name: str
    category: str = "hardware"
    supplier: str = ""
    supplier_url: str = ""
    purchase_cost: float = 0
    unit_cost: float = 0
    quantity_on_hand: float = 0
    min_stock: float = 0
    target_stock: float = 0
    storage_location: str = ""
    reorder_mode: str = "create_purchase_order"
    approval_required: bool = True
    barcode: str = ""
    notes: str = ""
    is_active: bool = True


class HardwareAdjust(BaseModel):
    quantity: float
    reason: str = "adjust"
    notes: str = ""


@router.get("")
async def list_hardware(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    rows = (await db.execute(select(HardwareItem).order_by(HardwareItem.sku))).scalars().all()
    return [item_out(r) for r in rows]


@router.post("/reorder/run")
async def run_reorder(db: AsyncSession = Depends(get_db), _: User = Depends(require_perm("inventory"))):
    results = await run_hardware_reorder_pass(db)
    await db.commit()
    return {"created": results}


@router.post("")
async def create_hardware(
    payload: HardwareIn, db: AsyncSession = Depends(get_db), user: User = Depends(require_perm("inventory"))
):
    if (await db.execute(select(HardwareItem).where(HardwareItem.sku == payload.sku))).scalar_one_or_none():
        raise HTTPException(400, "SKU already exists")
    item = HardwareItem(**payload.model_dump())
    db.add(item)
    await db.flush()
    item.public_code = await unique_public_code(
        db, HardwareItem, "public_code", hardware_public_code(item.sku)
    )
    await db.commit()
    await db.refresh(item)
    return item_out(item)


@router.get("/{item_id}")
async def get_hardware(item_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    item = await db.get(HardwareItem, item_id)
    if not item:
        raise HTTPException(404, "Not found")
    moves = (
        await db.execute(
            select(HardwareMovement)
            .where(HardwareMovement.hardware_item_id == item.id)
            .order_by(HardwareMovement.created_at.desc())
            .limit(50)
        )
    ).scalars().all()
    return {
        **item_out(item),
        "movements": [
            {
                "id": str(m.id),
                "quantity": m.quantity,
                "reason": m.reason,
                "notes": m.notes,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in moves
        ],
    }


@router.patch("/{item_id}")
async def update_hardware(
    item_id: UUID,
    payload: HardwareIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_perm("inventory")),
):
    item = await db.get(HardwareItem, item_id)
    if not item:
        raise HTTPException(404, "Not found")
    for k, v in payload.model_dump().items():
        setattr(item, k, v)
    await db.commit()
    await db.refresh(item)
    return item_out(item)


@router.post("/{item_id}/adjust")
async def adjust(
    item_id: UUID,
    payload: HardwareAdjust,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_perm("inventory")),
):
    try:
        item = await adjust_hardware(db, item_id, payload.quantity, payload.reason, payload.notes, user.email)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    await db.commit()
    return item_out(item)
