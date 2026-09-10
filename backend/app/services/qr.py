from __future__ import annotations

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
    path = settings.qr_dir / f"{kind}-{token}.png"
    if not path.exists():
        qr = segno.make(qr_payload(kind, token, public_base), error="m")
        qr.save(str(path), scale=8, border=2)
    return path
