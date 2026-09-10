from __future__ import annotations

from pathlib import Path

import httpx

from app.adapters.base import PrinterAdapter, PrinterSnapshot


class OctoPrintAdapter(PrinterAdapter):
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        return headers

    async def get_status(self) -> PrinterSnapshot:
        if not self.base_url:
            return PrinterSnapshot(online=False, status="offline", error="No OctoPrint URL configured")
        try:
            async with httpx.AsyncClient(timeout=6.0, headers=self._headers()) as client:
                printer = await client.get(f"{self.base_url}/api/printer")
                job = await client.get(f"{self.base_url}/api/job")
            if printer.status_code >= 400:
                return PrinterSnapshot(
                    online=False,
                    status="offline",
                    error=f"OctoPrint HTTP {printer.status_code}",
                )
            pdata = printer.json()
            jdata = job.json() if job.status_code < 400 else {}
            state_text = str(pdata.get("state", {}).get("text", "unknown")).lower()
            flags = pdata.get("state", {}).get("flags", {})
            if flags.get("error"):
                status = "error"
            elif flags.get("printing"):
                status = "paused" if flags.get("paused") else "printing"
            elif flags.get("ready") or "operational" in state_text:
                status = "idle"
            else:
                status = "offline" if flags.get("closedOrError") else "idle"
            temps = pdata.get("temperature", {})
            tool = temps.get("tool0") or {}
            bed = temps.get("bed") or {}
            progress = jdata.get("progress") or {}
            job_info = jdata.get("job") or {}
            file_info = job_info.get("file") or {}
            print_time_left = progress.get("printTimeLeft")
            completion = progress.get("completion") or 0
            return PrinterSnapshot(
                online=True,
                status=status,
                nozzle_temp=float(tool.get("actual") or 0),
                bed_temp=float(bed.get("actual") or 0),
                target_nozzle=float(tool.get("target") or 0),
                target_bed=float(bed.get("target") or 0),
                current_file=file_info.get("name"),
                progress_percent=float(completion or 0),
                time_remaining_seconds=int(print_time_left or 0),
            )
        except Exception as exc:
            return PrinterSnapshot(online=False, status="offline", error=str(exc))

    async def upload_and_start(self, local_path: str, filename: str) -> None:
        headers = {}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        path = Path(local_path)
        async with httpx.AsyncClient(timeout=60.0, headers=headers) as client:
            with path.open("rb") as handle:
                files = {"file": (filename, handle, "application/octet-stream")}
                resp = await client.post(
                    f"{self.base_url}/api/files/local",
                    files=files,
                    data={"select": "true", "print": "true"},
                )
            resp.raise_for_status()

    async def pause(self) -> None:
        await self._job_command({"command": "pause", "action": "pause"})

    async def resume(self) -> None:
        await self._job_command({"command": "pause", "action": "resume"})

    async def cancel(self) -> None:
        await self._job_command({"command": "cancel"})

    async def _job_command(self, payload: dict) -> None:
        async with httpx.AsyncClient(timeout=8.0, headers=self._headers()) as client:
            resp = await client.post(f"{self.base_url}/api/job", json=payload)
            resp.raise_for_status()
