from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import QcFailureReason

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


async def ensure_mes_defaults(db: AsyncSession) -> None:
    existing = (await db.execute(select(QcFailureReason))).scalars().first()
    if existing:
        return
    for i, (code, label) in enumerate(DEFAULT_FAILURE_REASONS):
        db.add(QcFailureReason(code=code, label=label, sort_order=i, is_active=True))
    from app.services.maintenance_rules import ensure_default_rules

    await ensure_default_rules(db)
    await db.flush()
