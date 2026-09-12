from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.models import (
    AssemblyKit,
    BomHardwareItem,
    BomItem,
    HardwareItem,
    OrderLine,
    Part,
    Product,
    ProductionRun,
    User,
)
from app.schemas import BomHardwareOut, BomItemOut, ProductIn, ProductOut
from app.services.production_expand import run_items_for_product
from app.services.shopify import shopify_numeric_id

router = APIRouter(prefix="/products", tags=["products"])

_LOAD = (
    selectinload(Product.bom_items).selectinload(BomItem.part),
    selectinload(Product.bom_hardware).selectinload(BomHardwareItem.hardware_item),
)


def _product_out(product: Product) -> ProductOut:
    bom = [
        BomItemOut(
            id=item.id,
            part_id=item.part_id,
            part_sku=item.part.sku if item.part else "",
            part_name=item.part.name if item.part else "",
            quantity=item.quantity,
            is_optional=item.is_optional,
        )
        for item in product.bom_items
    ]
    hardware = [
        BomHardwareOut(
            id=item.id,
            hardware_item_id=item.hardware_item_id,
            sku=item.hardware_item.sku if item.hardware_item else "",
            name=item.hardware_item.name if item.hardware_item else "",
            quantity=item.quantity,
            is_optional=item.is_optional,
        )
        for item in (product.bom_hardware or [])
    ]
    return ProductOut(
        id=product.id,
        sku=product.sku,
        name=product.name,
        description=product.description,
        woocommerce_product_id=product.woocommerce_product_id,
        shopify_product_id=getattr(product, "shopify_product_id", None),
        is_active=product.is_active,
        bom=bom,
        hardware_bom=hardware,
    )


async def _set_hardware_bom(db: AsyncSession, product: Product, items) -> None:
    for item in items:
        if not await db.get(HardwareItem, item.hardware_item_id):
            raise HTTPException(400, "Unknown hardware item in BOM")
        db.add(
            BomHardwareItem(
                product_id=product.id,
                hardware_item_id=item.hardware_item_id,
                quantity=item.quantity,
                is_optional=item.is_optional,
            )
        )


async def _sku_taken(db: AsyncSession, sku: str, exclude_id: UUID | None = None) -> bool:
    q = select(Product.id).where(Product.sku == sku)
    if exclude_id is not None:
        q = q.where(Product.id != exclude_id)
    return (await db.execute(q)).scalar_one_or_none() is not None


async def _replace_bom(db: AsyncSession, product: Product, payload: ProductIn) -> None:
    part_ids = [item.part_id for item in payload.bom]
    if len(part_ids) != len(set(part_ids)):
        raise HTTPException(400, "Each printed part can only appear once on the BOM")
    hw_ids = [item.hardware_item_id for item in payload.hardware_bom]
    if len(hw_ids) != len(set(hw_ids)):
        raise HTTPException(400, "Each hardware item can only appear once on the BOM")
    existing = (await db.execute(select(BomItem).where(BomItem.product_id == product.id))).scalars().all()
    for row in existing:
        await db.delete(row)
    hw_existing = (
        await db.execute(select(BomHardwareItem).where(BomHardwareItem.product_id == product.id))
    ).scalars().all()
    for row in hw_existing:
        await db.delete(row)
    await db.flush()
    for item in payload.bom:
        if not await db.get(Part, item.part_id):
            raise HTTPException(400, "Unknown part in BOM")
        db.add(
            BomItem(
                product_id=product.id,
                part_id=item.part_id,
                quantity=item.quantity,
                is_optional=item.is_optional,
            )
        )
    await _set_hardware_bom(db, product, payload.hardware_bom)


@router.get("", response_model=list[ProductOut])
async def list_products(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    rows = (await db.execute(select(Product).options(*_LOAD).order_by(Product.sku))).scalars().all()
    return [_product_out(p) for p in rows]


@router.get("/{product_id}/run-items")
async def product_run_items(
    product_id: UUID,
    quantity: int = 1,
    include_optional: bool = False,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    expanded = await run_items_for_product(db, product_id, quantity, include_optional)
    if not expanded:
        raise HTTPException(404, "Product not found")
    return expanded


@router.post("", response_model=ProductOut)
async def create_product(
    payload: ProductIn, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    if await _sku_taken(db, payload.sku):
        raise HTTPException(400, "Product SKU already exists")
    product = Product(
        sku=payload.sku,
        name=payload.name,
        description=payload.description,
        woocommerce_product_id=payload.woocommerce_product_id,
        shopify_product_id=shopify_numeric_id(payload.shopify_product_id),
        is_active=payload.is_active,
    )
    db.add(product)
    await db.flush()
    await _replace_bom(db, product, payload)
    await db.commit()
    product = (await db.execute(select(Product).options(*_LOAD).where(Product.id == product.id))).scalar_one()
    return _product_out(product)


@router.put("/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: UUID, payload: ProductIn, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    if await _sku_taken(db, payload.sku, exclude_id=product.id):
        raise HTTPException(400, "Product SKU already exists")
    product.sku = payload.sku
    product.name = payload.name
    product.description = payload.description
    product.woocommerce_product_id = payload.woocommerce_product_id
    product.shopify_product_id = shopify_numeric_id(payload.shopify_product_id)
    product.is_active = payload.is_active
    await _replace_bom(db, product, payload)
    await db.commit()
    product = (await db.execute(select(Product).options(*_LOAD).where(Product.id == product.id))).scalar_one()
    return _product_out(product)


@router.delete("/{product_id}")
async def delete_product(
    product_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    order_count = (
        await db.execute(select(func.count()).select_from(OrderLine).where(OrderLine.product_id == product.id))
    ).scalar_one()
    if order_count:
        raise HTTPException(
            400,
            f"Cannot delete {product.sku}: it is on {int(order_count)} order line(s). "
            "Leave it in the catalog so order history still resolves.",
        )
    kit_count = (
        await db.execute(select(func.count()).select_from(AssemblyKit).where(AssemblyKit.product_id == product.id))
    ).scalar_one()
    if kit_count:
        raise HTTPException(
            400,
            f"Cannot delete {product.sku}: {int(kit_count)} assembly kit(s) still reference it.",
        )
    await db.execute(
        update(ProductionRun).where(ProductionRun.product_id == product.id).values(product_id=None)
    )
    sku = product.sku
    try:
        await db.delete(product)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            400,
            f"Cannot delete {sku}: it is still referenced by farm records.",
        ) from exc
    return {"ok": True, "deleted": True, "sku": sku}
