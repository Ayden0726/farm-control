from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.adapters.base import PrinterAdapter, PrinterSnapshot


class SimulatedAdapter(PrinterAdapter):
    """In-process printer used for development, demos, and farms without live APIs yet."""

    async def get_status(self) -> PrinterSnapshot:
        state: dict[str, Any] = self.extra.get("sim", {})
        now = datetime.now(timezone.utc)
        status = state.get("status", "idle")
        progress = float(state.get("progress_percent") or 0)
        remaining = int(state.get("time_remaining_seconds") or 0)
        nozzle = 28.0
        bed = 24.0
        t_nozzle = 0.0
        t_bed = 0.0
        if status in {"printing", "paused", "waiting_for_bed_clear"}:
            t_nozzle = float(state.get("target_nozzle") or 250)
            t_bed = float(state.get("target_bed") or 80)
            if status == "printing":
                # Ease temperatures toward target
                nozzle = t_nozzle - max(0, 8 - (now.timestamp() % 10))
                bed = t_bed - max(0, 3 - (now.timestamp() % 6) / 2)
            else:
                nozzle = t_nozzle * 0.7
                bed = t_bed * 0.85
        return PrinterSnapshot(
            online=True,
            status=status,
            nozzle_temp=round(nozzle, 1),
            bed_temp=round(bed, 1),
            target_nozzle=t_nozzle,
            target_bed=t_bed,
            current_file=state.get("current_file"),
            progress_percent=progress,
            time_remaining_seconds=remaining,
        )

    async def upload_and_start(self, local_path: str, filename: str) -> None:
        sim = self.extra.setdefault("sim", {})
        sim["status"] = "printing"
        sim["current_file"] = filename
        sim["progress_percent"] = 0
        sim["target_nozzle"] = 250
        sim["target_bed"] = 80

    async def pause(self) -> None:
        sim = self.extra.setdefault("sim", {})
        if sim.get("status") == "printing":
            sim["status"] = "paused"

    async def resume(self) -> None:
        sim = self.extra.setdefault("sim", {})
        if sim.get("status") == "paused":
            sim["status"] = "printing"

    async def cancel(self) -> None:
        sim = self.extra.setdefault("sim", {})
        sim["status"] = "waiting_for_bed_clear"
        sim["progress_percent"] = 0
