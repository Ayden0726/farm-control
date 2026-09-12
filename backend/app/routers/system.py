from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from app.config import get_settings
from app.deps import require_roles
from app.models import User, UserRole

router = APIRouter(prefix="/system", tags=["system"])


def _heartbeat_fresh(folder: Path, max_age: int = 20) -> bool:
    beat = folder / "heartbeat"
    if not beat.exists():
        return False
    try:
        stamp = int(beat.read_text().strip() or "0")
    except ValueError:
        return False
    return abs(time.time() - stamp) <= max_age


def _status_payload() -> dict:
    settings = get_settings()
    folder = Path(settings.update_control_dir)
    available = folder.exists() and _heartbeat_fresh(folder)
    status = {
        "available": available,
        "status": "unavailable",
        "message": (
            "One-click update is not running on this server yet. SSH in and run ./update.sh once — "
            "after that, this button will work."
        ),
        "app_version": settings.app_version or "dev",
        "log_tail": "",
    }
    if not folder.exists():
        return status
    raw = folder / "status.json"
    if raw.exists():
        try:
            data = json.loads(raw.read_text())
            status["status"] = str(data.get("status") or "idle")
            status["message"] = str(data.get("message") or "")
        except json.JSONDecodeError:
            pass
    log = folder / "log.txt"
    if log.exists():
        lines = log.read_text(errors="replace").splitlines()
        status["log_tail"] = "\n".join(lines[-12:])
    if available and status["status"] == "unavailable":
        status["status"] = "idle"
        status["message"] = "Ready to update Print FarmOS."
    elif available and not status["message"]:
        status["message"] = "Ready to update Print FarmOS."
    if not available:
        status["status"] = "unavailable"
    return status


@router.get("/update")
async def get_update_status(_: User = Depends(require_roles(UserRole.admin))) -> dict:
    return _status_payload()


@router.post("/update")
async def start_update(_: User = Depends(require_roles(UserRole.admin))) -> dict:
    folder = Path(get_settings().update_control_dir)
    if not folder.exists() or not _heartbeat_fresh(folder):
        raise HTTPException(
            503,
            {
                "error": "One-click update is not running on this server.",
                "how_to_fix": [
                    "SSH into the FarmOS machine, open the farm-control folder, and run ./update.sh (Windows: .\\update.ps1).",
                    "That starts the updater. After it finishes, return here and use Update Print FarmOS.",
                ],
            },
        )
    current = _status_payload()
    if current.get("status") == "updating":
        raise HTTPException(409, {"error": "An update is already running.", "how_to_fix": []})
    (folder / "request").write_text("requested\n")
    return {
        "ok": True,
        "status": "updating",
        "message": "Update started. The site may go offline for a few minutes while containers rebuild.",
        "app_version": get_settings().app_version or "dev",
    }
