"use client";

import { FormEvent, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { FilamentNav } from "@/components/filament-nav";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatGrams, formatMoney } from "@/lib/format";
import { labelsPrintHref } from "@/lib/labels";
import { toast } from "sonner";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { DryingChoice, DryingStatusValue, dryingLabel } from "@/components/drying-choice";

type Spool = {
  id: string;
  product_id: string | null;
  public_code: string;
  name: string;
  manufacturer: string;
  material: string;
  color: string;
  initial_weight_g: number;
  remaining_weight_g: number;
  consumed_g: number;
  cost: number;
  cost_per_kg: number;
  is_sealed: boolean;
  is_empty: boolean;
  is_archived: boolean;
  drying_status: string;
  location_id: string | null;
  location_name: string | null;
  assigned_printer_name: string | null;
  assigned_printer_id: string | null;
  notes: string;
  purchase_date: string | null;
  date_received: string | null;
  date_opened: string | null;
  last_dried_at: string | null;
  transactions: { id: string; at: string; previous_g: number; amount_g: number; remaining_g: number; reason: string; notes: string }[];
};

type Loc = { id: string; name: string; kind?: string };
type Printer = { id: string; name: string };

export default function SpoolDetailPage() {
  const params = useParams<{ id: string }>();
  const [spool, setSpool] = useState<Spool | null>(null);
  const [locs, setLocs] = useState<Loc[]>([]);
  const [printers, setPrinters] = useState<Printer[]>([]);
  const [remaining, setRemaining] = useState("");

  async function load() {
    const row = await api<Spool>(`/api/v1/filament/spools/${params.id}`);
    setSpool(row);
    setRemaining(String(row.remaining_weight_g));
  }
  useEffect(() => {
    load();
    api<Loc[]>("/api/v1/filament/locations").then(setLocs);
    api<Printer[]>("/api/v1/printers").then(setPrinters);
  }, [params.id]);

  if (!spool) return <div className="text-zinc-500">Loading spool…</div>;

  async function move(location_id: string) {
    await api(`/api/v1/filament/spools/${params.id}/move`, { method: "POST", body: JSON.stringify({ location_id }) });
    toast.success("Location updated");
    load();
  }

  async function setDrying(status: DryingStatusValue) {
    await api(`/api/v1/filament/spools/${params.id}/detail`, {
      method: "PATCH",
      body: JSON.stringify({ drying_status: status }),
    });
    if (status === "drying") {
      const dryer = locs.find((l) => l.kind === "dryer" || /dryer/i.test(l.name));
      if (dryer && spool?.location_id !== dryer.id) {
        await api(`/api/v1/filament/spools/${params.id}/move`, {
          method: "POST",
          body: JSON.stringify({ location_id: dryer.id }),
        });
      }
    }
    toast.success("Drying updated");
    load();
  }

  async function assign(printer_id: string) {
    await api("/api/v1/filament/assign", { method: "POST", body: JSON.stringify({ printer_id, spool_id: params.id }) });
    toast.success("Assigned to printer");
    load();
  }

  async function adjust(e: FormEvent) {
    e.preventDefault();
    await api(`/api/v1/filament/spools/${params.id}/adjust`, {
      method: "POST",
      body: JSON.stringify({ remaining_weight_g: Number(remaining), notes: "Manual correction" }),
    });
    toast.success("Weight corrected — a transaction was stored");
    load();
  }

  return (
    <div className="space-y-4">
      <FilamentNav />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-mono text-xl">{spool.public_code}</h2>
          <p>
            {spool.manufacturer} {spool.material} — {spool.color}
          </p>
          {spool.product_id && (
            <Link href={`/filament/products/${spool.product_id}`} className="text-sm text-amber-300 hover:underline">
              Open filament profile
            </Link>
          )}
        </div>
        <Link href={labelsPrintHref("spool", [spool.id], { layout: "one", auto: true })} className={cn(buttonVariants(), "h-11")}>
          Reprint Label
        </Link>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-5 font-mono text-sm">
        <Card><CardHeader><CardTitle>Remaining</CardTitle></CardHeader><CardContent>{formatGrams(spool.remaining_weight_g)}</CardContent></Card>
        <Card><CardHeader><CardTitle>Consumed</CardTitle></CardHeader><CardContent>{formatGrams(spool.consumed_g)}</CardContent></Card>
        <Card><CardHeader><CardTitle>Paid at receive</CardTitle></CardHeader><CardContent>{formatMoney(spool.cost)}</CardContent></Card>
        <Card><CardHeader><CardTitle>Cost / kg</CardTitle></CardHeader><CardContent>{formatMoney(spool.cost_per_kg)}</CardContent></Card>
        <Card><CardHeader><CardTitle>Status</CardTitle></CardHeader><CardContent>{spool.is_empty ? "Empty" : spool.is_sealed ? "Sealed" : "Open"}</CardContent></Card>
      </div>
      <p className="text-sm text-zinc-400">
        Received {spool.date_received ? new Date(spool.date_received).toLocaleDateString() : "—"}
        {spool.purchase_date ? ` · purchased ${new Date(spool.purchase_date).toLocaleDateString()}` : ""}
        · Location: {spool.location_name || "—"} · Printer: {spool.assigned_printer_name || "—"} · Drying: {dryingLabel(spool.drying_status)}
        {spool.last_dried_at ? ` · last dried ${new Date(spool.last_dried_at).toLocaleString()}` : ""}
      </p>
      <p className="text-xs text-zinc-500">
        This roll keeps the ${spool.cost.toFixed(2)} paid when it arrived, even if the profile’s normal price changes later.
      </p>
      <div className="grid gap-3 md:grid-cols-2">
        <div className="space-y-1">
          <Label>Move to location</Label>
          <select className="h-12 w-full rounded-lg border border-input bg-transparent px-2" defaultValue="" onChange={(e) => e.target.value && move(e.target.value)}>
            <option value="">Choose…</option>
            {locs.map((l) => (
              <option key={l.id} value={l.id}>{l.name}</option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <Label>Assign to printer</Label>
          <select className="h-12 w-full rounded-lg border border-input bg-transparent px-2" defaultValue="" onChange={(e) => e.target.value && assign(e.target.value)}>
            <option value="">Choose…</option>
            {printers.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>
      </div>
      <DryingChoice value={spool.drying_status} onChange={setDrying} />
      <form onSubmit={adjust} className="flex flex-wrap items-end gap-2">
        <div className="space-y-1">
          <Label>Correct remaining grams</Label>
          <Input value={remaining} onChange={(e) => setRemaining(e.target.value)} />
        </div>
        <Button type="submit">Save correction</Button>
      </form>
      <Card>
        <CardHeader>
          <CardTitle>Transactions</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          {spool.transactions.map((t) => (
            <div key={t.id} className="flex justify-between gap-3">
              <span>
                {new Date(t.at).toLocaleString()} · {t.reason}
              </span>
              <span className="font-mono">
                {formatGrams(t.previous_g)} → {formatGrams(t.remaining_g)}
              </span>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
