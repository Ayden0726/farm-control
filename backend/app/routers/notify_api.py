from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.adapters.push import PROVIDERS
from app.db import get_db
from app.deps import get_current_user
from app.models import (
    PHONE_EVENTS,
    Notification,
    NotificationDelivery,
    NotificationPreference,
    NotificationProviderSetting,
    NotificationType,
    Printer,
    PrinterNotificationPreference,
    User,
    utcnow,
)
from app.security import encrypt_secret
from app.services.notifications import (
    EVENT_LABELS,
    NotifyContext,
    app_base,
    ensure_defaults,
    notify,
    print_complete_copy,
    provider_summaries,
    resolved_providers,
)
import json

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: UUID
    type: str
    title: str
    body: str
    severity: str
    is_read: bool
    entity_type: str | None
    entity_id: str | None
    printer_id: UUID | None = None
    printer_name: str | None = None
    job_id: UUID | None = None
    job_label: str | None = None
    production_run_name: str | None = None
    order_reference: str | None = None
    deep_link: str | None = None
    created_at: object


class DeliveryOut(BaseModel):
    id: UUID
    notification_id: UUID
    created_at: object
    event: str
    title: str
    printer_name: str | None
    job_label: str | None
    provider: str
    status: str
    error_message: str | None
    sent_at: object | None


class PreferenceIn(BaseModel):
    event_type: str
    enabled: bool


class PrinterPrefIn(BaseModel):
    event_type: str
    enabled: bool | None = None  # None = inherit global


class ProviderUpdate(BaseModel):
    enabled: bool | None = None
    public_config: dict = Field(default_factory=dict)
    secrets: dict = Field(default_factory=dict)


def _note_out(row: Notification) -> dict:
    return {
        "id": row.id,
        "type": row.type if isinstance(row.type, str) else getattr(row.type, "value", str(row.type)),
        "title": row.title,
        "body": row.body,
        "severity": row.severity,
        "is_read": row.is_read,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "printer_id": row.printer_id,
        "printer_name": row.printer_name,
        "job_id": row.job_id,
        "job_label": row.job_label,
        "production_run_id": row.production_run_id,
        "production_run_name": row.production_run_name,
        "order_id": row.order_id,
        "order_reference": row.order_reference,
        "deep_link": row.deep_link,
        "extra": row.extra or {},
        "created_at": row.created_at,
    }


