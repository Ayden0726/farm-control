from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.notify import dispatch_notification
from app.models import Notification, NotificationType


async def notify(
    db: AsyncSession,
    ntype: NotificationType,
    title: str,
    body: str = "",
    severity: str = "info",
    entity_type: str | None = None,
    entity_id: UUID | str | None = None,
) -> Notification:
    row = Notification(
        type=ntype,
        title=title,
        body=body,
        severity=severity,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id else None,
    )
    db.add(row)
    await db.flush()
    await dispatch_notification(row)
    return row
