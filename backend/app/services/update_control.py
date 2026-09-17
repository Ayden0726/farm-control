"""One-click Settings → Update: shared heartbeat / control-dir helpers."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

_HEARTBEAT_RE = re.compile(rb"(\d{9,12})")


def control_dir() -> Path:
    settings_dir = os.environ.get("UPDATE_CONTROL_DIR", "").strip()
    candidates = []
    if settings_dir:
        candidates.append(Path(settings_dir))
    from app.config import get_settings

    candidates.append(Path(get_settings().update_control_dir))
    candidates.extend(
        [
            Path("/update-control"),
            Path("/workspace/data/update"),
            Path("data/update"),
            Path("/farm/data/update"),
        ]
    )
    for path in candidates:
        try:
            if path.exists() and path.is_dir():
                return path
        except OSError:
            continue
    for path in candidates:
        try:
            path.mkdir(parents=True, exist_ok=True)
            return path
        except OSError:
            continue
    return Path(get_settings().update_control_dir)


def parse_heartbeat(raw: bytes | str | None) -> int | None:
    """Read a unix timestamp from the heartbeat file (ASCII, UTF-8, or UTF-16)."""
    if raw is None:
        return None
    if isinstance(raw, str):
        data = raw.encode("utf-8", errors="ignore")
    else:
        data = raw
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        try:
            text = data.decode("utf-16")
            data = text.encode("utf-8", errors="ignore")
        except UnicodeDecodeError:
            pass
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    match = _HEARTBEAT_RE.search(data)
    if not match:
        digits = re.sub(rb"[^0-9]", b"", data)
        if len(digits) >= 9:
            match = _HEARTBEAT_RE.search(digits)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def heartbeat_fresh(folder: Path, max_age: int = 90) -> bool:
    beat = folder / "heartbeat"
    if not beat.exists():
        return False
    try:
        stamp = parse_heartbeat(beat.read_bytes())
    except OSError:
        return False
    if stamp is None:
        return False
    return abs(time.time() - stamp) <= max_age


def write_heartbeat(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "heartbeat").write_text(f"{int(time.time())}\n", encoding="ascii")


_ENV_KEY_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def set_dotenv_key(path: Path, key: str, value: str) -> None:
    """Create or replace KEY=value in a .env file without touching other lines."""
    if not _ENV_KEY_RE.match(key):
        raise ValueError(f"invalid env key: {key}")
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = text.splitlines()
    found = False
    out: list[str] = []
    prefix = f"{key}="
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith(prefix) and not stripped.startswith("#"):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        if out and out[-1] != "":
            out.append("")
        out.append(f"{key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def apply_dotenv_updates(path: Path, updates: dict[str, str]) -> None:
    for key, value in updates.items():
        set_dotenv_key(path, key, str(value))


def parse_restart_env(text: str) -> dict[str, str]:
    updates: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip().lstrip("\ufeff").replace("\r", "")
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if _ENV_KEY_RE.match(key):
            updates[key] = value.strip()
    return updates


def write_restart_request(*, reason: str = "settings", env: dict[str, str] | None = None) -> Path:
    folder = control_dir()
    folder.mkdir(parents=True, exist_ok=True)
    env = env or {}
    if env:
        lines = [f"{key}={value}" for key, value in env.items() if _ENV_KEY_RE.match(key)]
        (folder / "restart.env").write_text("\n".join(lines) + "\n", encoding="ascii")
    (folder / "restart").write_text(f"{reason}\n", encoding="ascii")
    return folder


def farm_root() -> Path | None:
    env = os.environ.get("FARMOS_ROOT", "").strip()
    candidates = [Path(env)] if env else []
    candidates.extend(
        [
            Path("/farm"),
            Path("/workspace"),
            Path(__file__).resolve().parents[3],
        ]
    )
    seen: set[Path] = set()
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if (resolved / "update.sh").is_file() and (resolved / "docker-compose.yml").is_file():
            return resolved
    return None
