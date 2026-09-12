from __future__ import annotations

import re
from dataclasses import dataclass

import httpx
from fastapi import HTTPException

from app.adapters import ADAPTERS
from app.adapters.base import PrinterSnapshot


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

ADAPTER_URL_HINT = {
    "octoprint": "http://PRINTER_IP  (OctoPrint is usually port 80, sometimes 5000)",
    "moonraker": "http://PRINTER_IP:7125",
    "creality": "http://PRINTER_IP:4408  (Creality K1/K2 Moonraker port)",
}


@dataclass
class ConnectionResult:
    ok: bool
    status: str
    error: str | None
    how_to_fix: list[str]
    snapshot: PrinterSnapshot | None = None


def normalize_base_url(url: str | None) -> str | None:
    if not url or not str(url).strip():
        return None
    value = str(url).strip().rstrip("/")
    if not re.match(r"^https?://", value, re.I):
        value = "http://" + value
    return value


def _host_of(url: str) -> str:
    match = re.match(r"^https?://([^/:]+)", url, re.I)
    return (match.group(1) if match else "").lower()


def _fixes_for(adapter: str, url: str | None, raw_error: str) -> list[str]:
    err = (raw_error or "").lower()
    hint = ADAPTER_URL_HINT.get(adapter, "http://PRINTER_IP")
    fixes: list[str] = []

    if adapter != "simulated" and (not url or _host_of(url) in LOCAL_HOSTS):
        fixes.append(
            "Do not use localhost or 127.0.0.1 — that is the FarmOS server (or Docker container), not the printer. Use the printer’s LAN IP."
        )

    if "refused" in err or "actively refused" in err:
        fixes.append("Connection refused: the printer is off, the IP is wrong, or the port is wrong.")
        fixes.append(f"Typical URL: {hint}")
        fixes.append("From the FarmOS server, ping the printer IP and open the same URL in a browser.")
    elif "timed out" in err or "timeout" in err or "time out" in err:
        fixes.append("Timed out: FarmOS cannot reach that address from the server.")
        fixes.append("Confirm the printer and the FarmOS server are on the same network (or routed to it).")
        fixes.append(f"Check the IP and port. Typical URL: {hint}")
    elif "name or service not known" in err or "nodename nor servname" in err or "failed to resolve" in err or "getaddrinfo" in err:
        fixes.append("The hostname did not resolve. Use the printer’s numeric IP instead of a .local name.")
    elif "certificate" in err or "ssl" in err:
        fixes.append("TLS/SSL failed. Use http:// (not https://). FarmOS does not need printer certificates.")
    elif "409" in err:
        if adapter == "octoprint":
            fixes.append(
                "OctoPrint HTTP 409 is not a certificate problem. It means OctoPrint is running but the printer is not connected (USB unplugged, printer off, or OctoPrint → Connection → Connect)."
            )
            fixes.append("Keep using http://192.168.x.x — do not switch to https or create TLS certificates.")
            fixes.append("Connect the printer in the OctoPrint web UI, then try again.")
        else:
            fixes.append("The printer rejected the request because of its current state (busy or not connected). Try again when it is idle.")
    elif "401" in err or "403" in err or "unauthorized" in err or "forbidden" in err:
        if adapter == "octoprint":
            fixes.append("OctoPrint rejected the API key. In OctoPrint: Settings → API → copy the Application Key (or a user key) into FarmOS.")
            fixes.append("The key must belong to a user allowed to control the printer.")
        elif adapter == "moonraker":
            fixes.append("Moonraker rejected the request. If [authorization] is enabled, paste the API key. Also add the FarmOS server to cors_domains in moonraker.conf.")
        else:
            fixes.append("The printer rejected the login. Check the API key and that the URL includes the right port.")
    elif "404" in err:
        fixes.append("Wrong path or port — the printer answered, but not on that API.")
        fixes.append(f"Try {hint}")
        if adapter == "creality":
            fixes.append("K1/K2: use port 4408, not the Fluidd/Mainsail port.")
    elif url:
        fixes.append(f"Check the URL. Typical format: {hint}")
        fixes.append("The FarmOS server must be able to open that URL — not only your laptop.")
        fixes.append("Disable a printer firewall/VLAN that blocks the FarmOS host.")

    if not fixes:
        fixes.append(f"Check the printer is on, the URL is reachable from this server, and the adapter type matches the firmware. Typical URL: {hint}")

    return fixes


async def probe_adapter(
    adapter_type: str,
    *,
    name: str,
    base_url: str | None,
    api_key: str | None,
    extra: dict | None = None,
) -> ConnectionResult:
    if adapter_type == "simulated":
        return ConnectionResult(ok=True, status="idle", error=None, how_to_fix=[])

    cls = ADAPTERS.get(adapter_type)
    if not cls:
        return ConnectionResult(
            ok=False,
            status="offline",
            error=f"Unknown connection type '{adapter_type}'.",
            how_to_fix=["Choose OctoPrint, Moonraker/Klipper, Creality, or Simulated."],
        )

    url = normalize_base_url(base_url)
    if not url:
        return ConnectionResult(
            ok=False,
            status="offline",
            error="A printer URL is required.",
            how_to_fix=[
                f"Enter the address of the printer on your network. Typical URL: {ADAPTER_URL_HINT.get(adapter_type, 'http://PRINTER_IP')}",
                "Use the printer’s LAN IP, not localhost.",
            ],
        )

    if _host_of(url) in LOCAL_HOSTS:
        return ConnectionResult(
            ok=False,
            status="offline",
            error="localhost points at the FarmOS server, not the printer.",
            how_to_fix=_fixes_for(adapter_type, url, "localhost"),
        )

    adapter = cls(
        printer_id="probe",
        name=name or "probe",
        base_url=url,
        api_key=api_key,
        extra=extra or {},
    )
    try:
        snap = await adapter.get_status()
    except httpx.HTTPError as exc:
        raw = str(exc)
        return ConnectionResult(
            ok=False,
            status="offline",
            error=raw or "Could not reach the printer.",
            how_to_fix=_fixes_for(adapter_type, url, raw),
        )
    except Exception as exc:
        raw = str(exc)
        return ConnectionResult(
            ok=False,
            status="offline",
            error=raw or "Could not reach the printer.",
            how_to_fix=_fixes_for(adapter_type, url, raw),
        )

    host_ok = bool((snap.extra or {}).get("control_host_ok"))
    if snap.online or host_ok:
        return ConnectionResult(
            ok=True,
            status=snap.status or "idle",
            error=None,
            how_to_fix=[],
            snapshot=snap,
        )

    raw = snap.error or "Printer did not respond."
    return ConnectionResult(
        ok=False,
        status="offline",
        error=raw,
        how_to_fix=_fixes_for(adapter_type, url, raw),
        snapshot=snap,
    )


def raise_if_offline(result: ConnectionResult) -> None:
    if result.ok:
        return
    raise HTTPException(
        status_code=400,
        detail={
            "error": result.error or "Could not verify printer connection.",
            "how_to_fix": result.how_to_fix,
        },
    )
