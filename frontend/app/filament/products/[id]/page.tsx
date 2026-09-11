"use client";

import Link from "next/link";
import { FormEvent, Suspense, useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { FilamentNav } from "@/components/filament-nav";
import { AddRollsPanel } from "@/components/add-rolls-panel";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatGrams } from "@/lib/format";
import { labelsPrintHref } from "@/lib/labels";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

type Detail = {
  id: string;
  barcode_id: string;
  manufacturer: string;
  product_name: string;
  material: string;
  color: string;
  spool_size_label: string;
  filament_weight_g: number;
  purchase_cost: number;
  cost_per_kg: number;
  supplier_sku: string;
  supplier_url: string;
  nozzle_temp_c: number | null;
  bed_temp_c: number | null;
  notes: string;
  min_stock_g: number;
  target_stock_g: number;
  preferred_spool_weight_g: number;
  normal_price: number;
  max_price: number;
  max_price_per_kg: number;
  min_reorder_qty: number;
  reorder_multiple: number;
  lead_time_days: number;
  reorder_mode: string;
  approval_required: boolean;
  max_po_amount: number;
  preferred_supplier_name: string | null;
  preferred_supplier_id?: string | null;
  stock: {
    physical_kg: number;
    committed_kg: number;
    available_kg: number;
    sealed_rolls: number;
    open_rolls: number;
    installed_rolls: number;
  };
  forecast: { avg_daily_g: number; days_remaining: number | null; depletion_at: string | null; recommended_reorder_at: string | null };
  recommend: { needed: boolean; rolls: number; reason: string; resulting_g: number };
  spools: { id: string; public_code: string; remaining_weight_g: number; is_sealed: boolean; assigned_printer_name: string | null; location_name: string | null }[];
};

