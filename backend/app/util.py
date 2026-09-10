import logging
import re
import secrets
from pathlib import Path

logger = logging.getLogger("farmos")


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def new_qr_token() -> str:
    return secrets.token_urlsafe(12).replace("-", "").replace("_", "")[:16].lower()


def parse_quantity_from_filename(filename: str) -> int:
    """Recognise patterns like RK-FR5-Handle-x4.gcode or RK-FR5-Handle_x4.gcode."""
    stem = Path(filename).stem
    match = re.search(r"[_-]x(\d+)$", stem, re.IGNORECASE)
    if match:
        return max(1, int(match.group(1)))
    match = re.search(r"x(\d+)$", stem, re.IGNORECASE)
    if match:
        return max(1, int(match.group(1)))
    return 1


def parse_gcode_metadata(content: str) -> dict[str, float | int]:
    """Extract slicer comments for time and filament usage."""
    result: dict[str, float | int] = {}
    time_match = re.search(r";\s*TIME:\s*(\d+)", content, re.IGNORECASE)
    if time_match:
        result["estimated_time_seconds"] = int(time_match.group(1))
    time_hms = re.search(
        r";\s*estimated printing time.*=\s*(?:(\d+)h\s*)?(?:(\d+)m\s*)?(?:(\d+)s)?",
        content,
        re.IGNORECASE,
    )
    if time_hms and "estimated_time_seconds" not in result:
        h, m, s = (int(x) if x else 0 for x in time_hms.groups())
        result["estimated_time_seconds"] = h * 3600 + m * 60 + s
    gram_match = re.search(r";\s*filament used \[g\]\s*=\s*([\d.]+)", content, re.IGNORECASE)
    if gram_match:
        result["estimated_filament_grams"] = float(gram_match.group(1))
    else:
        meter_match = re.search(
            r";\s*filament used(?: \[mm\])?\s*=\s*([\d.]+)", content, re.IGNORECASE
        )
        if meter_match:
            mm = float(meter_match.group(1))
            # 1.75mm PETG ~ 0.0033 g/mm as a rough farm estimate
            result["estimated_filament_grams"] = round(mm * 0.0033, 2)
        else:
            used = re.search(r";\s*Filament used:\s*([\d.]+)\s*m", content, re.IGNORECASE)
            if used:
                result["estimated_filament_grams"] = round(float(used.group(1)) * 3.3, 2)
    return result


def jobs_needed(required_qty: int, quantity_per_file: int) -> int:
    per = max(1, quantity_per_file)
    return (required_qty + per - 1) // per
