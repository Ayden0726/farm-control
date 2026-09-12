from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.push import PROVIDERS, PushMessage
from app.config import get_settings
from app.models import (
    PHONE_EVENTS,
    AppSetting,
    Notification,
    NotificationDelivery,
    NotificationPreference,
    NotificationProviderSetting,
    NotificationType,
    PrinterNotificationPreference,
    utcnow,
)
from app.security import decrypt_secret, encrypt_secret

logger = logging.getLogger("farmos.notify")

EVENT_LABELS: dict[str, str] = {
    NotificationType.print_completed.value: "Print completed",
    NotificationType.print_failed.value: "Print failed",
    NotificationType.printer_offline.value: "Printer offline",
    NotificationType.printer_error.value: "Printer error",
    NotificationType.bed_needs_clearing.value: "Bed needs clearing",
    NotificationType.production_run_completed.value: "Production run complete",
    NotificationType.order_production_complete.value: "Order finished production",
    NotificationType.order_ready.value: "Order ready for fulfilment",
    NotificationType.filament_low.value: "Filament low",
    NotificationType.filament_reorder.value: "Filament reorder",
    NotificationType.maintenance_due.value: "Maintenance due",
}

FIELD_LABELS: dict[str, str] = {
    "server": "Server URL",
    "topic": "Topic",
    "chat_id": "Chat ID",
    "host": "SMTP host",
    "port": "SMTP port",
    "user": "SMTP username",
    "from_address": "From address",
    "to_address": "To address",
    "from_number": "From number",
    "to_number": "To number",
    "token": "Access token",
    "app_token": "Application token",
    "user_key": "User key",
    "webhook_url": "Webhook URL",
    "bot_token": "Bot token",
    "password": "Password",
    "account_sid": "Account SID",
    "auth_token": "Auth token",
    "url": "Webhook URL",
}


def _env_provider_defaults() -> dict[str, dict[str, Any]]:
    s = get_settings()
    return {
        "ntfy": {
            "enabled": bool(s.ntfy_topic),
            "public": {"server": s.ntfy_server or "https://ntfy.sh", "topic": s.ntfy_topic},
            "secrets": {"token": s.ntfy_token},
        },
        "pushover": {
            "enabled": bool(s.pushover_app_token and s.pushover_user_key),
            "public": {},
            "secrets": {"app_token": s.pushover_app_token, "user_key": s.pushover_user_key},
        },
        "discord": {
            "enabled": bool(s.discord_webhook_url),
            "public": {},
            "secrets": {"webhook_url": s.discord_webhook_url},
        },
        "telegram": {
            "enabled": bool(s.telegram_bot_token and s.telegram_chat_id),
            "public": {"chat_id": s.telegram_chat_id},
            "secrets": {"bot_token": s.telegram_bot_token},
        },
        "email": {
            "enabled": bool(s.smtp_host and (s.smtp_to or s.smtp_user)),
            "public": {
                "host": s.smtp_host,
                "port": str(s.smtp_port),
                "user": s.smtp_user,
                "from_address": s.smtp_from,
                "to_address": s.smtp_to or s.smtp_user,
            },
            "secrets": {"password": s.smtp_password},
        },
        "sms": {
            "enabled": bool(s.twilio_account_sid and s.sms_to),
            "public": {"from_number": s.twilio_from, "to_number": s.sms_to},
            "secrets": {"account_sid": s.twilio_account_sid, "auth_token": s.twilio_auth_token},
        },
        "webhook": {
            "enabled": bool(s.notify_webhook_url),
            "public": {},
            "secrets": {"url": s.notify_webhook_url},
        },
    }


@dataclass
class NotifyContext:
    printer_id: UUID | None = None
    printer_name: str | None = None
    job_id: UUID | None = None
    job_label: str | None = None
    production_run_id: UUID | None = None
    production_run_name: str | None = None
    order_id: UUID | None = None
    order_reference: str | None = None
    quantity: int | None = None
    duration_seconds: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def format_duration(seconds: int | None) -> str:
    total = max(0, int(seconds or 0))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def _setting_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


async def app_base(db: AsyncSession) -> str:
    row = await db.get(AppSetting, "public_app_url")
    stored = _setting_text(row.value if row else None).strip()
    if stored:
        return stored.rstrip("/")
    return get_settings().public_app_url.rstrip("/")


async def recently_notified(
    db: AsyncSession,
    event: str,
    printer_id: UUID | None,
    hours: float = 6,
) -> bool:
    cutoff = utcnow() - timedelta(hours=hours)
    stmt = select(Notification).where(Notification.type == event, Notification.created_at >= cutoff)
    if printer_id is not None:
        stmt = stmt.where(Notification.printer_id == printer_id)
    return (await db.execute(stmt.limit(1))).scalars().first() is not None


