"""HTTP client for shop-floor printers.

LAN firmware (OctoPrint, Moonraker) almost never has a public certificate.
FarmOS talks to them over http:// and does not verify TLS, so you do not need
to generate certs on the printer.
"""

from __future__ import annotations

import httpx


def lan_client(timeout: float, headers: dict[str, str] | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=timeout,
        headers=headers or {},
        verify=False,
        follow_redirects=True,
        trust_env=False,
    )
