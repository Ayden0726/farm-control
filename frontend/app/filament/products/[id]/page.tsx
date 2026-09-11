"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { FilamentNav } from "@/components/filament-nav";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatGrams, formatMoney } from "@/lib/format";
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

export default function ProductDetailPage() {
  const params = useParams<{ id: string }>();
  const [row, setRow] = useState<Detail | null>(null);

  async function load() {
    setRow(await api<Detail>(`/api/v1/filament/products/${params.id}`));
  }
  useEffect(() => {
    load();
  }, [params.id]);

  if (!row) return <div className="text-zinc-500">Loading product…</div>;

  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    try {
      await api(`/api/v1/filament/products/${params.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          manufacturer: row.manufacturer,
          product_name: row.product_name,
          material: row.material,
          color: row.color,
          spool_size_label: row.spool_size_label,
          filament_weight_g: row.filament_weight_g,
          purchase_cost: Number(fd.get("purchase_cost")),
          supplier_sku: String(fd.get("supplier_sku") || ""),
          supplier_url: String(fd.get("supplier_url") || ""),
          notes: String(fd.get("notes") || ""),
          min_stock_g: Number(fd.get("min_stock_g")),
          target_stock_g: Number(fd.get("target_stock_g")),
          preferred_spool_weight_g: row.preferred_spool_weight_g,
          normal_price: Number(fd.get("normal_price")),
          max_price: Number(fd.get("max_price")),
          max_price_per_kg: Number(fd.get("max_price_per_kg")),
          min_reorder_qty: Number(fd.get("min_reorder_qty")),
          reorder_multiple: Number(fd.get("reorder_multiple")),
          lead_time_days: Number(fd.get("lead_time_days")),
          reorder_mode: String(fd.get("reorder_mode")),
          approval_required: fd.get("approval_required") === "on",
          max_po_amount: Number(fd.get("max_po_amount")),
          nozzle_temp_c: row.nozzle_temp_c,
          bed_temp_c: row.bed_temp_c,
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
          <p className="font-mono text-sm text-amber-200">{row.barcode_id}</p>
          <p className="text-sm text-zinc-500">{row.spool_size_label} · reusable receiving barcode</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            href={`/labels/print?kind=product&ids=${row.id}&copies=1`}
            className={cn(buttonVariants(), "h-11")}
          >
            Print Receiving Barcode
          </Link>
          <Link href={`/filament/receive?code=${encodeURIComponent(row.barcode_id)}`} className={cn(buttonVariants({ variant: "outline" }), "h-11")}>
            Receive stock
          </Link>
          {row.supplier_url && (
            <a href={row.supplier_url} target="_blank" rel="noreferrer" className={cn(buttonVariants({ variant: "outline" }), "h-11")}>
              Open Supplier Page
            </a>
          )}
        </div>
      </div>
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
            {[
              ["min_stock_g", "Minimum (g)", row.min_stock_g],
              ["target_stock_g", "Target (g)", row.target_stock_g],
              ["normal_price", "Normal price", row.normal_price],
              ["purchase_cost", "Purchase cost", row.purchase_cost],
              ["max_price", "Max price", row.max_price],
              ["max_price_per_kg", "Max $/kg", row.max_price_per_kg],
              ["min_reorder_qty", "Min reorder qty", row.min_reorder_qty],
              ["reorder_multiple", "Reorder multiple", row.reorder_multiple],
              ["lead_time_days", "Lead time (days)", row.lead_time_days],
              ["max_po_amount", "Max PO amount", row.max_po_amount],
            ].map(([name, label, value]) => (
              <div key={name} className="space-y-1">
                <Label>{label}</Label>
                <Input name={name} defaultValue={String(value)} />
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
          {row.spools.length === 0 && <p className="text-zinc-500">No rolls received yet. Print the receiving barcode and scan it when stock arrives.</p>}
          {row.spools.map((s) => (
            <Link key={s.id} href={`/filament/spools/${s.id}`} className="flex justify-between rounded-md bg-white/5 px-3 py-2 hover:bg-white/10">
              <span className="font-mono">{s.public_code}</span>
              <span>
                {formatGrams(s.remaining_weight_g)} · {s.is_sealed ? "Sealed" : "Open"} · {s.assigned_printer_name || s.location_name || "—"}
              </span>
            </Link>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
