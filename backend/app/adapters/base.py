from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PrinterSnapshot:
    online: bool
    status: str
    nozzle_temp: float = 0
    bed_temp: float = 0
    target_nozzle: float = 0
    target_bed: float = 0
    current_file: str | None = None
    progress_percent: float = 0
    time_remaining_seconds: int = 0
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class PrinterAdapter(ABC):
    """Hardware-facing printer driver. New printer types implement this class."""

    def __init__(self, printer_id: str, name: str, base_url: str | None, api_key: str | None, extra: dict[str, Any]):
        self.printer_id = printer_id
        self.name = name
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.extra = extra or {}

    @abstractmethod
    async def get_status(self) -> PrinterSnapshot: ...

    @abstractmethod
    async def upload_and_start(self, local_path: str, filename: str) -> None: ...

    @abstractmethod
    async def pause(self) -> None: ...

    @abstractmethod
    async def resume(self) -> None: ...

    @abstractmethod
    async def cancel(self) -> None: ...
