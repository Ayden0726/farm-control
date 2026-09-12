"use client";

import { useEffect, useRef } from "react";
import {
  HID_SCAN_GAP_MS,
  HID_SCAN_MIN_LEN,
  isEditableTarget,
  isScanCaptureField,
  looksLikeFarmCode,
} from "@/lib/hid-scanner";

/**
 * Listens for a USB/Bluetooth barcode scanner. Those devices type the code
 * very quickly and send Enter. Slow typing in ordinary fields is ignored.
 */
export function useHidScanner(onScan: (code: string) => void, enabled = true) {
  const onScanRef = useRef(onScan);
  onScanRef.current = onScan;
  const buffer = useRef("");
  const lastKeyAt = useRef(0);
  const lastEmit = useRef({ code: "", at: 0 });

  useEffect(() => {
    if (!enabled || typeof window === "undefined") return;

    function reset() {
      buffer.current = "";
    }

    function emit(code: string) {
      const trimmed = code.trim();
      if (!trimmed) return;
      const now = Date.now();
      if (trimmed === lastEmit.current.code && now - lastEmit.current.at < 1200) return;
      lastEmit.current = { code: trimmed, at: now };
      onScanRef.current(trimmed);
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      const now = Date.now();
      const inScanField = isScanCaptureField(event.target);
      const inField = isEditableTarget(event.target);

      if (event.key === "Enter" || event.key === "Tab") {
        const rapid = buffer.current.length >= HID_SCAN_MIN_LEN && now - lastKeyAt.current <= HID_SCAN_GAP_MS + 50;
        if (rapid) {
          if (inScanField) {
            reset();
            return;
          }
          const code = buffer.current;
          reset();
          if (inField && !looksLikeFarmCode(code)) return;
          event.preventDefault();
          event.stopPropagation();
          emit(code);
          return;
        }
        reset();
        return;
      }

      if (event.key === "Shift") return;
      if (event.key.length !== 1) {
        reset();
        return;
      }

      if (buffer.current && now - lastKeyAt.current > HID_SCAN_GAP_MS) {
        buffer.current = "";
      }
      buffer.current += event.key;
      lastKeyAt.current = now;
    }

    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [enabled]);
}
