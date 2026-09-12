from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def record_audit(
    db: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    previous: Any = None,
    new: Any = None,
    actor: str = "system",
    source: str = "api",
) -> AuditLog:
    row = AuditLog(
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        previous_value=previous if isinstance(previous, (dict, list)) else {"value": previous},
        new_value=new if isinstance(new, (dict, list)) else {"value": new},
        actor=actor or "system",
        source=source,
    )
    db.add(row)
    await db.flush()
    return row
