from __future__ import annotations

from pathlib import Path

import httpx

from app.adapters.base import PrinterAdapter, PrinterSnapshot


def _first(*values):
    for value in values:
        if value is not None:
            return value
    return None


class MoonrakerAdapter(PrinterAdapter):
    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def get_status(self) -> PrinterSnapshot:
        if not self.base_url:
            return PrinterSnapshot(online=False, status="offline", error="No Moonraker URL configured")
        query = "print_stats&heater_bed&extruder&display_status&virtual_sdcard"
        try:
            async with httpx.AsyncClient(timeout=6.0, headers=self._headers()) as client:
                resp = await client.get(f"{self.base_url}/printer/objects/query?{query}")
            if resp.status_code >= 400:
                return PrinterSnapshot(online=False, status="offline", error=f"Moonraker HTTP {resp.status_code}")
            status = (resp.json().get("result") or {}).get("status") or {}
            stats = status.get("print_stats") or {}
            extruder = status.get("extruder") or {}
            bed = status.get("heater_bed") or {}
            display = status.get("display_status") or {}
            sd = status.get("virtual_sdcard") or {}
            state = str(stats.get("state") or "standby").lower()
            mapped = {
                "standby": "idle",
                "ready": "idle",
                "printing": "printing",
                "paused": "paused",
                "complete": "idle",
                "cancelled": "idle",
                "error": "error",
            }.get(state, "idle")
            progress = float(_first(display.get("progress"), sd.get("progress"), 0) or 0)
            if progress <= 1:
                progress *= 100
            print_duration = float(stats.get("print_duration") or 0)
            total_duration = float(stats.get("total_duration") or 0)
            remaining = 0
            if progress > 1:
                elapsed = print_duration or total_duration
                remaining = int(max(0, elapsed * (100 - progress) / progress))
            return PrinterSnapshot(
                online=True,
                status=mapped,
                nozzle_temp=float(extruder.get("temperature") or 0),
                bed_temp=float(bed.get("temperature") or 0),
                target_nozzle=float(extruder.get("target") or 0),
                target_bed=float(bed.get("target") or 0),
                current_file=stats.get("filename"),
                progress_percent=progress,
                time_remaining_seconds=remaining,
            )
        except Exception as exc:
            return PrinterSnapshot(online=False, status="offline", error=str(exc))

    async def upload_and_start(self, local_path: str, filename: str) -> None:
        path = Path(local_path)
        async with httpx.AsyncClient(timeout=60.0, headers=self._headers()) as client:
            with path.open("rb") as handle:
                files = {"file": (filename, handle, "application/octet-stream")}
                resp = await client.post(f"{self.base_url}/server/files/upload", files=files)
            resp.raise_for_status()
            start = await client.post(
                f"{self.base_url}/printer/print/start",
                params={"filename": filename},
            )
            start.raise_for_status()

    async def pause(self) -> None:
        await self._post("/printer/print/pause")

    async def resume(self) -> None:
        await self._post("/printer/print/resume")

    async def cancel(self) -> None:
        await self._post("/printer/print/cancel")

    async def _post(self, path: str) -> None:
        async with httpx.AsyncClient(timeout=8.0, headers=self._headers()) as client:
            resp = await client.post(f"{self.base_url}{path}")
            resp.raise_for_status()
