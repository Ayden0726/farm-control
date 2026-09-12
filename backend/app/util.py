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


# Same outer bounds as filename time/grams tokens. "." is a bound only when it
# is not a decimal point (so 0.4mm / 0.4pcs are not quantities, but x8-4pcs is).
_QTY_BOUND = r"[\s._\-()]"
_QTY_BOUND_START = r"[\s_\-()]"
# Longer unit names first so "pieces" is not parsed as "pc" + leftover text.
_QTY_PCS_UNITS = r"pieces|piece|pcs|pc"
_QTY_PCS_IN_NAME = re.compile(
    rf"(?:^|{_QTY_BOUND_START}|(?<!\d)\.)(\d+)\s*[\-_]?\s*(?:{_QTY_PCS_UNITS})(?=$|{_QTY_BOUND})",
    re.IGNORECASE,
)
_QTY_X_IN_NAME = re.compile(r"(?:^|[\s._-])x(\d+)(?=$|[\s._-])", re.IGNORECASE)


def _cap_filename_qty(n: int) -> int:
    return max(1, min(n, 999))


def parse_quantity_from_filename(filename: str) -> int:
    """How many of one part this plate prints.

    Prefers <number>pcs (Handle-4pcs.gcode, 4 pcs, 8-pcs, 4_pcs, (4pcs),
    4piece/4pieces/4pc). Falls back to x<number> (RK-FR5-Handle-x4.gcode).
    If both appear, pcs wins. Bounded so K1Max2 and 0.4mm are not quantities.
    """
    stem = Path(filename).stem
    pcs = list(_QTY_PCS_IN_NAME.finditer(stem))
    if pcs:
        return _cap_filename_qty(int(pcs[-1].group(1)))
    xs = list(_QTY_X_IN_NAME.finditer(stem))
    if not xs:
        return 1
    return _cap_filename_qty(int(xs[-1].group(1)))


def parse_time_from_filename(filename: str) -> int | None:
    """Print duration from a G-code file name, e.g. Handle-2h15m.gcode.

    Returns seconds, or None if the stem has no bounded duration token.
    """
    from app.services.gcode_meta import parse_time_from_filename as _parse

    return _parse(filename)


def parse_filament_grams_from_filename(filename: str) -> float | None:
    """Filament grams from a G-code file name, e.g. Handle-48g.gcode.

    Returns grams, or None if the stem has no bounded gram token.
    """
    from app.services.gcode_meta import parse_filament_grams_from_filename as _parse

    return _parse(filename)


def parse_gcode_metadata(content: str) -> dict[str, float | int]:
    """Extract slicer comments for time and filament usage."""
    from app.services.gcode_meta import parse_gcode_metadata as _parse

    return _parse(content)


def jobs_needed(required_qty: int, quantity_per_file: int) -> int:
    per = max(1, quantity_per_file)
    return (required_qty + per - 1) // per
