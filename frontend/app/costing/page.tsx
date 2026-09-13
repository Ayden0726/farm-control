"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatFilamentRate, formatGramsKnown, formatMoneyKnown } from "@/lib/format";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

type PartCost = {
  part_id: string;
  sku: string;
  name: string;
  gcode_filename: string | null;
  grams: number | null;
  plate_grams: number | null;
  quantity_per_file: number;
  grams_source: "actual" | "slicer" | "filename" | "missing";
  grams_label: string;
  filament_cost_per_g: number | null;
  filament_cost_per_kg: number | null;
  rate_source: "spool" | "profile" | "missing";
  rate_label: string | null;
  spool_code: string | null;
  filament_profile: string | null;
  filament_cost: number | null;
  electricity: number;
  failure_allowance: number;
  machine_time: number;
  labour: number;
  estimated_cost: number | null;
  costed: boolean;
  missing_reason: string | null;
  missing_message: string | null;
};

type ProductCost = {
  product_id: string;
  sku: string;
  name: string;
  parts: (PartCost & { bom_qty: number; line_total: number | null })[];
  hardware: { sku: string; name: string; qty: number; unit_cost: number; line_total: number }[];
  parts_cost: number | null;
  hardware_cost: number;
  estimated_cost: number | null;
  costed: boolean;
  missing_message: string | null;
};

type Profit = {
  orders: {
    reference: string;
    revenue: number;
    estimated_total_cost: number | null;
    gross_profit: number | null;
    gross_margin_pct: number | null;
    costed?: boolean;
  }[];
  by_week: { period: string; revenue: number; cost: number; profit: number }[];
};

function gramsBadge(source: PartCost["grams_source"]) {
  if (source === "actual") return { label: "Actual", className: "bg-emerald-500/15 text-emerald-200 ring-1 ring-emerald-500/30" };
  if (source === "slicer") return { label: "Slicer estimate", className: "bg-sky-500/15 text-sky-200 ring-1 ring-sky-500/30" };
  if (source === "filename") return { label: "Filename estimate", className: "bg-amber-500/15 text-amber-200 ring-1 ring-amber-400/30" };
  return { label: "No grams", className: "bg-zinc-700/40 text-zinc-400 ring-1 ring-zinc-600/40" };
}

