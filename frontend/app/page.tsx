"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Dashboard, Printer } from "@/lib/types";
import { StatusPill } from "@/components/status-pill";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDuration, formatEta, formatGrams, formatMoney } from "@/lib/format";
import { toast } from "sonner";
import { ScanLine } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

function Kpi({ label, value, warn }: { label: string; value: number | string; warn?: boolean }) {
  return (
    <div className="rounded-xl border border-white/8 bg-[#141a21] px-4 py-3">
      <div className="text-[11px] uppercase tracking-[0.16em] text-zinc-500">{label}</div>
      <div className={`mt-1 font-mono text-2xl font-semibold ${warn ? "text-amber-300" : "text-zinc-50"}`}>
        {value}
      </div>
    </div>
  );
}

function PrinterCard({ printer, onClear }: { printer: Printer; onClear: (id: string) => void }) {
  const pct = Math.min(100, printer.progress_percent || 0);
  return (
    <Card className="bg-[#141a21]">
      <CardHeader className="flex flex-row items-start justify-between gap-2 space-y-0">
        <div>
          <CardTitle className="text-base">{printer.name}</CardTitle>
          <div className="text-xs text-muted-foreground">
            {printer.model} · {printer.adapter_type}
          </div>
        </div>
        <StatusPill status={printer.status} />
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex justify-between text-xs text-zinc-400">
          <span>{printer.current_file || printer.current_part || "No active file"}</span>
          <span className="font-mono">{pct.toFixed(0)}%</span>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-zinc-800">
          <div
            className={`h-full ${printer.status === "waiting_for_bed_clear" ? "bg-amber-400" : "bg-emerald-400"}`}
            style={{ width: `${pct}%` }}
          />
        </div>
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div>
            <div className="text-zinc-500">Run</div>
            <div className="truncate">{printer.production_run || "—"}</div>
          </div>
          <div>
            <div className="text-zinc-500">Remaining</div>
            <div>
              {printer.quantity_remaining ?? "—"} left · {printer.quantity_completed ?? "—"} QC passed
            </div>
          </div>
          <div>
            <div className="text-zinc-500">Time / ETA</div>
            <div className="font-mono">
              {formatDuration(printer.time_remaining_seconds)} · {formatEta(printer.eta)}
            </div>
          </div>
          <div>
            <div className="text-zinc-500">Temps</div>
            <div className="font-mono">
              N {printer.nozzle_temp.toFixed(0)}° / B {printer.bed_temp.toFixed(0)}°
            </div>
          </div>
          <div>
            <div className="text-zinc-500">Filament</div>
            <div className="truncate">
              {printer.filament_name || "Unassigned"} {printer.filament_material ? `· ${printer.filament_material}` : ""}
            </div>
          </div>
          <div>
            <div className="text-zinc-500">Est. used / cost</div>
            <div className="font-mono">
              {formatGrams(printer.estimated_filament_used_g)} · {formatMoney(printer.estimated_filament_cost)}
            </div>
          </div>
        </div>
        {printer.status === "waiting_for_bed_clear" && (
          <Button className="w-full" onClick={() => onClear(printer.id)}>
            Confirm bed cleared
          </Button>
        )}
        <Link href={`/printers/${printer.id}`} className="block text-center text-xs text-amber-300 hover:underline">
          Open printer
        </Link>
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const dash = await api<Dashboard>("/api/v1/dashboard");
      setData(dash);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load dashboard");
    }
  }

  useEffect(() => {
    load();
    const id = setInterval(load, 2000);
    return () => clearInterval(id);
  }, []);

  async function clearBed(id: string) {
    try {
      await api(`/api/v1/printers/${id}/bed-cleared`, { method: "POST" });
      toast.success("Bed cleared — scheduler will assign the next compatible job.");
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not clear bed");
    }
  }

  if (error && !data) {
    return <div className="text-red-300">{error}</div>;
  }
  if (!data) {
    return <div className="text-zinc-500">Loading farm dashboard…</div>;
  }

  const running = data.printers.filter((p) => p.status === "printing" || p.status === "paused");

  return (
    <div className="space-y-6">
      <div className="flex justify-end">
        <Link href="/scan" className={cn(buttonVariants({ size: "lg" }), "h-12 min-w-28 gap-2 text-base")}>
          <ScanLine className="size-5" />
          SCAN
        </Link>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <Kpi label="Printing" value={data.counts.printing} />
        <Kpi label="Bed clear" value={data.counts.waiting_for_bed_clear} warn={data.counts.waiting_for_bed_clear > 0} />
        <Kpi label="Queued" value={data.counts.queued_jobs} />
        <Kpi label="Failed" value={data.counts.failed_jobs} warn={data.counts.failed_jobs > 0} />
        <Kpi label="Orders waiting" value={data.counts.orders_waiting} />
        <Kpi label="Ready to ship" value={data.counts.orders_ready} />
        <Kpi label="Low filament" value={data.counts.low_filament} warn={data.counts.low_filament > 0} />
        <Kpi label="Awaiting QC" value={data.counts.awaiting_qc} />
      </div>

      <section>
        <div className="mb-3 flex items-end justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-zinc-400">Printers currently running</h2>
          <span className="text-xs text-zinc-500">{running.length} active</span>
        </div>
        {running.length === 0 ? (
          <p className="rounded-xl border border-dashed border-white/10 p-6 text-sm text-zinc-500">
            No printers are printing. Idle machines will take work from the queue once beds are clear.
          </p>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {running.map((p) => (
              <PrinterCard key={p.id} printer={p} onClear={clearBed} />
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-[0.16em] text-zinc-400">Fleet</h2>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data.printers.map((p) => (
            <PrinterCard key={p.id} printer={p} onClear={clearBed} />
          ))}
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardHeader>
            <CardTitle>Waiting for bed clearance</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {data.waiting_for_bed_clear.length === 0 && (
              <p className="text-sm text-zinc-500">No printers blocked on bed clear.</p>
            )}
            {data.waiting_for_bed_clear.map((p) => (
              <div key={p.id} className="flex items-center justify-between gap-2 rounded-md bg-amber-500/10 p-2">
                <div>
                  <div className="text-sm">{p.name}</div>
                  <div className="text-xs text-zinc-400">{p.current_file}</div>
                </div>
                <Button size="sm" onClick={() => clearBed(p.id)}>
                  Cleared
                </Button>
              </div>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Failed jobs</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {data.failed_jobs.length === 0 && <p className="text-sm text-zinc-500">No failed jobs.</p>}
            {data.failed_jobs.map((j) => (
              <div key={j.id} className="rounded-md bg-red-500/10 p-2 text-sm">
                <div className="font-medium">{j.gcode_filename}</div>
                <div className="text-xs text-zinc-400">{j.fail_reason}</div>
              </div>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Upcoming queue</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {data.upcoming_jobs.length === 0 && <p className="text-sm text-zinc-500">Queue is empty.</p>}
            {data.upcoming_jobs.map((j) => (
              <div key={j.id} className="flex justify-between text-sm">
                <span className="truncate">{j.gcode_filename}</span>
                <StatusPill status={j.status} />
              </div>
            ))}
            <Link href="/queue" className="block pt-2 text-xs text-amber-300 hover:underline">
              Open print queue
            </Link>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Orders & filament</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div>
              <div className="mb-1 text-xs uppercase text-zinc-500">Waiting for production</div>
              {data.orders_waiting.length === 0 && <p className="text-zinc-500">None</p>}
              {data.orders_waiting.map((o) => (
                <Link key={o.id} href={`/orders/${o.id}`} className="block hover:text-amber-200">
                  {o.reference} · {o.customer_name}
                </Link>
              ))}
            </div>
            <div>
              <div className="mb-1 text-xs uppercase text-zinc-500">Ready to ship</div>
              {data.orders_ready.length === 0 && <p className="text-zinc-500">None</p>}
              {data.orders_ready.map((o) => (
                <Link key={o.id} href={`/orders/${o.id}`} className="block hover:text-amber-200">
                  {o.reference} · {o.customer_name}
                </Link>
              ))}
            </div>
            <div>
              <div className="mb-1 text-xs uppercase text-zinc-500">Low filament</div>
              {data.low_filament.length === 0 && <p className="text-zinc-500">All spools healthy</p>}
              {data.low_filament.map((s) => (
                <div key={s.id} className="text-amber-200">
                  {s.name} · {formatGrams(s.remaining_weight_g)}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