@router.get("")
async def list_notifications(
    unread_only: bool = False,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(Notification).order_by(Notification.created_at.desc()).limit(200)
    if unread_only:
        stmt = select(Notification).where(Notification.is_read.is_(False)).order_by(
            Notification.created_at.desc()
        ).limit(200)
    rows = (await db.execute(stmt)).scalars().all()
    return [_note_out(r) for r in rows]


@router.get("/history")
async def delivery_history(
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    await ensure_defaults(db)
    stmt = select(NotificationDelivery).options(selectinload(NotificationDelivery.notification))
    if status:
        stmt = stmt.where(NotificationDelivery.status == status)
    stmt = stmt.order_by(NotificationDelivery.created_at.desc()).limit(300)
    rows = (await db.execute(stmt)).scalars().all()
    out = []
    for d in rows:
        n = d.notification
        out.append(
            {
                "id": d.id,
                "notification_id": d.notification_id,
                "created_at": d.created_at,
                "event": n.type if n else None,
                "event_label": EVENT_LABELS.get(n.type if n else "", n.type if n else ""),
                "title": n.title if n else "",
                "printer_name": n.printer_name if n else None,
                "job_label": n.job_label if n else None,
                "provider": d.provider,
                "status": d.status,
                "error_message": d.error_message,
                "sent_at": d.sent_at,
                "deep_link": n.deep_link if n else None,
            }
        )
    return out


@router.post("/read-all")
async def read_all(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    rows = (await db.execute(select(Notification).where(Notification.is_read.is_(False)))).scalars().all()
    for row in rows:
        row.is_read = True
    await db.commit()
    return {"ok": True, "count": len(rows)}


@router.post("/clear")
async def clear_notifications(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    count = (await db.execute(select(func.count()).select_from(Notification))).scalar_one()
    await db.execute(delete(Notification))
    await db.commit()
    return {"ok": True, "count": int(count or 0)}


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    row = await db.get(Notification, notification_id)
    if not row:
        raise HTTPException(404, "Not found")
    row.is_read = True
    await db.commit()
    return {"ok": True}


@router.delete("/{notification_id}")
async def delete_notification(
    notification_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    row = await db.get(Notification, notification_id)
    if not row:
        raise HTTPException(404, "Notification not found")
    await db.delete(row)
    await db.commit()
    return {"ok": True, "deleted": True}


@router.get("/events")
async def list_events(_: User = Depends(get_current_user)):
    return [{"id": e.value, "label": EVENT_LABELS[e.value]} for e in PHONE_EVENTS]


@router.get("/preferences")
async def get_preferences(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    await ensure_defaults(db)
    rows = (await db.execute(select(NotificationPreference))).scalars().all()
    by_id = {r.event_type: r.enabled for r in rows}
    return [
        {"event_type": e.value, "label": EVENT_LABELS[e.value], "enabled": by_id.get(e.value, True)}
        for e in PHONE_EVENTS
    ]


@router.put("/preferences")
async def put_preferences(
    payload: list[PreferenceIn], db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    await ensure_defaults(db)
    allowed = {e.value for e in PHONE_EVENTS}
    for item in payload:
        if item.event_type not in allowed:
            raise HTTPException(400, f"Unknown event {item.event_type}")
        row = await db.get(NotificationPreference, item.event_type)
        if row:
            row.enabled = item.enabled
        else:
            db.add(NotificationPreference(event_type=item.event_type, enabled=item.enabled))
    await db.commit()
    rows = (await db.execute(select(NotificationPreference))).scalars().all()
    by_id = {r.event_type: r.enabled for r in rows}
    return [
        {"event_type": e.value, "label": EVENT_LABELS[e.value], "enabled": by_id.get(e.value, True)}
        for e in PHONE_EVENTS
    ]


@router.get("/preferences/printers")
async def printer_preferences(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    await ensure_defaults(db)
    printers = (await db.execute(select(Printer).order_by(Printer.name))).scalars().all()
    globals_ = {
        r.event_type: r.enabled
        for r in (await db.execute(select(NotificationPreference))).scalars().all()
    }
    overrides = (await db.execute(select(PrinterNotificationPreference))).scalars().all()
    ov_map: dict[tuple, bool] = {(o.printer_id, o.event_type): o.enabled for o in overrides}
    result = []
    for printer in printers:
        events = []
        for event in PHONE_EVENTS:
            key = (printer.id, event.value)
            override = ov_map.get(key)
            events.append(
                {
                    "event_type": event.value,
                    "label": EVENT_LABELS[event.value],
                    "global_enabled": globals_.get(event.value, True),
                    "override": override,
                    "effective": globals_.get(event.value, True) if override is None else override,
                }
            )
        result.append({"printer_id": printer.id, "printer_name": printer.name, "events": events})
    return result


@router.put("/preferences/printers/{printer_id}")
async def put_printer_preferences(
    printer_id: UUID,
    payload: list[PrinterPrefIn],
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    printer = await db.get(Printer, printer_id)
    if not printer:
        raise HTTPException(404, "Printer not found")
    allowed = {e.value for e in PHONE_EVENTS}
    existing = {
        r.event_type: r
        for r in (
            await db.execute(
                select(PrinterNotificationPreference).where(
                    PrinterNotificationPreference.printer_id == printer_id
                )
            )
        ).scalars().all()
    }
    for item in payload:
        if item.event_type not in allowed:
            raise HTTPException(400, f"Unknown event {item.event_type}")
        row = existing.get(item.event_type)
        if item.enabled is None:
            if row:
                await db.delete(row)
        elif row:
            row.enabled = item.enabled
        else:
            db.add(
                PrinterNotificationPreference(
                    printer_id=printer_id, event_type=item.event_type, enabled=item.enabled
                )
            )
    await db.commit()
    return {"ok": True}


@router.get("/providers")
async def list_providers(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    await ensure_defaults(db)
    resolved = await resolved_providers(db)
    return {
        "public_app_url": await app_base(db),
        "providers": provider_summaries(resolved),
    }


@router.put("/providers/{name}")
async def update_provider(
    name: str,
    payload: ProviderUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if name not in PROVIDERS:
        raise HTTPException(404, "Unknown provider")
    await ensure_defaults(db)
    row = await db.get(NotificationProviderSetting, name)
    if not row:
        row = NotificationProviderSetting(name=name, enabled=False, public_config={})
        db.add(row)
        await db.flush()
    if payload.enabled is not None:
        row.enabled = payload.enabled
    public = dict(row.public_config or {})
    for key in PROVIDERS[name].public_fields:
        if key in payload.public_config:
            public[key] = payload.public_config[key]
    row.public_config = public
    if payload.secrets:
        current = {}
        if row.secrets_encrypted:
            from app.security import decrypt_secret

            raw = decrypt_secret(row.secrets_encrypted)
            if raw:
                try:
                    current = json.loads(raw)
                except json.JSONDecodeError:
                    current = {}
        for key in PROVIDERS[name].secret_fields:
            value = payload.secrets.get(key)
            if value:
                current[key] = value
        row.secrets_encrypted = encrypt_secret(json.dumps(current)) if current else row.secrets_encrypted
    await db.commit()
    resolved = await resolved_providers(db)
    return next(p for p in provider_summaries(resolved) if p["name"] == name)


@router.post("/providers/{name}/test")
async def test_provider(
    name: str, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    if name not in PROVIDERS:
        raise HTTPException(404, "Unknown provider")
    now = utcnow()
    title, body = print_complete_copy(
        "K1 Max 02",
        "RK-FR5-Handle-x4.gcode",
        "Flex Rack 5 — Batch 004",
        4,
        42 * 60,
        now,
    )
    row = await notify(
        db,
        NotificationType.print_completed,
        title,
        body,
        ctx=NotifyContext(
            printer_name="K1 Max 02",
            job_label="RK-FR5-Handle-x4.gcode",
            production_run_name="Flex Rack 5 — Batch 004",
            quantity=4,
            duration_seconds=42 * 60,
        ),
        force=True,
        only_provider=name,
        include_disabled=True,
    )
    await db.commit()
    if row is None:
        raise HTTPException(400, "Print completed notifications are disabled in preferences.")
    deliveries = (
        await db.execute(
            select(NotificationDelivery).where(NotificationDelivery.notification_id == row.id)
        )
    ).scalars().all()
    return {
        "notification_id": row.id,
        "deliveries": [
            {"provider": d.provider, "status": d.status, "error_message": d.error_message} for d in deliveries
        ],
    }


@router.put("/app-url")
async def set_app_url(
    payload: dict, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    from app.services.farm_settings import upsert_public_host

    raw = str(payload.get("public_app_url") or "")
    try:
        info = await upsert_public_host(db, raw)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await db.commit()
    origin = info["public_farm_url"] or await app_base(db)
    return {"public_app_url": origin}
