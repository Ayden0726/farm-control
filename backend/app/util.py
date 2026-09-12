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


_QTY_IN_NAME = re.compile(r"(?:^|[\s._-])x(\d+)(?=$|[\s._-])", re.IGNORECASE)


def parse_quantity_from_filename(filename: str) -> int:
    """How many of one part this plate prints.

    Reads x<number> in the file name, e.g. RK-FR5-Handle-x4.gcode,
    Handle_x8.gcode, Bracket-x4-PETG.gcode, or x12-plate.gcode.
    """
    stem = Path(filename).stem
    matches = list(_QTY_IN_NAME.finditer(stem))
    if not matches:
        return 1
    n = int(matches[-1].group(1))
    return max(1, min(n, 999))


def parse_time_from_filename(filename: str) -> int | None:
    """Print duration from a G-code file name, e.g. Handle-2h15m.gcode.

    Returns seconds, or None if the stem has no bounded duration token.
    """
    from app.services.gcode_meta import parse_time_from_filename as _parse

    return _parse(filename)


def parse_gcode_metadata(content: str) -> dict[str, float | int]:
    """Extract slicer comments for time and filament usage."""
    from app.services.gcode_meta import parse_gcode_metadata as _parse

    return _parse(content)


def jobs_needed(required_qty: int, quantity_per_file: int) -> int:
    per = max(1, quantity_per_file)
    return (required_qty + per - 1) // per
