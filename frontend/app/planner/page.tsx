"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import Link from "next/link";

type Line = {
  id: string;
  part_sku: string;
  part_name: string;
  printer_id: string | null;
  printer_name: string | null;
  quantity: number;
  jobs_needed: number;
  estimated_start: string | null;
  estimated_end: string | null;
  required_filament_g: number;
  filament_ok: boolean;
  compatible: boolean;
  incompatibility_reason: string;
  order_refs: string[];
  reason: string;
  included: boolean;
  gcode_filename: string | null;
};

type Plan = { id: string; status: string; lines: Line[]; production_run_id?: string | null };

type Printer = { id: string; name: string };

export default function PlannerPage() {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [printers, setPrinters] = useState<Printer[]>([]);
  const [busy, setBusy] = useState(false);

  async function generate() {
    setBusy(true);
    try {
      const row = await api<Plan>("/api/v1/planner/generate", { method: "POST" });
      setPlan(row);
      toast.success("Production plan generated. Review shortages before committing to the queue.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not generate plan");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    api<Printer[]>("/api/v1/printers").then(setPrinters).catch(() => undefined);
  }, []);

  async function patch(line: Line, patch: Partial<Line>) {
    if (!plan) return;
    const next = await api<Plan>(`/api/v1/planner/${plan.id}/lines/${line.id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    });
    setPlan(next);
  }

  async function commit() {
    if (!plan) return;
    setBusy(true);
    try {
      const res = await api<{ run?: { id: string; batch_code?: string } }>(`/api/v1/planner/${plan.id}/commit`, {
        method: "POST",
      });
      toast.success(res.run?.batch_code ? `Committed ${res.run.batch_code}` : "Plan committed to the print queue");
      generate();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Commit failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-zinc-400">
          Calculates true shortages from open orders minus available inventory (physical − reserved) minus jobs already
          in the queue, then recommends a compatible printer.
        </p>
        <Button onClick={generate} disabled={busy}>
          {busy ? "Working…" : "Generate production plan"}
        </Button>
      </div>
      {!plan && <p className="text-sm text-zinc-500">Generate a plan to review printer assignments before queueing.</p>}
      {plan && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Draft plan</CardTitle>
            <Button onClick={commit} disabled={busy || plan.status !== "draft"}>
              Commit to print queue
            </Button>
          </CardHeader>
          <CardContent className="space-y-3">
            {plan.lines.length === 0 && <p className="text-sm text-zinc-500">Nothing to print. Inventory covers open orders.</p>}
            {plan.lines.map((line) => (
              <div key={line.id} className="space-y-2 rounded-md border border-white/8 p-3 text-sm">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={line.included}
                    onChange={(e) => patch(line, { included: e.target.checked } as never)}
                  />
                  <span className="font-medium">
                    {line.part_sku} · {line.quantity} pcs
                  </span>
                </label>
                <div className="grid gap-2 md:grid-cols-4">
                  <div>
                    Printer
                    <select
                      className="mt-1 h-8 w-full rounded-lg border border-input bg-transparent px-2"
                      value={line.printer_id || ""}
                      onChange={(e) => patch(line, { printer_id: e.target.value || null } as never)}
                    >
                      <option value="">Unassigned</option>
                      {printers.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    Quantity
                    <Input
                      className="mt-1"
                      type="number"
                      value={line.quantity}
                      onChange={(e) => patch(line, { quantity: Number(e.target.value) } as never)}
                    />
                  </div>
                  <div>
                    <div className="text-zinc-500">Start → finish</div>
                    <div className="font-mono text-xs">
                      {line.estimated_start ? new Date(line.estimated_start).toLocaleString() : "—"}
                      <br />
                      {line.estimated_end ? new Date(line.estimated_end).toLocaleString() : "—"}
                    </div>
                  </div>
                  <div>
                    <div className="text-zinc-500">Filament</div>
                    <div>
                      {line.required_filament_g.toFixed(0)} g {line.filament_ok ? "" : "· short"}
                    </div>
                    <div className="text-xs text-zinc-500">{line.gcode_filename || "No G-code"}</div>
                  </div>
                </div>
                <div className="text-xs text-zinc-400">
                  {line.reason}
                  {line.order_refs.length ? ` · Orders ${line.order_refs.join(", ")}` : ""}
                </div>
                {!line.compatible && line.incompatibility_reason && (
                  <div className="rounded-md bg-amber-500/10 p-2 text-xs text-amber-200">
                    Job incompatible{line.printer_name ? ` with ${line.printer_name}` : ""}. Reason:{" "}
                    {line.incompatibility_reason}
                  </div>
                )}
              </div>
            ))}
            <Link href="/timeline" className="text-xs text-amber-300 hover:underline">
              Open production timeline
            </Link>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
