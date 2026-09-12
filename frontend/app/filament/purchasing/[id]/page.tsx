"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { FilamentNav } from "@/components/filament-nav";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatMoney } from "@/lib/format";
import { toast } from "sonner";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { DryingChoice, DryingStatusValue } from "@/components/drying-choice";

type PO = {
  id: string;
  reference: string;
  status: string;
  supplier_name: string | null;
  supplier_website: string | null;
  reason: string;
  notes: string;
  tracking: string;
  total: number;
  lines: {
    id: string;
    filament: string;
    quantity_ordered: number;
    quantity_received: number;
    outstanding: number;
    unit_price: number;
    price_per_kg: number;
    spool_size_label: string | null;
    current_stock_kg?: number;
    committed_kg?: number;
    available_kg?: number;
    target_kg?: number;
    supplier_url: string;
  }[];
};

export default function PurchaseOrderPage() {
  const params = useParams<{ id: string }>();
  const [po, setPo] = useState<PO | null>(null);
  const [qty, setQty] = useState("");
  const [price, setPrice] = useState("");
  const [recvQty, setRecvQty] = useState("");
  const [recvDrying, setRecvDrying] = useState<DryingStatusValue>("needs_drying");
  const [recvLocationId, setRecvLocationId] = useState("");
  const [locs, setLocs] = useState<{ id: string; name: string; kind?: string }[]>([]);
  const [printPath, setPrintPath] = useState<string | null>(null);

  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setError(null);
      const row = await api<PO>(`/api/v1/purchasing/${params.id}`);
      row.lines = row.lines ?? [];
      setPo(row);
      if (row.lines[0]) {
        setQty(String(row.lines[0].quantity_ordered));
        setPrice(String(row.lines[0].unit_price));
        setRecvQty(String(row.lines[0].outstanding || row.lines[0].quantity_ordered));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load this purchase order");
    }
  }
  useEffect(() => {
    load();
    api<{ id: string; name: string; kind?: string }[]>("/api/v1/filament/locations")
      .then((rows) => {
        setLocs(rows);
        const sealed = rows.find((r) => r.kind === "sealed" || /sealed|shelf/i.test(r.name));
        if (sealed) setRecvLocationId(sealed.id);
      })
      .catch(() => undefined);
  }, [params.id]);

  async function act(path: string, body?: unknown) {
    try {
      const res = await api<PO | { purchase_order: PO; print_path: string; message: string }>(path, {
        method: "POST",
        body: body ? JSON.stringify(body) : undefined,
      });
      if (res && typeof res === "object" && "print_path" in res) {
        setPrintPath(res.print_path);
        toast.success(res.message);
        setPo(res.purchase_order);
        return;
      }
      load();
      toast.success("Updated");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    }
  }

  if (error) {
    return (
      <div className="space-y-3">
        <FilamentNav />
        <p className="text-sm text-red-300">{error}</p>
        <Button variant="outline" onClick={() => load()}>
          Retry
        </Button>
      </div>
    );
  }
  if (!po) return <div className="text-zinc-500">Loading purchase order…</div>;
  const line = (po.lines ?? [])[0];

  return (
    <div className="space-y-4">
      <FilamentNav />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">{po.reference}</h2>
          <p className="text-sm text-zinc-400">{po.status.replaceAll("_", " ")} · {po.supplier_name || "No supplier"}</p>
        </div>
        {po.supplier_website && (
          <a href={po.supplier_website} target="_blank" rel="noreferrer" className={cn(buttonVariants({ variant: "outline" }))}>
            Open Supplier Page
          </a>
        )}
      </div>
      <Card>
        <CardHeader>
          <CardTitle>{line?.filament}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2 text-sm sm:grid-cols-2">
          <div>Quantity ordered: {line?.quantity_ordered} × {line?.spool_size_label}</div>
          <div>Received: {line?.quantity_received} · outstanding {line?.outstanding}</div>
          <div>Cost per spool: {formatMoney(line?.unit_price || 0)}</div>
          <div>Cost per kg: {formatMoney(line?.price_per_kg || 0)}</div>
          <div>Current stock: {line?.current_stock_kg?.toFixed(1)} kg</div>
          <div>Committed: {line?.committed_kg?.toFixed(1)} kg</div>
          <div>Available: {line?.available_kg?.toFixed(1)} kg</div>
          <div>Target: {line?.target_kg?.toFixed(1)} kg</div>
          <div className="sm:col-span-2">Total {formatMoney(po.total)}</div>
          <div className="sm:col-span-2 text-zinc-400">{po.reason}</div>
        </CardContent>
      </Card>
      {["suggested", "draft", "awaiting_approval"].includes(po.status) && (
        <div className="flex flex-wrap gap-2">
          <Button className="h-11" onClick={() => act(`/api/v1/purchasing/${po.id}/approve`)}>
            Approve
          </Button>
          <Button variant="outline" className="h-11" onClick={() => act(`/api/v1/purchasing/${po.id}/modify`, { quantity: Number(qty), unit_price: Number(price) })}>
            Modify
          </Button>
          <Button variant="destructive" className="h-11" onClick={() => act(`/api/v1/purchasing/${po.id}/reject`)}>
            Reject
          </Button>
        </div>
      )}
      {["suggested", "draft", "awaiting_approval"].includes(po.status) && (
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <Label>Quantity</Label>
            <Input value={qty} onChange={(e) => setQty(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label>Unit price</Label>
            <Input value={price} onChange={(e) => setPrice(e.target.value)} />
          </div>
        </div>
      )}
      {po.status === "approved" && (
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => act(`/api/v1/purchasing/${po.id}/mark-ordered`)}>Mark ordered</Button>
          <Button variant="outline" onClick={() => act(`/api/v1/purchasing/${po.id}/place-order`)}>
            Place via supplier adapter
          </Button>
        </div>
      )}
      {["ordered", "shipped", "partially_received", "approved"].includes(po.status) && (
        <Card>
          <CardHeader>
            <CardTitle>Receive order</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-muted-foreground">
              No barcode scan required — FarmOS already knows the filament type. Partial deliveries stay open until complete.
            </p>
            <div className="space-y-1">
              <Label>Quantity received now</Label>
              <Input className="h-12" value={recvQty} onChange={(e) => setRecvQty(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label>Storage location</Label>
              <select
                className="h-12 w-full rounded-lg border border-input bg-transparent px-3"
                value={recvLocationId}
                onChange={(e) => setRecvLocationId(e.target.value)}
              >
                <option value="">Unassigned</option>
                {locs.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name}
                  </option>
                ))}
              </select>
            </div>
            <DryingChoice
              value={recvDrying}
              onChange={(next) => {
                setRecvDrying(next);
                if (next === "drying") {
                  const dryer = locs.find((r) => r.kind === "dryer" || /dryer/i.test(r.name));
                  if (dryer) setRecvLocationId(dryer.id);
                }
              }}
            />
            <Button
              className="h-12 w-full"
              onClick={() =>
                act(`/api/v1/purchasing/${po.id}/receive`, {
                  quantity: Number(recvQty),
                  location_id: recvLocationId || null,
                  drying_status: recvDrying,
                })
              }
            >
              Receive {recvQty} spools
            </Button>
            {printPath && (
              <Link href={printPath} className={cn(buttonVariants(), "flex h-12 items-center justify-center")}>
                Print All Spool Labels
              </Link>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
