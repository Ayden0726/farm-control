from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.models import BomItem, Part, Product, User
from app.schemas import BomItemOut, ProductIn, ProductOut

router = APIRouter(prefix="/products", tags=["products"])


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
    return ProductOut(
        id=product.id,
        sku=product.sku,
        name=product.name,
        description=product.description,
        woocommerce_product_id=product.woocommerce_product_id,
        is_active=product.is_active,
        bom=bom,
    )


@router.get("", response_model=list[ProductOut])
async def list_products(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    rows = (
        await db.execute(
            select(Product)
            .options(selectinload(Product.bom_items).selectinload(BomItem.part))
            .order_by(Product.sku)
        )
    ).scalars().all()
    return [_product_out(p) for p in rows]


@router.post("", response_model=ProductOut)
async def create_product(
    payload: ProductIn, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    if (await db.execute(select(Product).where(Product.sku == payload.sku))).scalar_one_or_none():
        raise HTTPException(400, "Product SKU already exists")
    product = Product(
        sku=payload.sku,
        name=payload.name,
        description=payload.description,
        woocommerce_product_id=payload.woocommerce_product_id,
        is_active=payload.is_active,
    )
    db.add(product)
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
    await db.commit()
    product = (
        await db.execute(
            select(Product)
            .options(selectinload(Product.bom_items).selectinload(BomItem.part))
            .where(Product.id == product.id)
        )
    ).scalar_one()
    return _product_out(product)


@router.put("/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: UUID, payload: ProductIn, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    product.sku = payload.sku
    product.name = payload.name
    product.description = payload.description
    product.woocommerce_product_id = payload.woocommerce_product_id
    product.is_active = payload.is_active
    existing = (
        await db.execute(select(BomItem).where(BomItem.product_id == product.id))
    ).scalars().all()
    for row in existing:
        await db.delete(row)
    await db.flush()
    for item in payload.bom:
        db.add(
            BomItem(
                product_id=product.id,
                part_id=item.part_id,
                quantity=item.quantity,
                is_optional=item.is_optional,
            )
        )
    await db.commit()
    product = (
        await db.execute(
            select(Product)
            .options(selectinload(Product.bom_items).selectinload(BomItem.part))
            .where(Product.id == product.id)
        )
    ).scalar_one()
    return _product_out(product)
