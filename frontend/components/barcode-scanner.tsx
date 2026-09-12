"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Stoppable = { stop: () => Promise<void> };

function safeStop(scanner: Stoppable | null) {
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

function patchStop(Ctor: { prototype: { stop: () => Promise<void> } }) {
  const proto = Ctor.prototype as { stop: (() => Promise<void>) & { __farmosSafe?: boolean } };
  if (proto.stop.__farmosSafe) return;
  const original = proto.stop;
  const wrapped = function (this: Stoppable) {
    try {
      const pending = original.call(this);
      if (pending && typeof pending.catch === "function") return pending.catch(() => undefined);
      return Promise.resolve();
    } catch {
      return Promise.resolve();
    }
  } as (() => Promise<void>) & { __farmosSafe?: boolean };
  wrapped.__farmosSafe = true;
  proto.stop = wrapped;
}

export function BarcodeScanner({
  onDetect,
  label = "USB and Bluetooth scanners work as a keyboard: click or focus the field below and pull the trigger. Codes submit on Enter. Camera (QR and Code 128) is optional, and you can type a code and press Go.",
  autoFocus = true,
}: {
  onDetect: (code: string) => void;
  label?: string;
  autoFocus?: boolean;
}) {
  const uid = useId().replace(/:/g, "");
  const elementId = `farmos-scanner-${uid}`;
  const host = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [manual, setManual] = useState("");
  const [running, setRunning] = useState(false);
  const [wantCamera, setWantCamera] = useState(false);
  const onDetectRef = useRef(onDetect);
  onDetectRef.current = onDetect;
  const scannerRef = useRef<Stoppable | null>(null);

  useEffect(() => {
    if (!wantCamera) return;
    let cancelled = false;
    async function start() {
      if (!host.current) return;
      try {
        const { Html5Qrcode, Html5QrcodeSupportedFormats } = await import("html5-qrcode");
        patchStop(Html5Qrcode);
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
  }, [wantCamera]);

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">{label}</p>
      {wantCamera ? (
        <div id={elementId} ref={host} className="overflow-hidden rounded-xl bg-black min-h-[220px]" />
      ) : (
        <button
          type="button"
          onClick={() => setWantCamera(true)}
          className="flex min-h-[140px] w-full flex-col items-center justify-center rounded-xl border border-dashed border-white/15 bg-black/40 px-4 text-center"
        >
          <span className="text-sm font-medium text-zinc-200">Use camera</span>
          <span className="mt-1 text-xs text-zinc-500">QR and Code 128. Skip this on a desktop without a camera.</span>
        </button>
      )}
      {error && <p className="text-sm text-amber-200">{error}</p>}
      {running && <p className="text-xs text-zinc-500">Camera live — QR and Code 128 are both accepted.</p>}
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          const value = manual.trim();
          if (!value) return;
          onDetect(value);
          setManual("");
        }}
      >
        <Input
          value={manual}
          onChange={(e) => setManual(e.target.value)}
          placeholder="Scan or type FILT-… or SPOOL-…"
          className="h-12 text-base"
          autoFocus={autoFocus}
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="off"
          spellCheck={false}
          data-farmos-scan="1"
        />
        <Button type="submit" className="h-12 px-5">
          Go
        </Button>
      </form>
      <p className="text-xs text-zinc-500">
        Plug in a USB or Bluetooth HID scanner, focus this field, and scan. The camera button is for phones.
      </p>
    </div>
  );
}
