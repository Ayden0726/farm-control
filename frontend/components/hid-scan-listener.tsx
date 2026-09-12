"use client";

import { useRef } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useHidScanner } from "@/hooks/use-hid-scanner";
import { toast } from "sonner";

type Hit = { kind: string; path: string; name?: string; public_code?: string; barcode_id?: string };

export function HidScanListener() {
  const router = useRouter();
  const busy = useRef(false);

  useHidScanner(async (code) => {
    if (busy.current) return;
    busy.current = true;
    try {
      const hit = await api<Hit>("/api/v1/filament/lookup", {
        method: "POST",
        body: JSON.stringify({ code }),
      });
      const label = hit.name || hit.public_code || hit.barcode_id || hit.kind;
      toast.success(`Scanned ${hit.kind}: ${label}`);
      router.push(hit.path);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Unknown barcode");
    } finally {
      window.setTimeout(() => {
        busy.current = false;
      }, 500);
    }
  });

  return null;
}