def deep_link_for(ntype: NotificationType, ctx: NotifyContext, base: str) -> str:
    if ctx.printer_id and ntype in {
        NotificationType.print_completed,
        NotificationType.print_failed,
        NotificationType.bed_needs_clearing,
        NotificationType.printer_offline,
        NotificationType.printer_error,
        NotificationType.maintenance_due,
    }:
        return f"{base}/printers/{ctx.printer_id}"
    if ntype in {NotificationType.order_ready, NotificationType.order_production_complete} and ctx.order_id:
        return f"{base}/orders/{ctx.order_id}"
    if ntype == NotificationType.production_run_completed and ctx.production_run_id:
        return f"{base}/production/{ctx.production_run_id}"
    if ntype == NotificationType.filament_low:
        return f"{base}/filament"
    if ntype == NotificationType.filament_reorder:
        po_id = (ctx.extra or {}).get("purchase_order_id")
        if po_id:
            return f"{base}/filament/purchasing/{po_id}"
        return f"{base}/filament/purchasing"
    if ctx.job_id:
        return f"{base}/queue"
    return f"{base}/"


def click_label_for(ntype: NotificationType) -> str:
    if ntype in {NotificationType.print_completed, NotificationType.bed_needs_clearing}:
        return "Open printer — clear bed"
    if ntype == NotificationType.print_failed:
        return "Open printer"
    if ntype in {NotificationType.order_ready, NotificationType.order_production_complete}:
        return "Open order"
    if ntype == NotificationType.filament_reorder:
        return "Review Order"
    return "Open Print FarmOS"


async def ensure_defaults(db: AsyncSession) -> None:
    existing = {
        r.event_type
        for r in (await db.execute(select(NotificationPreference))).scalars().all()
    }
    for event in PHONE_EVENTS:
        if event.value not in existing:
            db.add(NotificationPreference(event_type=event.value, enabled=True))
    for name, provider in PROVIDERS.items():
        row = await db.get(NotificationProviderSetting, name)
        if row is None:
            env = _env_provider_defaults().get(name, {"enabled": False, "public": {}, "secrets": {}})
            secrets = {k: v for k, v in env["secrets"].items() if v}
            db.add(
                NotificationProviderSetting(
                    name=name,
                    enabled=bool(env["enabled"]),
                    public_config={k: v for k, v in env["public"].items() if v not in (None, "")},
                    secrets_encrypted=encrypt_secret(json.dumps(secrets)) if secrets else None,
                )
            )
    await db.flush()


async def event_allowed(db: AsyncSession, event: str, printer_id: UUID | None) -> bool:
    pref = await db.get(NotificationPreference, event)
    global_on = True if pref is None else pref.enabled
    if printer_id is None:
        return global_on
    override = (
        await db.execute(
            select(PrinterNotificationPreference).where(
                PrinterNotificationPreference.printer_id == printer_id,
                PrinterNotificationPreference.event_type == event,
            )
        )
    ).scalar_one_or_none()
    if override is None:
        return global_on
    return override.enabled


def _decrypt_secrets(row: NotificationProviderSetting) -> dict[str, Any]:
    if not row.secrets_encrypted:
        return {}
    raw = decrypt_secret(row.secrets_encrypted)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


async def resolved_providers(db: AsyncSession) -> list[tuple[str, bool, dict[str, Any], dict[str, Any]]]:
    await ensure_defaults(db)
    env = _env_provider_defaults()
    out = []
    for name, provider in PROVIDERS.items():
        row = await db.get(NotificationProviderSetting, name)
        env_cfg = env.get(name, {"enabled": False, "public": {}, "secrets": {}})
        public = dict(env_cfg["public"])
        secrets = dict(env_cfg["secrets"])
        enabled = bool(env_cfg["enabled"])
        if row:
            enabled = row.enabled
            public.update({k: v for k, v in (row.public_config or {}).items() if v not in (None, "")})
            secrets.update({k: v for k, v in _decrypt_secrets(row).items() if v})
        out.append((name, enabled, public, secrets))
    return out


def provider_summaries(resolved: list[tuple[str, bool, dict[str, Any], dict[str, Any]]]) -> list[dict[str, Any]]:
    summaries = []
    for name, enabled, public, secrets in resolved:
        provider = PROVIDERS[name]
        summaries.append(
            {
                "name": name,
                "label": provider.label,
                "description": provider.description,
                "enabled": enabled,
                "configured": provider.is_configured(public, secrets),
                "public_config": {k: public.get(k) or "" for k in provider.public_fields},
                "public_fields": [
                    {
                        "name": field,
                        "label": FIELD_LABELS.get(field, field.replace("_", " ").title()),
                        "value": public.get(field) or "",
                    }
                    for field in provider.public_fields
                ],
                "secret_fields": [
                    {
                        "name": field,
                        "label": FIELD_LABELS.get(field, field.replace("_", " ").title()),
                        "set": bool(secrets.get(field)),
                    }
                    for field in provider.secret_fields
                ],
            }
        )
    return summaries


