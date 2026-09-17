from __future__ import annotations

import json
from fastapi import APIRouter, Depends, HTTPException

from app.config import get_settings
from app.deps import require_roles
from app.models import User, UserRole
from app.services.update_control import control_dir

router = APIRouter(prefix="/system", tags=["system"])


def _status_payload() -> dict:
    settings = get_settings()
    folder = control_dir()
    available = True
    status = {
        "available": available,
        "status": "unavailable",
        "message": (
            "Print FarmOS will start the updater when you press the button. "
            "The database and uploaded G-code are kept."
        ),
        "app_version": settings.app_version or "dev",
        "log_tail": "",
    }
    raw = folder / "status.json"
    if raw.exists():
        try:
            data = json.loads(raw.read_text(encoding="utf-8"))
            status["status"] = str(data.get("status") or "idle")
            status["message"] = str(data.get("message") or "")
        except (json.JSONDecodeError, OSError):
            pass
    log = folder / "log.txt"
    if log.exists():
        try:
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
            status["log_tail"] = "\n".join(lines[-20:])
        except OSError:
            pass
    if available and status["status"] == "unavailable":
        status["status"] = "idle"
        status["message"] = "Ready to update Print FarmOS from git and rebuild containers."
    elif available and not status["message"]:
        status["message"] = "Ready to update Print FarmOS."
    return status


@router.get("/update")
async def get_update_status(_: User = Depends(require_roles(UserRole.admin))) -> dict:
    return _status_payload()


@router.post("/update")
async def start_update(_: User = Depends(require_roles(UserRole.admin))) -> dict:
    folder = control_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(
            503,
            {
                "error": "Could not write the update control folder.",
                "how_to_fix": [
                    "On the FarmOS machine run ./install.sh (Windows: .\\install.ps1) so data/update exists.",
                    str(exc),
                ],
            },
        ) from exc
    current = _status_payload()
    if current.get("status") == "updating":
        raise HTTPException(409, {"error": "An update is already running.", "how_to_fix": []})
    (folder / "request").write_text("requested\n", encoding="ascii")
    return {
        "ok": True,
        "available": True,
        "status": "updating",
        "message": "Update started. The site may go offline for a few minutes while containers rebuild.",
        "app_version": get_settings().app_version or "dev",
        "log_tail": current.get("log_tail") or "",
    }
