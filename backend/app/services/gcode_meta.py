from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

# Slicer stats for Prusa/Orca/Bambu live in the footer; Cura writes them in the header.
# Thumbnails can occupy hundreds of KB in the middle of the header, so read both ends.
_END_BYTES = 512_000

_DENSITY_G_CM3 = {
    "pla": 1.24,
    "pla+": 1.24,
    "petg": 1.27,
    "abs": 1.04,
    "asa": 1.07,
    "tpu": 1.21,
    "tpe": 1.20,
    "nylon": 1.14,
    "pa": 1.14,
    "pc": 1.20,
    "hips": 1.04,
    "pva": 1.23,
    "pp": 0.90,
    "pet": 1.27,
    "pctg": 1.23,
}

# Longer unit names must come first so "hours" is not parsed as "h" + leftover text.
# Allow compact tokens like 2h15m (no word boundary between h and 15).
_DURATION_UNITS = r"days?|d|hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s"
_DURATION_PART = re.compile(
    rf"(\d+(?:\.\d+)?)\s*({_DURATION_UNITS})(?![A-Za-z])",
    re.IGNORECASE,
)
_CLOCK = re.compile(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b")
_NUMS = re.compile(r"[\d.]+")
_UNIT_SECONDS = {
    "d": 86400,
    "day": 86400,
    "days": 86400,
    "h": 3600,
    "hr": 3600,
    "hrs": 3600,
    "hour": 3600,
    "hours": 3600,
    "m": 60,
    "min": 60,
    "mins": 60,
    "minute": 60,
    "minutes": 60,
    "s": 1,
    "sec": 1,
    "secs": 1,
    "second": 1,
    "seconds": 1,
}
_MAX_DURATION_SECONDS = 7 * 86400
_MIN_FILENAME_GRAMS = 0.01
_MAX_FILENAME_GRAMS = 100_000
_FILENAME_BOUND = r"[\s._\-()]"
_FILENAME_TIME_TOKEN = re.compile(
    rf"(?:^|{_FILENAME_BOUND})("
    rf"(?:\d+(?:\.\d+)?\s*(?:{_DURATION_UNITS})(?:[\s._-]*\d+(?:\.\d+)?\s*(?:{_DURATION_UNITS}))*)"
    rf"|(?:\d+\s*(?:hours?|hrs?|h)[\s._-]*\d{{2}}(?!\s*(?:{_DURATION_UNITS})))"
    rf"|(?:\d{{1,2}}:\d{{2}}(?::\d{{2}})?)"
    rf")(?=$|{_FILENAME_BOUND})",
    re.IGNORECASE,
)
# Longer unit names first so "grams" is not parsed as "g" + leftover text.
# "gr" is allowed when bounded (Handle-48gr.gcode); "green" is not a bound after "gr".
_FILENAME_GRAM_UNITS = r"grams?|gr|g"
_FILENAME_GRAM_TOKEN = re.compile(
    rf"(?:^|{_FILENAME_BOUND})(\d+(?:\.\d+)?)\s*(?:{_FILENAME_GRAM_UNITS})(?=$|{_FILENAME_BOUND})",
    re.IGNORECASE,
)


def read_gcode_scan_bytes(path: Path, end_bytes: int = _END_BYTES) -> bytes:
    with path.open("rb") as fh:
        head = fh.read(end_bytes)
        fh.seek(0, 2)
        size = fh.tell()
        if size <= end_bytes * 2:
            fh.seek(0)
            return fh.read()
        fh.seek(max(0, size - end_bytes))
        tail = fh.read()
    return head + b"\n" + tail


def gcode_text_for_metadata(raw: bytes, end_bytes: int = _END_BYTES) -> str:
    if len(raw) <= end_bytes * 2:
        sample = raw
    else:
        sample = raw[:end_bytes] + b"\n" + raw[-end_bytes:]
    return sample.decode("utf-8", errors="ignore")


def parse_gcode_comments(content: str) -> dict[str, float | int | str]:
    """Pull print time, filament, and a few profile fields from slicer comments."""
    result: dict[str, float | int | str] = {}
    seconds = _best_time_seconds(content)
    if seconds:
        result["estimated_time_seconds"] = seconds
    grams = _best_filament_grams(content)
    if grams is not None and grams > 0:
        result["estimated_filament_grams"] = round(grams, 2)
    slicer = _slicer_name(content)
    if slicer:
        result["slicer"] = slicer
    layer = _first_float(
        content,
        (
            r";\s*layer_height\s*=\s*([\d.]+)",
            r";\s*Layer height:\s*([\d.]+)",
            r";\s*layerHeight\s*=\s*([\d.]+)",
        ),
    )
    if layer:
        result["layer_height_mm"] = layer
    nozzle = _first_float(
        content,
        (
            r";\s*nozzle_diameter\s*=\s*([\d.]+)",
            r";\s*machine_nozzle_size\s*=\s*([\d.]+)",
            r";\s*nozzle diameter\s*=\s*([\d.]+)",
        ),
    )
    if nozzle:
        result["nozzle_mm"] = nozzle
        result["required_nozzle_mm"] = nozzle
    return result


def parse_gcode_metadata(content: str) -> dict[str, float | int]:
    parsed = parse_gcode_comments(content)
    out: dict[str, float | int] = {}
    if "estimated_time_seconds" in parsed:
        out["estimated_time_seconds"] = int(parsed["estimated_time_seconds"])
    if "estimated_filament_grams" in parsed:
        out["estimated_filament_grams"] = float(parsed["estimated_filament_grams"])
    return out


def parse_gcode_file_bytes(raw: bytes) -> dict[str, float | int | str]:
    return parse_gcode_comments(gcode_text_for_metadata(raw))


def parse_gcode_file(path: Path) -> dict[str, float | int | str]:
    return parse_gcode_comments(gcode_text_for_metadata(read_gcode_scan_bytes(path)))


def parse_time_from_filename(filename: str) -> int | None:
    """Print duration encoded in a G-code file name, if any.

    Same units as slicer comment parsing (h/hr/hours, m/min/minutes, s/sec/seconds).
    Bounded like quantity markers: start/end, spaces, dots, underscores, dashes, parentheses.
    """
    stem = Path(filename or "").stem
    if not stem:
        return None
    found: list[int] = []
    for match in _FILENAME_TIME_TOKEN.finditer(stem):
        seconds = _parse_duration(match.group(1))
        if seconds:
            found.append(seconds)
    return found[-1] if found else None


def apply_filename_time_fallback(meta: dict[str, float | int | str], filename: str) -> bool:
    """Use a filename duration when slicer comments did not produce a real estimate."""
    if meta.get("estimated_time_seconds"):
        return False
    seconds = parse_time_from_filename(filename)
    if not seconds:
        return False
    meta["estimated_time_seconds"] = seconds
    return True


def parse_filament_grams_from_filename(filename: str) -> float | None:
    """Filament mass in grams encoded in a G-code file name, if any.

    Bounded like quantity and time markers: start/end, spaces, dots, underscores,
    dashes, parentheses. Units: g, gr, gram, grams.
    """
    stem = Path(filename or "").stem
    if not stem:
        return None
    found: list[float] = []
    for match in _FILENAME_GRAM_TOKEN.finditer(stem):
        grams = _bounded_grams(float(match.group(1)))
        if grams is not None:
            found.append(grams)
    return found[-1] if found else None


def apply_filename_filament_fallback(meta: dict[str, float | int | str], filename: str) -> bool:
    """Use a filename gram amount when slicer comments did not produce a real estimate."""
    if meta.get("estimated_filament_grams"):
        return False
    grams = parse_filament_grams_from_filename(filename)
    if not grams:
        return False
    meta["estimated_filament_grams"] = grams
    return True


def apply_gcode_estimates(gcode: Any, meta: dict[str, float | int | str], *, fill_profile: bool = True) -> bool:
    changed = False
    if "estimated_time_seconds" in meta:
        seconds = max(1, int(meta["estimated_time_seconds"]))
        if gcode.estimated_time_seconds != seconds:
            gcode.estimated_time_seconds = seconds
            changed = True
    if "estimated_filament_grams" in meta:
        grams = max(0.01, float(meta["estimated_filament_grams"]))
        if abs(float(gcode.estimated_filament_grams or 0) - grams) > 0.009:
            gcode.estimated_filament_grams = grams
            changed = True
    if fill_profile:
        for field in ("slicer", "layer_height_mm", "nozzle_mm", "required_nozzle_mm"):
            value = meta.get(field)
            if value in (None, ""):
                continue
            current = getattr(gcode, field, None)
            if current in (None, ""):
                setattr(gcode, field, value)
                changed = True
    return changed


def _best_time_seconds(content: str) -> int | None:
    best: tuple[int, int] | None = None

    def consider(priority: int, seconds: int | None) -> None:
        nonlocal best
        if not seconds or seconds <= 0:
            return
        if best is None or priority > best[0] or (priority == best[0] and seconds > best[1]):
            best = (priority, seconds)

    for match in re.finditer(
        r";\s*total estimated time\s*[:=]\s*([^\n;]+)", content, re.IGNORECASE
    ):
        consider(100, _parse_duration(match.group(1)))
    for match in re.finditer(
        r";\s*estimated printing time\s*\(\s*normal mode\s*\)\s*=\s*([^\n;]+)",
        content,
        re.IGNORECASE,
    ):
        consider(90, _parse_duration(match.group(1)))
    for match in re.finditer(
        r";\s*estimated printing time(?:\s*\([^)]*\))?\s*=\s*([^\n;]+)",
        content,
        re.IGNORECASE,
    ):
        label_start = content.rfind("\n", 0, match.start())
        label = content[label_start + 1 : match.start()].lower()
        if "first layer" in label:
            continue
        if "silent" in label:
            consider(40, _parse_duration(match.group(1)))
            continue
        consider(80, _parse_duration(match.group(1)))
    for match in re.finditer(r";\s*TIME:\s*(\d+)\b", content, re.IGNORECASE):
        consider(70, int(match.group(1)))
    for match in re.finditer(
        r";\s*model printing time\s*[:=]\s*([^\n;]+)", content, re.IGNORECASE
    ):
        consider(60, _parse_duration(match.group(1)))
    for match in re.finditer(
        r";\s*(?:print time|build time)\s*[:=]\s*([^\n;]+)", content, re.IGNORECASE
    ):
        consider(50, _parse_duration(match.group(1)))
    for match in re.finditer(r"^M73\b[^\n]*\bR(\d+)\b", content, re.IGNORECASE | re.MULTILINE):
        consider(20, int(match.group(1)) * 60)
        break
    return best[1] if best else None


def _best_filament_grams(content: str) -> float | None:
    density = _density(content)
    diameter = _diameter_mm(content)
    grams = _sum_after(
        content,
        (
            r";\s*total filament used \[g\]\s*=\s*([^\n;]+)",
            r";\s*total filament weight \[g\]\s*[:=]\s*([^\n;]+)",
            r";\s*filament used \[g\]\s*=\s*([^\n;]+)",
        ),
    )
    if grams:
        return grams
    cm3 = _sum_after(content, (r";\s*filament used \[cm3\]\s*=\s*([^\n;]+)",))
    if cm3:
        return cm3 * density
    mm = _sum_after(
        content,
        (
            r";\s*total filament length \[mm\]\s*[:=]\s*([^\n;]+)",
            r";\s*filament used \[mm\]\s*=\s*([^\n;]+)",
        ),
    )
    if mm:
        return _grams_from_length_mm(mm, diameter, density)
    meters = _cura_filament_meters(content)
    if meters:
        return _grams_from_length_mm(meters * 1000.0, diameter, density)
    meters = _sum_after(
        content,
        (
            r";\s*total filament length \[m\]\s*[:=]\s*([^\n;]+)",
            r";\s*filament used:\s*([^\n;]+)",
        ),
    )
    if meters:
        # Cura-style "12.3m" already handled; a bare number here is meters if small.
        if meters > 500:
            return _grams_from_length_mm(meters, diameter, density)
        return _grams_from_length_mm(meters * 1000.0, diameter, density)
    return None


def _parse_duration(raw: str) -> int | None:
    text = (raw or "").strip()
    if not text:
        return None
    clock = _CLOCK.search(text)
    if clock:
        h = int(clock.group(1))
        m = int(clock.group(2))
        s = int(clock.group(3) or 0)
        if m < 60 and s < 60:
            return _bounded_seconds(h * 3600 + m * 60 + s)
    implied = re.fullmatch(
        rf"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)[\s._-]*(\d{{2}})",
        text,
        re.IGNORECASE,
    )
    if implied:
        minutes = int(implied.group(2))
        if minutes < 60:
            return _bounded_seconds(int(round(float(implied.group(1)) * 3600 + minutes * 60)))
    total = 0.0
    found = False
    for match in _DURATION_PART.finditer(text):
        unit = match.group(2).lower()
        total += float(match.group(1)) * _UNIT_SECONDS[unit]
        found = True
    if not found or total <= 0:
        return None
    return _bounded_seconds(int(round(total)))


def _bounded_seconds(seconds: int) -> int | None:
    if seconds < 1 or seconds > _MAX_DURATION_SECONDS:
        return None
    return seconds


def _bounded_grams(grams: float) -> float | None:
    if grams < _MIN_FILENAME_GRAMS or grams > _MAX_FILENAME_GRAMS:
        return None
    return round(grams, 2)


def _sum_after(content: str, patterns: tuple[str, ...]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, content, re.IGNORECASE)
        if not match:
            continue
        total = _sum_numbers(match.group(1))
        if total is not None:
            return total
    return None


def _sum_numbers(raw: str) -> float | None:
    values = [float(x) for x in _NUMS.findall(raw or "") if x != "."]
    if not values:
        return None
    return sum(values)


def _cura_filament_meters(content: str) -> float | None:
    match = re.search(r";\s*Filament used:\s*([^\n;]+)", content, re.IGNORECASE)
    if not match:
        return None
    total = 0.0
    found = False
    for part in match.group(1).split(","):
        num = re.search(r"([\d.]+)\s*m\b", part, re.IGNORECASE)
        if not num:
            continue
        total += float(num.group(1))
        found = True
    return total if found else None


def _density(content: str) -> float:
    match = re.search(r";\s*filament[_ ]density\s*=\s*([^\n;]+)", content, re.IGNORECASE)
    if match:
        nums = [float(x) for x in _NUMS.findall(match.group(1)) if x != "."]
        nums = [n for n in nums if 0.5 < n < 3.0]
        if nums:
            return sum(nums) / len(nums)
    match = re.search(
        r";\s*filament[_ ](?:type|material)\s*=\s*([A-Za-z0-9+]+)", content, re.IGNORECASE
    )
    if match:
        return _DENSITY_G_CM3.get(match.group(1).lower(), 1.24)
    flavor = re.search(
        r";\s*(?:material|filament_type)\s*[:=]\s*([A-Za-z0-9+]+)", content, re.IGNORECASE
    )
    if flavor:
        return _DENSITY_G_CM3.get(flavor.group(1).lower(), 1.24)
    return 1.24


def _diameter_mm(content: str) -> float:
    listed = _first_float(
        content,
        (
            r";\s*filament[_ ]diameter\s*=\s*([\d.]+)",
            r";\s*Default printing filament diameter\s*=\s*([\d.]+)",
            r";\s*filament_diameter\s*=\s*([\d.]+)",
        ),
    )
    return listed or 1.75


def _grams_from_length_mm(length_mm: float, diameter_mm: float, density: float) -> float:
    radius = max(diameter_mm, 0.1) / 2.0
    volume_cm3 = (math.pi * radius * radius * length_mm) / 1000.0
    return volume_cm3 * density


def _first_float(content: str, patterns: tuple[str, ...]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                continue
    return None


def _slicer_name(content: str) -> str | None:
    match = re.search(
        r";\s*generated by\s+([A-Za-z0-9._+\- ]+?)(?:\s+on\s+|\s*$)",
        content,
        re.IGNORECASE | re.MULTILINE,
    )
    if match:
        return match.group(1).strip()[:80]
    match = re.search(r";\s*Generated with\s+([A-Za-z0-9._+\-]+)", content, re.IGNORECASE)
    if match:
        return match.group(1).strip()[:80]
    return None
