"use client";

import { Suspense, useCallback, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { FilamentNav } from "@/components/filament-nav";
import { BarcodeScanner } from "@/components/barcode-scanner";
import { toast } from "sonner";

function ReceiveInner() {
  const params = useSearchParams();
  const router = useRouter();

  const identify = useCallback(
    async (code: string) => {
      try {
        const hit = await api<{ kind: string; id: string }>("/api/v1/filament/lookup", {
          method: "POST",
          body: JSON.stringify({ code }),
        });
        if (hit.kind !== "product") {
          toast.error("Scan a reusable profile barcode (FILT-…), not a unique spool QR.");
          return;
        }
        router.replace(`/filament/products/${hit.id}?add=1`);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Unknown barcode");
      }
    },
    [router],
  );

  useEffect(() => {
    const code = params.get("code");
    if (code) identify(code);
  }, [params, identify]);

  return (
    <div className="mx-auto max-w-xl space-y-4">
      <FilamentNav />
      <h2 className="text-xl font-semibold">Scan a filament profile</h2>
      <p className="text-sm text-muted-foreground">
        Connect a USB or Bluetooth scanner to this PC, focus the field, and scan the reusable FILT- barcode. On a phone,
        use the camera. FarmOS opens that saved profile so you only enter how many rolls arrived.
      </p>
      <BarcodeScanner onDetect={identify} />
    </div>
  );
}

export default function ReceivePage() {
  return (
    <Suspense fallback={<div className="text-zinc-500">Opening receive…</div>}>
      <ReceiveInner />
    </Suspense>
  );
}
