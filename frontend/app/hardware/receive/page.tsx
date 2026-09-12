"use client";

import { Suspense, useCallback, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { HardwareNav } from "@/components/hardware-nav";
import { BarcodeScanner } from "@/components/barcode-scanner";
import { toast } from "sonner";

function ReceiveInner() {
  const params = useSearchParams();
  const router = useRouter();

  const identify = useCallback(
    async (code: string) => {
      try {
        const hit = await api<{ kind: string; id: string; path?: string }>("/api/v1/filament/lookup", {
          method: "POST",
          body: JSON.stringify({ code }),
        });
        if (hit.kind !== "hardware") {
          toast.error("Scan a hardware HW- barcode, not a filament or spool code.");
          return;
        }
        router.replace(hit.path || `/hardware/${hit.id}?add=1`);
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
      <HardwareNav />
      <h2 className="text-xl font-semibold">Scan a hardware SKU</h2>
      <p className="text-sm text-muted-foreground">
        Scan the reusable HW- barcode. FarmOS opens that SKU so you only enter how many pieces arrived.
      </p>
      <BarcodeScanner onDetect={identify} />
    </div>
  );
}

export default function HardwareReceivePage() {
  return (
    <Suspense fallback={<div className="text-zinc-500">Opening receive…</div>}>
      <ReceiveInner />
    </Suspense>
  );
}
