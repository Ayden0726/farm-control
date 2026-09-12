"""Creality K1 Max / K2 Pro adapter.

These machines typically expose a Moonraker-compatible API (often on port 4408).
The adapter prefers Moonraker, then falls back to Creality local HTTP endpoints.
"""

from __future__ import annotations

from pathlib import Path

from app.adapters.base import PrinterSnapshot
from app.adapters.http import lan_client
from app.adapters.moonraker import MoonrakerAdapter


class CrealityAdapter(MoonrakerAdapter):
    async def get_status(self) -> PrinterSnapshot:
        snapshot = await super().get_status()
        if snapshot.online:
            return snapshot
        if not self.base_url:
            return PrinterSnapshot(online=False, status="offline", error="No Creality URL configured")
        try:
            async with lan_client(6.0) as client:
                info = await client.get(f"{self.base_url}/info")
                if info.status_code >= 400:
                    info = await client.post(f"{self.base_url}/protocal.cgi", json={"method": "get_printer_status"})
                data = info.json() if info.status_code < 400 else {}
            status = str(data.get("state") or data.get("status") or "idle").lower()
            mapped = "printing" if "print" in status else "idle" if "idle" in status or "ready" in status else "error"
            return PrinterSnapshot(
                online=True,
                status=mapped,
                nozzle_temp=float(data.get("nozzleTemp") or data.get("nozzle") or 0),
                bed_temp=float(data.get("bedTemp") or data.get("bed") or 0),
                current_file=data.get("filename") or data.get("printFile"),
                progress_percent=float(data.get("progress") or data.get("printProgress") or 0),
                time_remaining_seconds=int(data.get("printRemainTime") or 0),
            )
        except Exception as exc:
            return PrinterSnapshot(online=False, status="offline", error=str(exc) or snapshot.error)

    async def upload_and_start(self, local_path: str, filename: str) -> None:
        try:
            await super().upload_and_start(local_path, filename)
            return
        except Exception:
            path = Path(local_path)
            async with lan_client(60.0) as client:
                with path.open("rb") as handle:
                    resp = await client.post(
                        f"{self.base_url}/upload",
                        files={"file": (filename, handle, "application/octet-stream")},
                    )
                resp.raise_for_status()
