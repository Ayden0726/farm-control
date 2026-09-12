/** USB / Bluetooth scanners that emulate a keyboard (HID wedge). */

export const HID_SCAN_GAP_MS = 80;
export const HID_SCAN_MIN_LEN = 4;

/** Printer labels are sanitized names (PRN-X1C-01), not hex tokens. */
const PRINTER_LABEL = /^(PRINTER|PRN)[-:][A-Z0-9]/i;
/** Prefixes whose payload should look like a uuid/hex token, not a supplier SKU. */
const HEX_PREFIX = /^(SPOOL|FILT|BIN|PBIN|ORDER|BATCH|KIT|HW|JOB)[-:](.+)$/i;
const HEX_TOKEN = /^[0-9a-f]{8,}$/i;

export function looksLikeFarmCode(raw: string): boolean {
  const text = (raw || "").trim();
  if (text.length < HID_SCAN_MIN_LEN) return false;
  const lower = text.toLowerCase();
  if (lower.includes("/scan/")) return true;
  if (lower.startsWith("farmos:")) return true;
  if (PRINTER_LABEL.test(text)) return true;
  const match = HEX_PREFIX.exec(text);
  if (!match) return false;
  const token = match[2].replace(/-/g, "");
  return HEX_TOKEN.test(token);
}

export function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  return target.isContentEditable;
}

export function isScanCaptureField(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.getAttribute("data-farmos-scan") === "1";
}
