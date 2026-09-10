from __future__ import annotations

from typing import Any
from uuid import UUID

from app.adapters.base import PrinterAdapter
from app.adapters.creality import CrealityAdapter
from app.adapters.moonraker import MoonrakerAdapter
from app.adapters.octoprint import OctoPrintAdapter
from app.adapters.simulated import SimulatedAdapter
from app.models import Printer
from app.security import decrypt_secret

ADAPTERS: dict[str, type[PrinterAdapter]] = {
    "octoprint": OctoPrintAdapter,
    "moonraker": MoonrakerAdapter,
    "creality": CrealityAdapter,
    "simulated": SimulatedAdapter,
}


def register_adapter(name: str, cls: type[PrinterAdapter]) -> None:
    ADAPTERS[name] = cls


def build_adapter(printer: Printer) -> PrinterAdapter:
    cls = ADAPTERS.get(printer.adapter_type.value)
    if not cls:
        raise ValueError(f"Unknown printer adapter: {printer.adapter_type}")
    extra: dict[str, Any] = dict(printer.extra_config or {})
    return cls(
        printer_id=str(printer.id),
        name=printer.name,
        base_url=printer.base_url,
        api_key=decrypt_secret(printer.api_key_encrypted),
        extra=extra,
    )


def adapter_names() -> list[str]:
    return sorted(ADAPTERS.keys())
