"""Invoke PrusaSlicer CLI with an argv list. Never interpolate user strings into a shell."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from app.config import get_settings


class SlicerCliError(RuntimeError):
    pass


def resolve_slicer_bin(explicit: str | None = None) -> str | None:
    settings = get_settings()
    candidates = [
        explicit,
        settings.slicer_bin,
        os.environ.get("SLICER_BIN"),
        "prusa-slicer",
        "prusa-slicer-console",
        "/usr/bin/prusa-slicer",
        "/opt/PrusaSlicer/prusa-slicer",
        "/squashfs-root/usr/bin/prusa-slicer",
    ]
    for raw in candidates:
        if not raw:
            continue
        path = Path(raw)
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
        found = shutil.which(raw)
        if found:
            return found
    return None


def slicer_argv(
    binary: str,
    ini_path: Path,
    stl_path: Path,
    output_path: Path,
) -> list[str]:
    return [
        binary,
        "--load",
        str(ini_path),
        "--export-gcode",
        "--output",
        str(output_path),
        "--",
        str(stl_path),
    ]


def run_prusa_slicer(
    ini_path: Path,
    stl_path: Path,
    output_path: Path,
    *,
    binary: str | None = None,
    timeout: int | None = None,
) -> Path:
    settings = get_settings()
    exe = resolve_slicer_bin(binary)
    if not exe:
        raise SlicerCliError(
            "PrusaSlicer CLI is not installed on this host. Run the slicer-worker "
            "Docker service (it installs PrusaSlicer) or set SLICER_BIN."
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    argv = slicer_argv(exe, ini_path, stl_path, output_path)
    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout or settings.slicer_timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise SlicerCliError("PrusaSlicer timed out while slicing this plate.") from exc
    except OSError as exc:
        raise SlicerCliError(f"Could not start PrusaSlicer: {exc}") from exc
    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "").strip()
        raise SlicerCliError(err or f"PrusaSlicer exited with code {completed.returncode}")
    produced = output_path
    if not produced.is_file():
        # PrusaSlicer may write <stem>.gcode next to --output when output is a directory.
        sibling = output_path.with_suffix(".gcode")
        if sibling.is_file():
            produced = sibling
        else:
            matches = list(output_path.parent.glob("*.gcode"))
            if len(matches) == 1:
                produced = matches[0]
    if not produced.is_file():
        raise SlicerCliError("PrusaSlicer finished but did not write a G-code file.")
    return produced
