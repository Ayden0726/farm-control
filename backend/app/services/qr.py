from __future__ import annotations

import hashlib
import re
from pathlib import Path

import segno

from app.config import get_settings


def qr_payload(kind: str, token: str, public_base: str = "") -> str:
    base = public_base.rstrip("/")
    if base:
        return f"{base}/scan/{kind}/{token}"
    return f"farmos:{kind}:{token}"


def render_qr_png(kind: str, token: str, public_base: str = "") -> Path:
    settings = get_settings()
    payload = qr_payload(kind, token, public_base)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
    safe_kind = re.sub(r"[^A-Za-z0-9._-]+", "_", kind)[:40]
    safe_token = re.sub(r"[^A-Za-z0-9._-]+", "_", token)[:80]
    path = settings.qr_dir / f"{safe_kind}-{safe_token}-{digest}.png"
    if not path.exists():
        qr = segno.make(payload, error="m")
        qr.save(str(path), scale=8, border=2)
    return path
