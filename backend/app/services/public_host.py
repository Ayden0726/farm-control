"""Normalize the Settings public domain into a FarmOS host (farm.example.com)."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlparse

LABEL_RE = re.compile(r"^(?:xn--)?[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$", re.I)
LOCAL_HOSTS = {"localhost", "localhost."}


@dataclass(frozen=True)
class PublicHost:
    raw: str
    host: str = ""
    origin: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


EMPTY = PublicHost(raw="", host="", origin="")

_JUNK = "That doesn’t look like a domain or IP. Try example.com, farm.example.com, or a LAN address."


def normalize_public_host(raw: str | None) -> PublicHost:
    """Turn operator input into a public FarmOS origin, or an empty result if unset.

    Blank → no public host (local QR payloads stay farmos:kind:token).
    example.com → https://farm.example.com
    farm.example.com / https://farm.example.com/path → do not double-prefix.
    www.example.com → farm.example.com unless farm. was already present.
    localhost and IPs stay as typed (no farm. prefix).
    """
    text = (raw or "").strip()
    if not text:
        return EMPTY
    if any(ch.isspace() for ch in text):
        return PublicHost(raw=text, host="", origin="", error="Domain cannot contain spaces. Use example.com or farm.example.com.")
    if any(ch in text for ch in ("\\", "<", ">", '"', "'", "`", "@")):
        return PublicHost(raw=text, host="", origin="", error=_JUNK)
    try:
        scheme_in, host_in, port_in = _parse_input(text)
    except ValueError as exc:
        return PublicHost(raw=text, host="", origin="", error=str(exc) or _JUNK)

    host_in = (host_in or "").rstrip(".").lower()
    if not host_in:
        return PublicHost(raw=text, host="", origin="", error=_JUNK)
    if len(host_in) > 253:
        return PublicHost(raw=text, host="", origin="", error="That hostname is too long.")

    local = _is_local_or_ip(host_in)
    if not local:
        try:
            host_in = host_in.encode("idna").decode("ascii")
        except UnicodeError:
            return PublicHost(raw=text, host="", origin="", error=_JUNK)
        err = _validate_hostname(host_in)
        if err:
            return PublicHost(raw=text, host="", origin="", error=err)

    host = host_in if local else _apply_farm_prefix(host_in)
    if not local:
        err = _validate_hostname(host)
        if err:
            return PublicHost(raw=text, host="", origin="", error=err)

    if not local:
        scheme = "https"
    elif scheme_in == "https":
        scheme = "https"
    else:
        scheme = "http"

    origin = f"{scheme}://{_hostport(host, port_in, scheme)}"
    return PublicHost(raw=text, host=_hostport(host, port_in, scheme), origin=origin)


def public_origin_or_empty(raw: str | None) -> str:
    result = normalize_public_host(raw)
    if not result.ok:
        raise ValueError(result.error)
    return result.origin


def _parse_input(text: str) -> tuple[str, str, int | None]:
    if "://" in text:
        parsed = urlparse(text)
        scheme = (parsed.scheme or "").lower()
        if scheme not in {"http", "https"}:
            raise ValueError("Use http:// or https://, or enter a domain with no scheme.")
    else:
        body = text.lstrip("/")
        if _bare_ipv6(body):
            body = f"[{body}]"
        parsed = urlparse(f"//{body}")
        scheme = ""
    if parsed.username or parsed.password:
        raise ValueError(_JUNK)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("That port number is not valid.") from exc
    host = parsed.hostname
    if not host:
        raise ValueError(_JUNK)
    return scheme, host, port


def _bare_ipv6(text: str) -> bool:
    head = text.split("/")[0]
    if head.startswith("["):
        return False
    candidate = head.split("%")[0]
    try:
        ipaddress.IPv6Address(candidate)
        return True
    except ValueError:
        return False


def _is_local_or_ip(host: str) -> bool:
    if host in LOCAL_HOSTS or host.endswith(".localhost"):
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _apply_farm_prefix(host: str) -> str:
    labels = [p for p in host.split(".") if p]
    if not labels:
        return host
    if labels[0] == "www" and len(labels) > 1:
        labels = labels[1:]
        host = ".".join(labels)
    if labels[0] == "farm":
        return host
    if "." not in host:
        # Single-label LAN names stay as-is — do not invent farm.localhost-style hosts.
        return host
    return "farm." + host


def _validate_hostname(host: str) -> str:
    labels = host.split(".")
    if any(not label for label in labels):
        return "That domain has an empty label (check the dots)."
    if any(not LABEL_RE.match(label) for label in labels):
        return _JUNK
    return ""


def _hostport(host: str, port: int | None, scheme: str) -> str:
    try:
        ip = ipaddress.ip_address(host)
        display = f"[{host}]" if ip.version == 6 else host
    except ValueError:
        display = host
    default = 443 if scheme == "https" else 80
    if port and port != default:
        return f"{display}:{port}"
    return display
