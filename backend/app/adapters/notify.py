"""Notification providers. Add SMS/email/webhook implementations without changing callers."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.config import get_settings
from app.models import Notification, NotificationType

logger = logging.getLogger("farmos.notify")


class NotificationProvider(ABC):
    name: str

    @abstractmethod
    async def send(self, notification: Notification) -> None: ...


class LogProvider(NotificationProvider):
    name = "log"

    async def send(self, notification: Notification) -> None:
        logger.info("notify [%s] %s — %s", notification.type.value, notification.title, notification.body)


class WebhookProvider(NotificationProvider):
    name = "webhook"

    async def send(self, notification: Notification) -> None:
        url = get_settings().notify_webhook_url
        if not url:
            return
        payload: dict[str, Any] = {
            "type": notification.type.value,
            "title": notification.title,
            "body": notification.body,
            "severity": notification.severity,
            "entity_type": notification.entity_type,
            "entity_id": notification.entity_id,
        }
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                await client.post(url, json=payload)
        except Exception:
            logger.exception("webhook notification failed")


class SmtpProvider(NotificationProvider):
    name = "smtp"

    async def send(self, notification: Notification) -> None:
        settings = get_settings()
        if not settings.smtp_host or notification.severity not in {"warning", "error"}:
            return
        # Optional: farm operators can configure SMTP later. Failures must not block the queue.
        logger.info("smtp provider configured; would send %s", notification.title)


PROVIDERS: list[NotificationProvider] = [LogProvider(), WebhookProvider(), SmtpProvider()]


async def dispatch_notification(notification: Notification) -> None:
    for provider in PROVIDERS:
        try:
            await provider.send(notification)
        except Exception:
            logger.exception("provider %s failed", provider.name)


def register_provider(provider: NotificationProvider) -> None:
    PROVIDERS.append(provider)
