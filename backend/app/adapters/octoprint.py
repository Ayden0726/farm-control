from __future__ import annotations

from pathlib import Path

from app.adapters.base import PrinterAdapter, PrinterSnapshot
from app.adapters.http import lan_client


class OctoPrintAdapter(PrinterAdapter):
    def _headers(self, *, json_body: bool = False) -> dict[str, str]:
        headers: dict[str, str] = {}
        if json_body:
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        return headers

    async def get_status(self) -> PrinterSnapshot:
        if not self.base_url:
            return PrinterSnapshot(online=False, status="offline", error="No OctoPrint URL configured")
        try:
            async with lan_client(6.0, self._headers()) as client:
                version = await client.get(f"{self.base_url}/api/version")
                if version.status_code in {401, 403}:
                    return PrinterSnapshot(
                        online=False,
                        status="offline",
                        error=f"OctoPrint HTTP {version.status_code}",
                    )
                if version.status_code >= 400:
                    return PrinterSnapshot(
                        online=False,
                        status="offline",
                        error=f"OctoPrint HTTP {version.status_code}",
                    )
                printer = await client.get(f"{self.base_url}/api/printer")
                job = await client.get(f"{self.base_url}/api/job")
            return snapshot_from_octoprint(printer.status_code, _safe_json(printer), _safe_json(job) if job.status_code < 400 else {})
        except Exception as exc:
            return PrinterSnapshot(online=False, status="offline", error=str(exc))

    async def upload_and_start(self, local_path: str, filename: str) -> None:
        path = Path(local_path)
        async with lan_client(60.0, self._headers()) as client:
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
        async with lan_client(8.0, self._headers(json_body=True)) as client:
            resp = await client.post(f"{self.base_url}/api/job", json=payload)
            resp.raise_for_status()


def _safe_json(resp) -> dict:
    try:
        data = resp.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def snapshot_from_octoprint(printer_status: int, pdata: dict, jdata: dict) -> PrinterSnapshot:
    """Map OctoPrint /api/printer (+ optional /api/job) into a snapshot.

    HTTP 409 on /api/printer means OctoPrint itself is up, but the machine is
    not connected (USB unplugged, printer off, or Connection → Connect). That
    is not a TLS/certificate problem.
    """
    if printer_status == 409:
        return PrinterSnapshot(
            online=False,
            status="offline",
            extra={"control_host_ok": True, "printer_disconnected": True},
        )
    if printer_status >= 400:
        return PrinterSnapshot(
            online=False,
            status="offline",
            error=f"OctoPrint HTTP {printer_status}",
            extra={"control_host_ok": printer_status not in {401, 403}},
        )

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
        extra={"control_host_ok": True},
    )
