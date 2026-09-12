from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BomHardwareItem, HardwareItem, Order, Product, QcFailureReason

DEFAULT_FAILURE_REASONS = [
    ("stringing", "Stringing"),
    ("warping", "Warping"),
    ("layer_shift", "Layer shift"),
    ("poor_first_layer", "Poor first layer"),
    ("under_extrusion", "Under extrusion"),
    ("dimensional", "Dimensional issue"),
    ("surface", "Surface defect"),
    ("support_damage", "Support damage"),
    ("mechanical", "Mechanical failure"),
    ("printer_error", "Printer error"),
    ("other", "Other"),
]

DEMO_HARDWARE = [
    ("HW-M4-INSERT", "M4 Heat-Set Insert", "hardware", 0.08, 50, 300, 120),
    ("HW-M4-SCREW", "M4 Screw", "fasteners", 0.04, 50, 300, 200),
    ("HW-MAGNET", "Magnet 6x3 mm", "hardware", 0.12, 20, 100, 40),
    ("PKG-BOX-FR5", "Flex Rack 5 box", "packaging", 1.40, 10, 40, 18),
    ("PKG-BUBBLE", "Bubble wrap roll", "packaging", 8.50, 1, 4, 2),
    ("PKG-LABEL", "Shipping label roll", "labels", 12.00, 1, 3, 1),
]


async def ensure_mes_defaults(db: AsyncSession) -> None:
    have = {r.code for r in (await db.execute(select(QcFailureReason))).scalars().all()}
    for i, (code, label) in enumerate(DEFAULT_FAILURE_REASONS):
        if code not in have:
            db.add(QcFailureReason(code=code, label=label, sort_order=i, is_active=True))
    from app.services.maintenance_rules import ensure_default_rules

    await ensure_default_rules(db)
    await _backfill_order_codes(db)
    await _ensure_demo_hardware(db)
    await db.flush()


async def _backfill_order_codes(db: AsyncSession) -> None:
    from app.services.codes import next_order_code

    rows = (await db.execute(select(Order).where(Order.public_code.is_(None)))).scalars().all()
    for order in rows:
        order.public_code = await next_order_code(db, order.reference)


async def _ensure_demo_hardware(db: AsyncSession) -> None:
    if (await db.execute(select(HardwareItem))).scalars().first():
        return
    product = (await db.execute(select(Product).where(Product.sku == "RK-FR5"))).scalar_one_or_none()
    if not product:
        return
    from app.services.barcodes import unique_public_code
    from app.services.hardware import hardware_public_code

    created: dict[str, HardwareItem] = {}
    for sku, name, category, unit, min_s, target, qty in DEMO_HARDWARE:
        item = HardwareItem(
            sku=sku,
            name=name,
            category=category,
            unit_cost=unit,
            purchase_cost=unit,
            min_stock=min_s,
            target_stock=target,
            quantity_on_hand=qty,
            reorder_mode="create_purchase_order",
        )
        db.add(item)
        await db.flush()
        item.public_code = await unique_public_code(db, HardwareItem, "public_code", hardware_public_code(sku))
        created[sku] = item
    bom = [
        ("HW-M4-INSERT", 16),
        ("HW-M4-SCREW", 16),
        ("PKG-BOX-FR5", 1),
        ("PKG-LABEL", 1),
    ]
    for sku, qty in bom:
        db.add(BomHardwareItem(product_id=product.id, hardware_item_id=created[sku].id, quantity=qty))
