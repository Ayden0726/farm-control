"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatPcs } from "@/lib/pcs";
import { toast } from "sonner";

export type HardwareForStock = {
  id: string;
  sku: string;
  name: string;
  unit_cost: number;
  storage_location: string;
};

export function AddHardwareStockPanel({
  item,
  defaultOpen = false,
  onReceived,
}: {
  item: HardwareForStock;
  defaultOpen?: boolean;
  onReceived?: () => void;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [qty, setQty] = useState("1");
  const [cost, setCost] = useState(item.unit_cost ? String(item.unit_cost) : "");
  const [location, setLocation] = useState(item.storage_location || "");
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState<number | null>(null);

  const count = Math.max(1, Math.round(Number(qty) || 1));

  async function receive() {
    setBusy(true);
    try {
      await api(`/api/v1/hardware/${item.id}/receive`, {
        method: "POST",
        body: JSON.stringify({
          quantity_pcs: count,
          unit_cost: cost === "" ? null : Number(cost),
          storage_location: location,
        }),
      });
      setLast(count);
      toast.success(`Received ${formatPcs(count)} of ${item.sku}`);
      onReceived?.();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not receive hardware");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="border-amber-500/30">
      <CardHeader className="flex flex-col items-stretch gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <CardTitle>Add stock</CardTitle>
          <p className="text-sm text-muted-foreground">
            {item.sku} · {item.name}. Count in pieces, not grams.
          </p>
        </div>
        {!open && last == null && (
          <Button className="h-12 w-full sm:h-11 sm:w-auto" onClick={() => setOpen(true)}>
            Add pcs
          </Button>
        )}
      </CardHeader>
      {(open || last != null) && (
        <CardContent className="space-y-4">
          {last == null && (
            <>
              <p className="text-sm text-zinc-400">
                SKU, name, and supplier stay on this profile. Enter how many pieces arrived and the cost per piece.
              </p>
              <div className="grid gap-3 sm:grid-cols-3">
                <div className="space-y-1">
                  <Label className="text-xs">Pieces received</Label>
                  <Input className="h-12 text-lg" inputMode="numeric" min={1} value={qty} onChange={(e) => setQty(e.target.value)} />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Cost per piece</Label>
                  <Input className="h-12 text-lg" inputMode="decimal" value={cost} onChange={(e) => setCost(e.target.value)} />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Storage location</Label>
                  <Input className="h-12 text-lg" value={location} onChange={(e) => setLocation(e.target.value)} placeholder="Bin A, shelf 2" />
                </div>
              </div>
              <Button className="h-12 w-full text-base" disabled={busy} onClick={receive}>
                {busy ? "Receiving…" : `Receive ${formatPcs(count)}`}
              </Button>
            </>
          )}
          {last != null && (
            <div className="space-y-3">
              <p className="text-base font-semibold">{formatPcs(last)} added to on-hand</p>
              <Button
                variant="ghost"
                className="w-full"
                onClick={() => {
                  setLast(null);
                  setOpen(true);
                }}
              >
                Receive more of this SKU
              </Button>
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}
