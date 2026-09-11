"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import type { ProductionRun } from "@/lib/types";
import { StatusPill } from "@/components/status-pill";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "sonner";

export default function ProductionDetailPage() {
  const params = useParams<{ id: string }>();
  const [run, setRun] = useState<ProductionRun | null>(null);
  const [filament, setFilament] = useState<{
    overall: string;
    materials: { product_id: string; label: string; required_g: number; available_g: number; on_order_g: number }[];
  } | null>(null);

  async function load() {
    setRun(await api<ProductionRun>(`/api/v1/production-runs/${params.id}`));
    try {
      setFilament(await api(`/api/v1/production-runs/${params.id}/filament-check`));
    } catch {
      setFilament(null);
    }
  }
  useEffect(() => {
    load();
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
  }, [params.id]);

  if (!run) return <div className="text-zinc-500">Loading run…</div>;

  async function act(action: string) {
    const id = params.id;
    try {
      await api(`/api/v1/production-runs/${id}/${action}`, { method: "POST" });
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-xl font-semibold">{run.name}</h2>
          <p className="text-sm text-muted-foreground">{run.notes || "No notes"}</p>
        </div>
        <div className="flex items-center gap-2">
          <StatusPill status={run.status} />
          <Button variant="outline" size="sm" onClick={() => act("pause")}>
            Pause queued work
          </Button>
          <Button variant="outline" size="sm" onClick={() => act("resume")}>
            Resume
          </Button>
          <Button variant="outline" size="sm" onClick={() => act("requeue-scrap")}>
            Requeue scrap
          </Button>
          <Button variant="destructive" size="sm" onClick={() => act("cancel")}>
            Cancel remaining
          </Button>
        </div>
      </div>
      {filament && (
        <Card className={filament.overall !== "can_start" ? "border-amber-500/40" : ""}>
          <CardHeader>
            <CardTitle>Filament for this batch</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="font-medium">
              {filament.overall === "can_start"
                ? "Can start now"
                : filament.overall === "partial"
                  ? "Can partially start"
                  : filament.overall === "wait_for_stock"
                    ? "Should wait for stock on order"
                    : "Requires another purchase"}
            </div>
            {filament.materials.map((m) => (
              <div key={m.product_id} className="flex justify-between gap-3">
                <span>
                  {m.label}: {(m.required_g / 1000).toFixed(1)} kg required
                </span>
                <span className="font-mono">
                  avail {(m.available_g / 1000).toFixed(1)} kg · on order {(m.on_order_g / 1000).toFixed(1)} kg
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
      <div className="grid gap-3 md:grid-cols-2">
        {run.items.map((item) => (
          <Card key={item.id}>
            <CardHeader>
              <CardTitle className="text-base">
                {item.part_sku} · {item.part_name}
              </CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-2 font-mono text-sm">
              <span>Required {item.required_qty}</span>
              <span>Printed {item.printed_qty}</span>
              <span>Passed QC {item.passed_qc}</span>
              <span>Failed QC {item.failed_qc}</span>
              <span>Still to print {item.remaining_to_print}</span>
              <span className="text-amber-200">Remaining good {item.remaining_qty}</span>
              <span className="col-span-2 text-xs text-zinc-500">{item.gcode_filename}</span>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
