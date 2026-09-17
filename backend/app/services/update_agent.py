"""Background loop so Settings → Update works without a separate host process.

Writes the heartbeat the UI keys off, and runs ./update.sh when the button
drops a request file. Used when FarmOS is started from a git checkout
(local uvicorn or the compose update-agent container).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.services.update_control import control_dir, farm_root, write_heartbeat

logger = logging.getLogger("farmos.update")


def _write_status(folder: Path, status: str, message: str) -> None:
    payload = {
        "status": status,
        "message": message,
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    (folder / "status.json").write_text(json.dumps(payload), encoding="utf-8")


def _run_update_script(root: Path, folder: Path) -> int:
    log_path = folder / "log.txt"
    script = root / "update.sh"
    if os.name == "nt" and (root / "update.ps1").is_file():
        cmd = ["powershell.exe", "-NoProfile", "-File", str(root / "update.ps1")]
    elif script.is_file():
        cmd = ["bash", str(script)]
    else:
        _write_status(folder, "error", "update.sh was not found in the FarmOS folder.")
        return 1
    env = os.environ.copy()
    env["UPDATE_FROM_AGENT"] = "1"
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    return int(proc.returncode)


async def update_agent_loop() -> None:
    folder = control_dir()
    folder.mkdir(parents=True, exist_ok=True)
    root = farm_root()
    lock_file = None
    exclusive = False
    if root is not None:
        try:
            import fcntl

            lock_file = (folder / "agent.lock").open("a+")
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            exclusive = True
        except ImportError:
            exclusive = True
        except OSError:
            exclusive = False
            logger.info("Another update agent holds the lock; this process will only keep a heartbeat")
    _write_status(folder, "idle", "Ready to update Print FarmOS.")
    logger.info("Update agent watching %s (farm root %s exclusive=%s)", folder, root, exclusive)
    while True:
        try:
            write_heartbeat(folder)
            request = folder / "request"
            if request.exists() and exclusive:
                try:
                    request.unlink()
                except OSError:
                    pass
                if root is None:
                    _write_status(
                        folder,
                        "error",
                        "Update was requested but FarmOS could not find update.sh. "
                        "Run ./update.sh on the server once.",
                    )
                else:
                    _write_status(
                        folder,
                        "updating",
                        "Pulling the latest Print FarmOS and rebuilding. This can take several minutes.",
                    )
                    code = await asyncio.to_thread(_run_update_script, root, folder)
                    if code == 0:
                        _write_status(
                            folder,
                            "ok",
                            "Update finished. Hard-refresh the browser if the UI looks old.",
                        )
                    else:
                        _write_status(
                            folder,
                            "error",
                            "Update failed. Check the log below or run ./update.sh in a terminal.",
                        )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("update agent loop error")
        await asyncio.sleep(2)


def maybe_touch_heartbeat() -> None:
    """Keep the button enabled even before the async loop's first tick."""
    try:
        write_heartbeat(control_dir())
    except OSError:
        pass