function ProductDetailInner() {
  const params = useParams<{ id: string }>();
  const search = useSearchParams();
  const [row, setRow] = useState<Detail | null>(null);

  async function load() {
    setRow(await api<Detail>(`/api/v1/filament/products/${params.id}`));
  }
  useEffect(() => {
    load();
  }, [params.id]);

  if (!row) return <div className="text-zinc-500">Loading filament profile…</div>;

  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!row) return;
    const current = row;
    const fd = new FormData(e.currentTarget);
    try {
      await api(`/api/v1/filament/products/${params.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          manufacturer: current.manufacturer,
          product_name: current.product_name,
          material: current.material,
          color: current.color,
          spool_size_label: current.spool_size_label,
          filament_weight_g: current.filament_weight_g,
          purchase_cost: Number(fd.get("purchase_cost")),
          supplier_sku: String(fd.get("supplier_sku") || ""),
          supplier_url: String(fd.get("supplier_url") || ""),
          notes: String(fd.get("notes") || ""),
          min_stock_g: Number(fd.get("min_stock_g")),
          target_stock_g: Number(fd.get("target_stock_g")),
          preferred_spool_weight_g: current.preferred_spool_weight_g,
          normal_price: Number(fd.get("normal_price")),
          max_price: Number(fd.get("max_price")),
          max_price_per_kg: Number(fd.get("max_price_per_kg")),
          min_reorder_qty: Number(fd.get("min_reorder_qty")),
          reorder_multiple: Number(fd.get("reorder_multiple")),
          lead_time_days: Number(fd.get("lead_time_days")),
          reorder_mode: String(fd.get("reorder_mode")),
          approval_required: fd.get("approval_required") === "on",
          max_po_amount: Number(fd.get("max_po_amount")),
          nozzle_temp_c: fd.get("nozzle_temp_c") ? Number(fd.get("nozzle_temp_c")) : current.nozzle_temp_c,
          bed_temp_c: fd.get("bed_temp_c") ? Number(fd.get("bed_temp_c")) : current.bed_temp_c,
        }),
      });
      toast.success("Reorder settings saved");
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Save failed");
    }
  }

  return (
    <div className="space-y-4">
      <FilamentNav />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">
            {row.manufacturer} {row.material} — {row.color}
          </h2>
          <p className="text-sm text-zinc-400">Filament profile · {row.spool_size_label}</p>
          <p className="font-mono text-sm text-amber-200">{row.barcode_id}</p>
          <p className="text-sm text-zinc-500">
            Saved once. New rolls inherit manufacturer, material, colour, size, supplier, and temperatures.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            href={labelsPrintHref("product", [row.id], { layout: "one", auto: true })}
            className={cn(buttonVariants({ variant: "outline" }), "h-11")}
          >
            Print Receiving Barcode
          </Link>
          {row.supplier_url && (
            <a href={row.supplier_url} target="_blank" rel="noreferrer" className={cn(buttonVariants({ variant: "outline" }), "h-11")}>
              Open Supplier Page
            </a>
          )}
        </div>
      </div>
      <AddRollsPanel
        product={row}
        defaultOpen={search.get("add") === "1" || row.spools.length === 0}
        onCreated={load}
      />
      <div className="grid gap-3 md:grid-cols-4">
        <Card>
          <CardHeader>
            <CardTitle>Physical</CardTitle>
          </CardHeader>
          <CardContent className="font-mono">{row.stock.physical_kg.toFixed(1)} kg</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Committed</CardTitle>
          </CardHeader>
          <CardContent className="font-mono">{row.stock.committed_kg.toFixed(1)} kg</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Available</CardTitle>
          </CardHeader>
          <CardContent className="font-mono text-amber-200">{row.stock.available_kg.toFixed(1)} kg</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Forecast</CardTitle>
          </CardHeader>
          <CardContent className="text-sm">
            {formatGrams(row.forecast.avg_daily_g)}/day
            {row.forecast.days_remaining != null ? ` · ${row.forecast.days_remaining} days left` : ""}
          </CardContent>
        </Card>
      </div>
      {row.recommend.needed && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm">
          {row.recommend.reason} Resulting stock {formatGrams(row.recommend.resulting_g)}.
        </div>
      )}
      <Card>
        <CardHeader>
          <CardTitle>Reorder settings</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={save} className="grid gap-3 sm:grid-cols-3">
            {(
              [
                { name: "min_stock_g", label: "Minimum (g)", value: row.min_stock_g },
                { name: "target_stock_g", label: "Target (g)", value: row.target_stock_g },
                { name: "normal_price", label: "Normal price", value: row.normal_price },
                { name: "purchase_cost", label: "Purchase cost", value: row.purchase_cost },
                { name: "max_price", label: "Max price", value: row.max_price },
                { name: "max_price_per_kg", label: "Max $/kg", value: row.max_price_per_kg },
                { name: "min_reorder_qty", label: "Min reorder qty", value: row.min_reorder_qty },
                { name: "reorder_multiple", label: "Reorder multiple", value: row.reorder_multiple },
                { name: "lead_time_days", label: "Lead time (days)", value: row.lead_time_days },
                { name: "max_po_amount", label: "Max PO amount", value: row.max_po_amount },
                { name: "nozzle_temp_c", label: "Nozzle °C", value: row.nozzle_temp_c ?? "" },
                { name: "bed_temp_c", label: "Bed °C", value: row.bed_temp_c ?? "" },
              ] as { name: string; label: string; value: number | string }[]
            ).map((field) => (
              <div key={field.name} className="space-y-1">
                <Label>{field.label}</Label>
                <Input name={field.name} defaultValue={String(field.value)} />
              </div>
            ))}
            <div className="space-y-1">
              <Label>Reorder mode</Label>
              <select name="reorder_mode" defaultValue={row.reorder_mode} className="h-8 w-full rounded-lg border border-input bg-transparent px-2 text-sm">
                <option value="off">Off</option>
                <option value="suggest_only">Suggest only</option>
                <option value="create_purchase_order">Create purchase order (recommended)</option>
                <option value="approve_and_order">Approve and order</option>
                <option value="full_auto">Full auto (disabled unless spending control is on)</option>
              </select>
            </div>
            <div className="space-y-1 sm:col-span-2">
              <Label>Supplier SKU</Label>
              <Input name="supplier_sku" defaultValue={row.supplier_sku} />
            </div>
            <div className="space-y-1 sm:col-span-3">
              <Label>Supplier URL</Label>
              <Input name="supplier_url" defaultValue={row.supplier_url} />
            </div>
            <div className="space-y-1 sm:col-span-3">
              <Label>Notes</Label>
              <Input name="notes" defaultValue={row.notes} />
            </div>
            <label className="flex items-center gap-2 text-sm sm:col-span-2">
              <input type="checkbox" name="approval_required" defaultChecked={row.approval_required} />
              Approval required
            </label>
            <Button type="submit">Save settings</Button>
          </form>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Physical rolls</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          {row.spools.length === 0 && (
            <p className="text-zinc-500">No physical rolls yet. Use Add New Rolls — FarmOS assigns the next SPOOL numbers automatically.</p>
          )}
          {row.spools.map((s) => (
            <div key={s.id} className="flex items-center justify-between gap-2 rounded-md bg-white/5 px-3 py-2">
              <Link href={`/filament/spools/${s.id}`} className="flex min-w-0 flex-1 justify-between hover:text-amber-200">
                <span className="font-mono">{s.public_code}</span>
                <span className="truncate text-zinc-400">
                  {formatGrams(s.remaining_weight_g)} · {s.is_sealed ? "Sealed" : "Open"} · {s.assigned_printer_name || s.location_name || "—"}
                </span>
              </Link>
              <Link href={labelsPrintHref("spool", [s.id], { layout: "one", auto: true })} className="shrink-0 text-xs text-amber-300 hover:underline">
                Reprint
              </Link>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

export default function ProductDetailPage() {
  return (
    <Suspense fallback={<div className="text-zinc-500">Loading filament profile…</div>}>
      <ProductDetailInner />
    </Suspense>
  );
}
