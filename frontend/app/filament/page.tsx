"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { FilamentNav } from "@/components/filament-nav";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatGrams, formatMoney } from "@/lib/format";
import { ScanLine } from "lucide-react";
import { cn } from "@/lib/utils";
import { buttonVariants } from "@/components/ui/button";

type Dash = {
  totals: {
    physical_kg: number;
    sealed_rolls: number;
    open_rolls: number;
    installed_rolls: number;
    empty_rolls: number;
    inventory_value: number;
    avg_daily_g: number;
    low_stock: number;
  };
  by_material: Record<string, number>;
  by_color: Record<string, number>;
  by_manufacturer: Record<string, number>;
  products: {
    product: { id: string; manufacturer: string; material: string; color: string; barcode_id: string };
    stock: {
      physical_kg: number;
      sealed_rolls: number;
      open_rolls: number;
      installed_rolls: number;
      committed_kg: number;
      available_kg: number;
      below_minimum: boolean;
    };
    recommend: { needed: boolean; rolls: number; reason: string };
  }[];
  recent_usage: { id: string; at: string; spool: string | null; amount_g: number; reason: string; printer: string | null }[];
};

function Kpi({ label, value, warn }: { label: string; value: string | number; warn?: boolean }) {
  return (
    <div className="rounded-xl border border-white/8 bg-[#141a21] px-4 py-3">
      <div className="text-[11px] uppercase tracking-[0.16em] text-zinc-500">{label}</div>
      <div className={`mt-1 font-mono text-2xl font-semibold ${warn ? "text-amber-300" : "text-zinc-50"}`}>{value}</div>
    </div>
  );
}

export default function FilamentDashboard() {
  const [data, setData] = useState<Dash | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Dash>("/api/v1/filament/dashboard")
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"));
  }, []);

  if (error) return <div className="text-red-300">{error}</div>;
  if (!data) return <div className="text-zinc-500">Loading filament inventory…</div>;

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm text-muted-foreground">
            Filament profiles are saved once. Add rolls from a profile — each physical roll gets the next unique SPOOL number.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href="/scan" className={cn(buttonVariants({ size: "lg" }), "h-12 min-w-24 gap-2 text-base")}>
            <ScanLine className="size-5" />
            SCAN
          </Link>
          <Link href="/filament/products" className={cn(buttonVariants({ variant: "outline", size: "lg" }), "h-12")}>
            Profiles
          </Link>
        </div>
      </div>
      <FilamentNav />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <Kpi label="Total filament" value={`${data.totals.physical_kg.toFixed(1)} kg`} />
        <Kpi label="Sealed rolls" value={data.totals.sealed_rolls} />
        <Kpi label="Open rolls" value={data.totals.open_rolls} />
        <Kpi label="On printers" value={data.totals.installed_rolls} />
        <Kpi label="Empty rolls" value={data.totals.empty_rolls} />
        <Kpi label="Inventory value" value={formatMoney(data.totals.inventory_value)} />
        <Kpi label="Avg daily use" value={formatGrams(data.totals.avg_daily_g)} />
        <Kpi label="Low stock" value={data.totals.low_stock} warn={data.totals.low_stock > 0} />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>By material</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 text-sm">
            {Object.entries(data.by_material).map(([k, v]) => (
              <div key={k} className="flex justify-between">
                <span>{k}</span>
                <span className="font-mono">{v.toFixed(1)} kg</span>
              </div>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>By colour</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 text-sm">
            {Object.entries(data.by_color).map(([k, v]) => (
              <div key={k} className="flex justify-between">
                <span>{k}</span>
                <span className="font-mono">{v.toFixed(1)} kg</span>
              </div>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>By manufacturer</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 text-sm">
            {Object.entries(data.by_manufacturer).map(([k, v]) => (
              <div key={k} className="flex justify-between">
                <span>{k}</span>
                <span className="font-mono">{v.toFixed(1)} kg</span>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
      {data.products.length === 0 && (
        <Card>
          <CardHeader>
            <CardTitle>No filament in inventory</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            <p>
              Inventory starts empty. Create a filament profile, then add the physical rolls you actually have.
            </p>
            <Link href="/filament/products" className={cn(buttonVariants(), "inline-flex h-10 items-center")}>
              Create a filament profile
            </Link>
          </CardContent>
        </Card>
      )}
      <div className="grid gap-3 md:grid-cols-2">
        {data.products.map((row) => (
          <Card key={row.product.id} className={row.stock.below_minimum ? "border-amber-500/40" : ""}>
            <CardHeader>
              <CardTitle className="text-base">
                <Link href={`/filament/products/${row.product.id}`} className="hover:text-amber-200">
                  {row.product.color} {row.product.material}
                </Link>
              </CardTitle>
              <p className="text-xs text-zinc-500">
                {row.product.manufacturer} · {row.product.barcode_id}
              </p>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid grid-cols-2 gap-2 font-mono text-sm">
                <span>Physical {row.stock.physical_kg.toFixed(1)} kg</span>
                <span>Sealed {row.stock.sealed_rolls}</span>
                <span>Open {row.stock.open_rolls}</span>
                <span>Installed {row.stock.installed_rolls}</span>
                <span>Committed {row.stock.committed_kg.toFixed(1)} kg</span>
                <span className={row.stock.below_minimum ? "text-amber-300" : ""}>
                  Available {row.stock.available_kg.toFixed(1)} kg
                </span>
                {row.recommend.needed && (
                  <span className="col-span-2 text-xs text-amber-200">Reorder {row.recommend.rolls} rolls</span>
                )}
              </div>
              <Link href={`/filament/products/${row.product.id}?add=1`} className={cn(buttonVariants(), "flex h-11 w-full items-center justify-center")}>
                Add Rolls
              </Link>
            </CardContent>
          </Card>
        ))}
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Recent filament usage</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          {data.recent_usage.length === 0 && <p className="text-zinc-500">No usage transactions yet.</p>}
          {data.recent_usage.map((u) => (
            <div key={u.id} className="flex justify-between gap-3">
              <span>
                {u.spool || "spool"} · {u.reason}
                {u.printer ? ` · ${u.printer}` : ""}
              </span>
              <span className="font-mono">{formatGrams(u.amount_g)}</span>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
