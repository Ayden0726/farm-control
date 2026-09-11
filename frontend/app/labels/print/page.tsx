"use client";

import { Suspense, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { toast } from "sonner";

function PrintInner() {
  const params = useSearchParams();
  useEffect(() => {
    const kind = params.get("kind") || "product";
    const ids = (params.get("ids") || "").split(",").filter(Boolean);
    const copies = Number(params.get("copies") || "1");
    if (!ids.length) return;
    api<{ html: string }>("/api/v1/labels/sheet", {
      method: "POST",
      body: JSON.stringify({
        kind,
        items: ids.map((id) => ({ id, copies })),
        width_mm: Number(params.get("w") || 54),
        height_mm: Number(params.get("h") || 70),
        columns: Number(params.get("cols") || 2),
      }),
    })
      .then((res) => {
        document.open();
        document.write(res.html);
        document.close();
      })
      .catch((err) => toast.error(err instanceof Error ? err.message : "Print failed"));
  }, [params]);
  return <div className="p-6 text-zinc-400">Preparing labels…</div>;
}

export default function PrintPage() {
  return (
    <Suspense fallback={<div className="p-6 text-zinc-400">Preparing labels…</div>}>
      <PrintInner />
    </Suspense>
  );
}