async def _record_delivery(
    db: AsyncSession,
    notification: Notification,
    provider: str,
    status: str,
    error: str | None = None,
) -> None:
    db.add(
        NotificationDelivery(
            notification_id=notification.id,
            provider=provider,
            status=status,
            error_message=error,
            sent_at=utcnow() if status == "sent" else None,
        )
    )
    await db.flush()
    if status == "failed":
        logger.error("notification provider %s failed: %s", provider, error)
    elif status == "skipped":
        logger.info("notification provider %s skipped: %s", provider, error)


async def dispatch_push(
    db: AsyncSession,
    notification: Notification,
    ntype: NotificationType,
    *,
    only_provider: str | None = None,
    include_disabled: bool = False,
) -> None:
    message = PushMessage(
        title=notification.title,
        body=notification.body,
        event=ntype.value,
        severity=notification.severity,
        click_url=notification.deep_link,
        click_label=click_label_for(ntype),
        tags=["farmos", ntype.value.replace("_", "-")],
        extra=notification.extra or {},
    )
    resolved = await resolved_providers(db)
    attempted = False
    for name, enabled, public, secrets in resolved:
        if only_provider and name != only_provider:
            continue
        provider = PROVIDERS[name]
        if not enabled and not include_disabled:
            continue
        attempted = True
        if not provider.is_configured(public, secrets):
            await _record_delivery(
                db,
                notification,
                name,
                "skipped",
                "Provider is missing credentials or topic/URL.",
            )
            continue
        try:
            await provider.send(message, public, secrets)
            await _record_delivery(db, notification, name, "sent")
        except Exception as send_error:
            await _record_delivery(db, notification, name, "failed", str(send_error)[:2000])
    if not attempted:
        reason = (
            f"Provider '{only_provider}' is disabled. Enable it in Settings, then send a test."
            if only_provider
            else "No phone notification provider is enabled. Configure ntfy (or another provider) in Settings."
        )
        await _record_delivery(db, notification, only_provider or "none", "skipped", reason)


async def notify(
    db: AsyncSession,
    ntype: NotificationType,
    title: str,
    body: str = "",
    severity: str = "info",
    entity_type: str | None = None,
    entity_id: UUID | str | None = None,
    ctx: NotifyContext | None = None,
    *,
    force: bool = False,
    only_provider: str | None = None,
    include_disabled: bool = False,
) -> Notification | None:
    ctx = ctx or NotifyContext()
    await ensure_defaults(db)
    allowed = await event_allowed(db, ntype.value, ctx.printer_id)
    if not force and not allowed and ntype != NotificationType.info:
        logger.info("notification %s suppressed by preferences", ntype.value)
        return None
    base = await app_base(db)
    extra = dict(ctx.extra or {})
    if ctx.quantity is not None:
        extra.setdefault("quantity", ctx.quantity)
    if ctx.duration_seconds is not None:
        extra.setdefault("duration_seconds", ctx.duration_seconds)
    row = Notification(
        type=ntype.value,
        title=title[:255],
        body=body,
        severity=severity,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id else None,
        printer_id=ctx.printer_id,
        printer_name=ctx.printer_name,
        job_id=ctx.job_id,
        job_label=ctx.job_label,
        production_run_id=ctx.production_run_id,
        production_run_name=ctx.production_run_name,
        order_id=ctx.order_id,
        order_reference=ctx.order_reference,
        deep_link=deep_link_for(ntype, ctx, base),
        extra=extra,
    )
    db.add(row)
    await db.flush()
    await dispatch_push(
        db,
        row,
        ntype,
        only_provider=only_provider,
        include_disabled=include_disabled,
    )
    return row


def print_complete_copy(
    printer_name: str,
    filename: str,
    run_name: str | None,
    quantity: int,
    duration_seconds: int,
    completed_at: datetime,
    assume_ejection: bool = False,
) -> tuple[str, str]:
    when = completed_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    title = f"{printer_name} — Print Complete"
    if assume_ejection:
        status_line = "Status: Bed assumed clear (automatic part removal)"
        next_step = "The next queued job can start on this printer without a bed-clear confirmation."
    else:
        status_line = "Status: Waiting for Bed Clear"
        next_step = "Open Print FarmOS to clear the bed and start the next queued job."
    body = (
        f"{filename} has finished printing.\n\n"
        f"Production Run: {run_name or '—'}\n"
        f"Quantity: {quantity}\n"
        f"{status_line}\n"
        f"Duration: {format_duration(duration_seconds)}\n"
        f"Completed: {when}\n\n"
        f"{next_step}"
    )
    return title, body
