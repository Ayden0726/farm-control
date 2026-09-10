"""Push / phone notification providers. Register new adapters here without changing callers."""

from __future__ import annotations

import logging
import smtplib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger("farmos.push")


@dataclass
class PushMessage:
    title: str
    body: str
    event: str
    severity: str = "info"
    click_url: str | None = None
    click_label: str = "Open RackKit FarmOS"
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def priority(self) -> str:
        if self.severity == "error":
            return "high"
        if self.severity == "warning":
            return "default"
        return "low"


class PushProvider(ABC):
    name: str
    label: str
    description: str
    public_fields: tuple[str, ...] = ()
    secret_fields: tuple[str, ...] = ()

    def is_configured(self, public: dict[str, Any], secrets: dict[str, Any]) -> bool:
        return True

    @abstractmethod
    async def send(self, message: PushMessage, public: dict[str, Any], secrets: dict[str, Any]) -> None: ...


class NtfyProvider(PushProvider):
    name = "ntfy"
    label = "ntfy"
    description = "Self-hosted or ntfy.sh phone push. Install the ntfy app and subscribe to your topic."
    public_fields = ("server", "topic")
    secret_fields = ("token",)

    def is_configured(self, public: dict[str, Any], secrets: dict[str, Any]) -> bool:
        return bool(public.get("topic"))

    async def send(self, message: PushMessage, public: dict[str, Any], secrets: dict[str, Any]) -> None:
        server = (public.get("server") or "https://ntfy.sh").rstrip("/")
        topic = public["topic"]
        headers: dict[str, str] = {
            "Title": message.title,
            "Priority": "high" if message.priority == "high" else "default",
            "Tags": ",".join(message.tags or ["3d-printer"]),
        }
        if message.click_url:
            headers["Click"] = message.click_url
            headers["Actions"] = f"view, {message.click_label}, {message.click_url}, clear=true"
        token = secrets.get("token")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(f"{server}/{quote(topic)}", content=message.body.encode("utf-8"), headers=headers)
            resp.raise_for_status()


class PushoverProvider(PushProvider):
    name = "pushover"
    label = "Pushover"
    description = "Pushover mobile push (iOS/Android)."
    public_fields = ()
    secret_fields = ("app_token", "user_key")

    def is_configured(self, public: dict[str, Any], secrets: dict[str, Any]) -> bool:
        return bool(secrets.get("app_token") and secrets.get("user_key"))

    async def send(self, message: PushMessage, public: dict[str, Any], secrets: dict[str, Any]) -> None:
        data = {
            "token": secrets["app_token"],
            "user": secrets["user_key"],
            "title": message.title,
            "message": message.body,
            "priority": 1 if message.priority == "high" else 0,
        }
        if message.click_url:
            data["url"] = message.click_url
            data["url_title"] = message.click_label
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post("https://api.pushover.net/1/messages.json", data=data)
            resp.raise_for_status()


class DiscordProvider(PushProvider):
    name = "discord"
    label = "Discord"
    description = "Discord incoming webhook (channel message)."
    public_fields = ()
    secret_fields = ("webhook_url",)

    def is_configured(self, public: dict[str, Any], secrets: dict[str, Any]) -> bool:
        return bool(secrets.get("webhook_url"))

    async def send(self, message: PushMessage, public: dict[str, Any], secrets: dict[str, Any]) -> None:
        color = 0xE8A54B if message.severity != "error" else 0xF07167
        payload = {
            "username": "RackKit FarmOS",
            "embeds": [
                {
                    "title": message.title,
                    "description": message.body,
                    "color": color,
                    "url": message.click_url,
                }
            ],
        }
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(secrets["webhook_url"], json=payload)
            resp.raise_for_status()


