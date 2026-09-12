"use client";

import { useEffect, useState } from "react";
import { getToken } from "@/lib/api";
import { cn } from "@/lib/utils";

export function PrinterCamera({
  printerId,
  className,
  refreshMs = 4000,
}: {
  printerId: string;
  className?: string;
  refreshMs?: number;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [status, setStatus] = useState("offline");

  useEffect(() => {
    let cancel = false;
    let current: string | null = null;
    async function tick() {
      try {
        const headers = new Headers();
        const t = getToken();
        if (t) headers.set("Authorization", `Bearer ${t}`);
        const res = await fetch(`/api/v1/printers/${printerId}/camera`, { headers, cache: "no-store" });
        if (!res.ok) {
          if (!cancel) setStatus("offline");
          return;
        }
        const blob = await res.blob();
        const next = URL.createObjectURL(blob);
        if (current) URL.revokeObjectURL(current);
        current = next;
        if (!cancel) {
          setUrl(next);
          setStatus(res.headers.get("X-Camera-Status") || "online");
        }
      } catch {
        if (!cancel) setStatus("offline");
      }
    }
    tick();
    const id = setInterval(tick, refreshMs);
    return () => {
      cancel = true;
      clearInterval(id);
      if (current) URL.revokeObjectURL(current);
    };
  }, [printerId, refreshMs]);

  if (!url) {
    return <div className={cn("flex items-center justify-center rounded-md bg-black/40 text-xs text-zinc-500", className)}>Camera {status}</div>;
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img alt="Printer camera" src={url} className={cn("rounded-md object-cover bg-black", className)} />
  );
}
