"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { FilamentNav } from "@/components/filament-nav";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatMoney } from "@/lib/format";
import { toast } from "sonner";

type PO = {
  id: string;
  reference: string;
  status: string;
  supplier_name: string | null;
  total: number;
  created_at: string | null;
  ordered_at: string | null;
  expected_delivery: string | null;
  tracking: string;
  lines: { filament: string; quantity_ordered: number; spool_size_label: string | null; unit_price: number; price_per_kg: number }[];
};

type Spend = {
  monthly_budget: number;
  max_po_value: number;
  max_price_per_kg: number;
  max_price_per_spool: number;
  price_increase_tolerance_pct: number;
  full_auto_enabled: boolean;
};

const STATUSES = [
  "suggested",
  "draft",
  "awaiting_approval",
  "approved",
  "ordered",
  "shipped",
  "partially_received",
  "delivered",
  "cancelled",
];

export default function PurchasingPage() {
  const [rows, setRows] = useState<PO[]>([]);
  const [status, setStatus] = useState("");
  const [spend, setSpend] = useState<Spend | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const q = status ? `?status=${encodeURIComponent(status)}` : "";
      const [list, spendData] = await Promise.all([
        api<PO[]>(`/api/v1/purchasing${q}`),
        api<Spend>("/api/v1/purchasing/spend"),
      ]);
      setRows(Array.isArray(list) ? list : []);
      setSpend(spendData);
    } catch (err) {
      setRows([]);
      setError(err instanceof Error ? err.message : "Could not load purchasing");
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    load();
  }, [status]);

  async function evaluate() {
    try {
      const res = await api<{ created: unknown[] }>("/api/v1/purchasing/evaluate", { method: "POST" });
      toast.success(`Reorder pass finished (${res.created.length} actions).`);
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Evaluate failed");
    }
  }

  async function saveSpend() {
    if (!spend) return;
    try {
      await api("/api/v1/purchasing/spend", { method: "PUT", body: JSON.stringify(spend) });
      toast.success("Spending controls saved. Full Auto stays off unless you enable it here.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save spending controls");
    }
  }

  return (
    <div className="space-y-4">
      <FilamentNav />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          FarmOS never spends money automatically unless Full Auto is explicitly enabled in spending controls.
        </p>
        <Button variant="outline" onClick={evaluate}>
          Run reorder check
        </Button>
      </div>
      <div className="flex flex-wrap gap-1">
        <Button size="sm" variant={status === "" ? "default" : "outline"} onClick={() => setStatus("")}>
          All
        </Button>
        {STATUSES.map((s) => (
          <Button key={s} size="sm" variant={status === s ? "default" : "outline"} onClick={() => setStatus(s)}>
            {s.replaceAll("_", " ")}
          </Button>
        ))}
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>PO</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Supplier</TableHead>
            <TableHead>Product</TableHead>
            <TableHead>Qty</TableHead>
            <TableHead>Total</TableHead>
            <TableHead></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((p) => (
            <TableRow key={p.id}>
              <TableCell className="font-mono text-xs">{p.reference}</TableCell>
              <TableCell>{(p.status || "").replaceAll("_", " ")}</TableCell>
              <TableCell>{p.supplier_name || "—"}</TableCell>
              <TableCell className="text-xs">{(p.lines ?? []).map((l) => l.filament).join(", ")}</TableCell>
              <TableCell>{(p.lines ?? []).map((l) => `${l.quantity_ordered} × ${l.spool_size_label || ""}`).join(", ")}</TableCell>
              <TableCell>{formatMoney(p.total)}</TableCell>
              <TableCell>
                <Link href={`/filament/purchasing/${p.id}`} className="text-xs text-amber-300 hover:underline">
                  Open
                </Link>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {loading && <p className="text-sm text-zinc-500">Loading purchase orders…</p>}
      {error && (
        <p className="text-sm text-red-300">
          {error}{" "}
          <button type="button" className="underline" onClick={() => load()}>
            Retry
          </button>
        </p>
      )}
      {!loading && !error && rows.length === 0 && (
        <p className="text-sm text-zinc-500">No purchase orders in this filter.</p>
      )}
      {spend && (
        <Card>
          <CardHeader>
            <CardTitle>Spending controls</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-3">
            {(
              [
                ["monthly_budget", "Monthly budget"],
                ["max_po_value", "Max PO value"],
                ["max_price_per_kg", "Max $/kg"],
                ["max_price_per_spool", "Max $/spool"],
                ["price_increase_tolerance_pct", "Price increase tolerance %"],
              ] as const
            ).map(([key, label]) => (
              <div key={key} className="space-y-1">
                <Label>{label}</Label>
                <Input value={String(spend[key])} onChange={(e) => setSpend({ ...spend, [key]: Number(e.target.value) })} />
              </div>
            ))}
            <label className="flex items-center gap-2 text-sm sm:col-span-3">
              <input
                type="checkbox"
                checked={spend.full_auto_enabled}
                onChange={(e) => setSpend({ ...spend, full_auto_enabled: e.target.checked })}
              />
              Enable Full Auto ordering (off by default — FarmOS will still not order unknown products)
            </label>
            <Button onClick={saveSpend}>Save spending controls</Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