function GramsPill({ source }: { source: PartCost["grams_source"] }) {
  const badge = gramsBadge(source);
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${badge.className}`}>
      {badge.label}
    </span>
  );
}

function PartMissing({ part }: { part: PartCost }) {
  const message =
    part.missing_message ||
    (part.missing_reason === "missing_gcode"
      ? "No G-code tagged to this part — upload a file in Library"
      : "No filament estimate on this G-code — re-read estimates in Library");
  return (
    <div className="max-w-[28rem] whitespace-normal text-xs text-amber-200/90">
      {message}{" "}
      <Link href="/library" className="underline underline-offset-2">
        Open Library
      </Link>
    </div>
  );
}

function PartBreakdown({ part }: { part: PartCost }) {
  const extras = [
    part.electricity ? `elec ${formatMoneyKnown(part.electricity)}` : null,
    part.failure_allowance ? `fail ${formatMoneyKnown(part.failure_allowance)}` : null,
    part.machine_time ? `machine ${formatMoneyKnown(part.machine_time)}` : null,
    part.labour ? `labour ${formatMoneyKnown(part.labour)}` : null,
  ].filter(Boolean);
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-2">
        <GramsPill source={part.grams_source} />
        <span className="font-mono text-sm">{formatGramsKnown(part.grams)}</span>
        {part.quantity_per_file > 1 && part.plate_grams ? (
          <span className="text-[11px] text-zinc-500">
            {formatGramsKnown(part.plate_grams)} plate ÷ {part.quantity_per_file}
          </span>
        ) : null}
      </div>
      <div className="text-xs text-zinc-400">{part.grams_label}</div>
      {part.costed ? (
        <>
          <div className="font-mono text-sm">{formatFilamentRate(part.filament_cost_per_g)}</div>
          <div className="text-[11px] text-zinc-500">{part.rate_label}</div>
          <div className="text-sm">
            Filament {formatMoneyKnown(part.filament_cost)}
            {extras.length ? ` · ${extras.join(" · ")}` : ""}
          </div>
        </>
      ) : (
        <PartMissing part={part} />
      )}
    </div>
  );
}

export default function CostingPage() {
  const [parts, setParts] = useState<PartCost[] | null>(null);
  const [products, setProducts] = useState<ProductCost[] | null>(null);
  const [profit, setProfit] = useState<Profit | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api<PartCost[]>("/api/v1/costing/parts"),
      api<ProductCost[]>("/api/v1/costing/products"),
      api<Profit>("/api/v1/costing/profitability"),
    ])
      .then(([partRows, productRows, profitRows]) => {
        if (cancelled) return;
        setParts(partRows);
        setProducts(productRows);
        setProfit(profitRows);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load costing");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-6 text-sm text-red-200">
        {error}
      </div>
    );
  }

  if (!parts) {
    return <div className="text-zinc-500">Loading part costs…</div>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Costing</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Part cost is filament grams for that part times the filament price per gram, plus electricity, machine time,
          labour, and a failure allowance when those are enabled. A completed job uses the grams actually consumed.
          Otherwise Print FarmOS uses the slicer estimate on the G-code, then a filename gram token.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Cost per part</CardTitle>
        </CardHeader>
        <CardContent>
          {parts.length === 0 ? (
            <p className="text-sm text-zinc-500">No active parts yet. Add parts from Products or Library.</p>
          ) : (
            <>
              <div className="space-y-3 md:hidden">
                {parts.map((p) => (
                  <div key={p.part_id} className="space-y-2 rounded-xl border border-white/8 bg-[#141a21] p-3">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="font-medium">{p.sku}</div>
                        <div className="text-xs text-zinc-500">{p.name}</div>
                        {p.gcode_filename ? (
                          <div className="mt-1 truncate font-mono text-[11px] text-zinc-500">{p.gcode_filename}</div>
                        ) : null}
                      </div>
                      <div className="text-right font-mono text-base">
                        {p.costed ? formatMoneyKnown(p.estimated_cost) : "—"}
                      </div>
                    </div>
                    <PartBreakdown part={p} />
                  </div>
                ))}
              </div>
              <div className="hidden md:block">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Part</TableHead>
                      <TableHead>Grams</TableHead>
                      <TableHead>Filament rate</TableHead>
                      <TableHead>Filament</TableHead>
                      <TableHead>Extras</TableHead>
                      <TableHead>Part cost</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {parts.map((p) => (
                      <TableRow key={p.part_id}>
                        <TableCell className="whitespace-normal">
                          <div className="font-medium">{p.sku}</div>
                          <div className="text-xs text-zinc-500">{p.name}</div>
                          {p.gcode_filename ? (
                            <div className="mt-1 font-mono text-[11px] text-zinc-500">{p.gcode_filename}</div>
                          ) : null}
                        </TableCell>
                        <TableCell className="whitespace-normal">
                          <div className="flex flex-wrap items-center gap-2">
                            <GramsPill source={p.grams_source} />
                            <span className="font-mono">{formatGramsKnown(p.grams)}</span>
                          </div>
                          <div className="mt-1 max-w-[16rem] text-[11px] text-zinc-500">{p.grams_label}</div>
                          {p.quantity_per_file > 1 && p.plate_grams ? (
                            <div className="text-[11px] text-zinc-500">
                              {formatGramsKnown(p.plate_grams)} plate ÷ {p.quantity_per_file}
                            </div>
                          ) : null}
                        </TableCell>
                        <TableCell className="whitespace-normal">
                          {p.costed || p.filament_cost_per_g ? (
                            <>
                              <div className="font-mono text-sm">{formatFilamentRate(p.filament_cost_per_g)}</div>
                              <div className="mt-1 max-w-[16rem] text-[11px] text-zinc-500">{p.rate_label}</div>
                            </>
                          ) : (
                            <span className="text-zinc-500">—</span>
                          )}
                        </TableCell>
                        <TableCell className="whitespace-normal">
                          {p.costed ? (
                            formatMoneyKnown(p.filament_cost)
                          ) : (
                            <PartMissing part={p} />
                          )}
                        </TableCell>
                        <TableCell className="text-xs text-zinc-400">
                          {formatMoneyKnown(p.electricity)} elec
                          <div>fail {formatMoneyKnown(p.failure_allowance)}</div>
                          <div>machine {formatMoneyKnown(p.machine_time)}</div>
                          {p.labour ? <div>labour {formatMoneyKnown(p.labour)}</div> : null}
                        </TableCell>
                        <TableCell className="font-mono">
                          {p.costed ? formatMoneyKnown(p.estimated_cost) : "—"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Catalog products</CardTitle>
        </CardHeader>
        <CardContent>
          {!products ? (
            <p className="text-sm text-zinc-500">Loading product costs…</p>
          ) : products.length === 0 ? (
            <p className="text-sm text-zinc-500">No active catalog products yet.</p>
          ) : (
            <div className="space-y-4">
              {products.map((product) => (
                <div key={product.product_id} className="rounded-xl border border-white/8 p-3">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <div className="font-medium">
                        {product.sku} · {product.name}
                      </div>
                      {!product.costed && product.missing_message ? (
                        <div className="mt-1 text-xs text-amber-200/90">{product.missing_message}</div>
                      ) : null}
                    </div>
                    <div className="font-mono text-base">
                      {product.costed ? formatMoneyKnown(product.estimated_cost) : "—"}
                    </div>
                  </div>
                  <div className="mt-3 space-y-2 text-sm">
                    {product.parts.map((line) => (
                      <div key={`${product.product_id}-${line.part_id}`} className="flex flex-wrap justify-between gap-2">
                        <span>
                          {line.bom_qty} × {line.sku}
                          <span className="ml-2 text-xs text-zinc-500">{line.name}</span>
                        </span>
                        <span className="font-mono">
                          {line.costed ? formatMoneyKnown(line.line_total) : "—"}
                        </span>
                      </div>
                    ))}
                    {product.hardware.map((hw) => (
                      <div key={`${product.product_id}-hw-${hw.sku}`} className="flex flex-wrap justify-between gap-2 text-zinc-400">
                        <span>
                          {hw.qty} × {hw.sku} {hw.name}
                        </span>
                        <span className="font-mono">{formatMoneyKnown(hw.line_total)}</span>
                      </div>
                    ))}
                    <div className="flex justify-between text-xs text-zinc-500">
                      <span>Printed parts {formatMoneyKnown(product.parts_cost)}</span>
                      <span>Hardware {formatMoneyKnown(product.hardware_cost)}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Order profitability</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {!profit ? (
            <p className="text-zinc-500">Loading order profitability…</p>
          ) : (profit.orders || []).length === 0 && (profit.by_week || []).length === 0 ? (
            <p className="text-zinc-500">No orders with revenue yet. Profitability appears after WooCommerce or Shopify orders land.</p>
          ) : (
            <>
              {(profit.orders || []).map((o) => (
                <div key={o.reference} className="flex flex-col gap-1 sm:flex-row sm:justify-between">
                  <span>Order {o.reference}</span>
                  <span className="font-mono text-xs sm:text-sm">
                    {formatMoneyKnown(o.revenue)} · cost{" "}
                    {o.costed === false ? "incomplete" : formatMoneyKnown(o.estimated_total_cost)} · profit{" "}
                    {o.costed === false ? "—" : formatMoneyKnown(o.gross_profit)}
                    {o.gross_margin_pct != null ? ` (${o.gross_margin_pct}%)` : ""}
                  </span>
                </div>
              ))}
              {(profit.by_week || []).map((w) => (
                <div key={w.period} className="text-zinc-400">
                  {w.period}: {formatMoneyKnown(w.profit)} profit on {formatMoneyKnown(w.revenue)}
                </div>
              ))}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
