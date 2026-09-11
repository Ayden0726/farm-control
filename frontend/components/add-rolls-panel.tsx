"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { LABEL_PRESETS, LabelLayout, labelsPrintHref } from "@/lib/labels";

export type ProfileForRolls = {
  id: string;
  manufacturer: string;
  material: string;
  color: string;
  spool_size_label: string;
  purchase_cost: number;
  normal_price?: number;
  preferred_supplier_id?: string | null;
};

type Loc = { id: string; name: string };
type Created = { id: string; public_code: string };

type ReceiveResult = {
  message: string;
  print_path: string;
  spools: Created[];
};

export function AddRollsPanel({
  product,
  defaultOpen = false,
  onCreated,
}: {
  product: ProfileForRolls;
  defaultOpen?: boolean;
  onCreated?: () => void;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [qty, setQty] = useState("5");
  const [cost, setCost] = useState(String(product.normal_price || product.purchase_cost || ""));
  const [locationId, setLocationId] = useState("");
  const [locs, setLocs] = useState<Loc[]>([]);
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<Created[] | null>(null);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [layout, setLayout] = useState<LabelLayout>("sheet");

  useEffect(() => {
    api<Loc[]>("/api/v1/filament/locations").then((rows) => {
      setLocs(rows);
      const sealed = rows.find((r) => /sealed|shelf/i.test(r.name));
      if (sealed) setLocationId(sealed.id);
      else if (rows[0]) setLocationId(rows[0].id);
    }).catch(() => undefined);
  }, []);

  useEffect(() => {
    setCost(String(product.normal_price || product.purchase_cost || ""));
  }, [product.id, product.normal_price, product.purchase_cost]);

  const count = Math.max(1, Number(qty) || 1);
  const ids = (created || []).filter((s) => selected[s.id] !== false).map((s) => s.id);
  const selectedIds = (created || []).filter((s) => selected[s.id]).map((s) => s.id);

  async function create() {
    setBusy(true);
    try {
      const res = await api<ReceiveResult>("/api/v1/filament/receive", {
        method: "POST",
        body: JSON.stringify({
          product_id: product.id,
          quantity: count,
          cost_per_spool: cost === "" ? null : Number(cost),
          location_id: locationId || null,
          supplier_id: product.preferred_supplier_id,
        }),
      });
      setCreated(res.spools);
      setSelected(Object.fromEntries(res.spools.map((s) => [s.id, true])));
      toast.success(res.message);
      onCreated?.();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not create rolls");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="border-amber-500/30">
      <CardHeader className="flex flex-row items-center justify-between gap-3">
        <div>
          <CardTitle>Add New Rolls</CardTitle>
          <p className="text-sm text-muted-foreground">
            {product.manufacturer} {product.material} — {product.color} — {product.spool_size_label}
          </p>
        </div>
        {!open && !created && (
          <Button className="h-11" onClick={() => setOpen(true)}>
            Add New Rolls
          </Button>
        )}
      </CardHeader>
      {(open || created) && (
        <CardContent className="space-y-4">
          {!created && (
            <>
              <p className="text-sm text-zinc-400">
                Manufacturer, material, colour, and size come from this saved profile. Only quantity, price, and location are needed.
              </p>
              <div className="grid gap-3 sm:grid-cols-3">
                <div className="space-y-1">
                  <Label className="text-xs">Quantity received</Label>
                  <Input className="h-12 text-lg" inputMode="numeric" value={qty} onChange={(e) => setQty(e.target.value)} />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Cost per roll</Label>
                  <Input className="h-12 text-lg" inputMode="decimal" value={cost} onChange={(e) => setCost(e.target.value)} />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Storage location</Label>
                  <select
                    className="h-12 w-full rounded-lg border border-input bg-transparent px-3"
                    value={locationId}
                    onChange={(e) => setLocationId(e.target.value)}
                  >
                    <option value="">Unassigned</option>
                    {locs.map((l) => (
                      <option key={l.id} value={l.id}>
                        {l.name}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              <Button className="h-12 w-full text-base" disabled={busy} onClick={create}>
                {busy ? "Creating…" : `Create ${count} Roll${count === 1 ? "" : "s"}`}
              </Button>
            </>
          )}
          {created && (
            <div className="space-y-3">
              <p className="text-base font-semibold">{created.length} New Rolls Created</p>
              <ul className="space-y-1">
                {created.map((s) => (
                  <li key={s.id} className="flex items-center gap-2 font-mono text-sm">
                    <input
                      type="checkbox"
                      checked={!!selected[s.id]}
                      onChange={(e) => setSelected({ ...selected, [s.id]: e.target.checked })}
                    />
                    <Link href={`/filament/spools/${s.id}`} className="hover:text-amber-200">
                      {s.public_code}
                    </Link>
                  </li>
                ))}
              </ul>
              <div className="flex flex-wrap gap-2">
                {(Object.keys(LABEL_PRESETS) as LabelLayout[]).map((key) => (
                  <Button key={key} size="sm" variant={layout === key ? "default" : "outline"} onClick={() => setLayout(key)}>
                    {LABEL_PRESETS[key].label}
                  </Button>
                ))}
              </div>
              <p className="text-xs text-zinc-500">{LABEL_PRESETS[layout].hint}. Reprint later from any spool — the number does not change.</p>
              <div className="flex flex-col gap-2 sm:flex-row">
                <Link href={labelsPrintHref("spool", created.map((s) => s.id), { layout, auto: true })} className={cn(buttonVariants(), "flex h-12 flex-1 items-center justify-center")}>
                  Print All {created.length} Labels
                </Link>
                <Link
                  href={labelsPrintHref("spool", selectedIds.length ? selectedIds : ids, { layout, auto: true })}
                  className={cn(buttonVariants({ variant: "outline" }), "flex h-12 flex-1 items-center justify-center")}
                >
                  Print Selected
                </Link>
              </div>
              <Button
                variant="ghost"
                className="w-full"
                onClick={() => {
                  setCreated(null);
                  setOpen(true);
                }}
              >
                Create more rolls of this profile
              </Button>
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}