class TelegramProvider(PushProvider):
    name = "telegram"
    label = "Telegram"
    description = "Telegram bot message to a chat or group."
    public_fields = ("chat_id",)
    secret_fields = ("bot_token",)

    def is_configured(self, public: dict[str, Any], secrets: dict[str, Any]) -> bool:
        return bool(secrets.get("bot_token") and public.get("chat_id"))

    async def send(self, message: PushMessage, public: dict[str, Any], secrets: dict[str, Any]) -> None:
        text = f"*{message.title}*\n\n{message.body}"
        if message.click_url:
            text += f"\n\n[{message.click_label}]({message.click_url})"
        params = {
            "chat_id": public["chat_id"],
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        url = f"https://api.telegram.org/bot{secrets['bot_token']}/sendMessage"
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(url, json=params)
            resp.raise_for_status()


class EmailProvider(PushProvider):
    name = "email"
    label = "Email"
    description = "SMTP email. Configure host and recipients; password stays encrypted."
    public_fields = ("host", "port", "user", "from_address", "to_address")
    secret_fields = ("password",)

    def is_configured(self, public: dict[str, Any], secrets: dict[str, Any]) -> bool:
        return bool(public.get("host") and public.get("to_address"))

    async def send(self, message: PushMessage, public: dict[str, Any], secrets: dict[str, Any]) -> None:
        import asyncio

        await asyncio.to_thread(self._send_sync, message, public, secrets)

    def _send_sync(self, message: PushMessage, public: dict[str, Any], secrets: dict[str, Any]) -> None:
        msg = EmailMessage()
        msg["Subject"] = message.title
        msg["From"] = public.get("from_address") or "farmos@localhost"
        msg["To"] = public["to_address"]
        body = message.body
        if message.click_url:
            body += f"\n\n{message.click_label}: {message.click_url}"
        msg.set_content(body)
        host = public["host"]
        port = int(public.get("port") or 587)
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.starttls()
            if public.get("user"):
                smtp.login(public["user"], secrets.get("password") or "")
            smtp.send_message(msg)


class SmsProvider(PushProvider):
    name = "sms"
    label = "SMS (Twilio)"
    description = "SMS via Twilio. Add more SMS gateways later as extra adapters."
    public_fields = ("from_number", "to_number")
    secret_fields = ("account_sid", "auth_token")

    def is_configured(self, public: dict[str, Any], secrets: dict[str, Any]) -> bool:
        return bool(
            secrets.get("account_sid")
            and secrets.get("auth_token")
            and public.get("from_number")
            and public.get("to_number")
        )

    async def send(self, message: PushMessage, public: dict[str, Any], secrets: dict[str, Any]) -> None:
        sid = secrets["account_sid"]
        url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
        text = f"{message.title}\n{message.body}"
        if message.click_url:
            text += f"\n{message.click_url}"
        data = {"From": public["from_number"], "To": public["to_number"], "Body": text[:1500]}
        async with httpx.AsyncClient(timeout=12.0, auth=(sid, secrets["auth_token"])) as client:
            resp = await client.post(url, data=data)
            resp.raise_for_status()


class WebhookPushProvider(PushProvider):
    name = "webhook"
    label = "Webhook"
    description = "Generic JSON POST for custom bridges (Home Assistant, n8n, Slack, etc.)."
    public_fields = ()
    secret_fields = ("url",)

    def is_configured(self, public: dict[str, Any], secrets: dict[str, Any]) -> bool:
        return bool(secrets.get("url"))

    async def send(self, message: PushMessage, public: dict[str, Any], secrets: dict[str, Any]) -> None:
        payload = {
            "title": message.title,
            "body": message.body,
            "event": message.event,
            "severity": message.severity,
            "click_url": message.click_url,
            "extra": message.extra,
        }
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(secrets["url"], json=payload)
            resp.raise_for_status()


PROVIDERS: dict[str, PushProvider] = {
    p.name: p
    for p in (
        NtfyProvider(),
        PushoverProvider(),
        DiscordProvider(),
        TelegramProvider(),
        EmailProvider(),
        SmsProvider(),
        WebhookPushProvider(),
    )
}


def register_push_provider(provider: PushProvider) -> None:
    PROVIDERS[provider.name] = provider
