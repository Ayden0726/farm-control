"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

function safeStop(scanner: { stop: () => Promise<void> } | null) {
  if (!scanner) return;
  try {
    const pending = scanner.stop();
    if (pending && typeof pending.catch === "function") {
      pending.catch(() => undefined);
    }
  } catch {
    // html5-qrcode throws a string if the camera never started.
  }
}

export function BarcodeScanner({
  onDetect,
  label = "Point the camera at a FarmOS QR or Code 128 label",
}: {
  onDetect: (code: string) => void;
  label?: string;
}) {
  const uid = useId().replace(/:/g, "");
  const elementId = `farmos-scanner-${uid}`;
  const host = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [manual, setManual] = useState("");
  const [running, setRunning] = useState(false);
  const onDetectRef = useRef(onDetect);
  onDetectRef.current = onDetect;
  const scannerRef = useRef<{ stop: () => Promise<void> } | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function start() {
      if (!host.current) return;
      try {
        const { Html5Qrcode, Html5QrcodeSupportedFormats } = await import("html5-qrcode");
        const scanner = new Html5Qrcode(host.current.id);
        scannerRef.current = scanner;
        const config = {
          fps: 8,
          qrbox: { width: 280, height: 180 },
          formatsToSupport: [Html5QrcodeSupportedFormats.QR_CODE, Html5QrcodeSupportedFormats.CODE_128],
        };
        await scanner.start(
          { facingMode: "environment" },
          config as never,
          (text) => {
            if (text) onDetectRef.current(text);
          },
          () => undefined,
        );
        if (cancelled) {
          safeStop(scanner);
          scannerRef.current = null;
          return;
        }
        setRunning(true);
      } catch (err) {
        scannerRef.current = null;
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Camera unavailable. Enter the code manually.");
        }
      }
    }
    start();
    return () => {
      cancelled = true;
      const scanner = scannerRef.current;
      scannerRef.current = null;
      safeStop(scanner);
    };
  }, []);

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">{label}</p>
      <div id={elementId} ref={host} className="overflow-hidden rounded-xl bg-black min-h-[220px]" />
      {error && <p className="text-sm text-amber-200">{error}</p>}
      {running && <p className="text-xs text-zinc-500">Camera live — QR and Code 128 are both accepted.</p>}
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (manual.trim()) onDetect(manual.trim());
        }}
      >
        <Input
          value={manual}
          onChange={(e) => setManual(e.target.value)}
          placeholder="Or type FILT-… or SPOOL-…"
          className="h-12 text-base"
        />
        <Button type="submit" className="h-12 px-5">
          Go
        </Button>
      </form>
    </div>
  );
}
