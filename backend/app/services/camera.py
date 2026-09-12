from __future__ import annotations

import logging
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import build_adapter
from app.config import get_settings
from app.models import Printer
from app.security import decrypt_secret

logger = logging.getLogger("farmos.camera")


async def fetch_snapshot(printer: Printer) -> tuple[bytes | None, str]:
    """Fetch a snapshot server-side. Never return camera credentials to the client."""
    url = (printer.camera_snapshot_url or "").strip()
    headers: dict[str, str] = {}
    if printer.camera_auth_encrypted:
        token = decrypt_secret(printer.camera_auth_encrypted)
        if token:
            if token.lower().startswith("basic "):
                headers["Authorization"] = token
            else:
                headers["Authorization"] = f"Bearer {token}"
    if not url and printer.adapter_type.value == "octoprint" and printer.base_url:
        url = printer.base_url.rstrip("/") + "/webcam/?action=snapshot"
        if printer.api_key_encrypted:
            key = decrypt_secret(printer.api_key_encrypted)
            if key:
                headers["X-Api-Key"] = key
    if not url and printer.adapter_type.value in {"moonraker", "creality"} and printer.base_url:
        url = printer.base_url.rstrip("/") + "/webcam/?action=snapshot"
    if not url:
        return None, "offline"
    try:
        async with httpx.AsyncClient(timeout=6.0, follow_redirects=True, verify=False) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code >= 400 or not resp.content:
            return None, "offline"
        dest = get_settings().snapshots_dir / f"{printer.id}.jpg"
        dest.write_bytes(resp.content)
        return resp.content, "online"
    except Exception:
        logger.debug("camera snapshot failed for %s", printer.name, exc_info=True)
        return None, "offline"


def latest_snapshot_path(printer: Printer) -> Path | None:
    path = get_settings().snapshots_dir / f"{printer.id}.jpg"
    return path if path.is_file() else None


def camera_public(printer: Printer) -> dict:
    has_url = bool((printer.camera_snapshot_url or "").strip() or printer.adapter_type.value != "simulated")
    latest = latest_snapshot_path(printer)
    return {
        "configured": bool((printer.camera_snapshot_url or "").strip())
        or printer.adapter_type.value in {"octoprint", "moonraker", "creality"},
        "has_stream": bool((printer.camera_stream_url or "").strip()),
        "snapshot_available": latest is not None,
        "proxy_url": f"/api/v1/printers/{printer.id}/camera",
        "status": "online" if latest else ("configured" if has_url else "offline"),
    }
