"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { FilamentNav } from "@/components/filament-nav";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";

type Product = {
  id: string;
  barcode_id: string;
  manufacturer: string;
  material: string;
  color: string;
  spool_size_label: string;
};

export default function InventoryLabelsPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [copies, setCopies] = useState<Record<string, number>>({});
  const [width, setWidth] = useState("54");
  const [height, setHeight] = useState("70");
  const [columns, setColumns] = useState("3");

  useEffect(() => {
    api<Product[]>("/api/v1/filament/products").then(setProducts);
  }, []);

  async function generate() {
    const items = products
      .filter((p) => (copies[p.id] || 0) > 0)
      .map((p) => ({ id: p.id, copies: copies[p.id] }));
    if (items.length === 0) {
      toast.error("Select at least one product and a copy count.");
      return;
    }
    try {
      const res = await api<{ html: string }>("/api/v1/labels/sheet", {
        method: "POST",
        body: JSON.stringify({
          kind: "product",
          items,
          width_mm: Number(width),
          height_mm: Number(height),
          columns: Number(columns),
        }),
      });
      const w = window.open("", "_blank");
      if (!w) {
        toast.error("Allow pop-ups to print the label sheet.");
        return;
      }
      w.document.write(res.html);
      w.document.close();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not generate labels");
    }
  }

  return (
    <div className="space-y-4">
      <FilamentNav />
      <div>
        <h2 className="text-lg font-semibold">Inventory Labels</h2>
        <p className="text-sm text-muted-foreground">
          Print reusable FarmOS receiving barcodes for shelves, the receiving bench, or a binder. These are product codes, not unique spool IDs.
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="space-y-1">
          <Label>Label width (mm)</Label>
          <Input value={width} onChange={(e) => setWidth(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label>Label height (mm)</Label>
          <Input value={height} onChange={(e) => setHeight(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label>Columns</Label>
          <Input value={columns} onChange={(e) => setColumns(e.target.value)} />
        </div>
      </div>
      <div className="space-y-2">
        {products.map((p) => (
          <label key={p.id} className="flex items-center justify-between gap-3 rounded-lg border border-white/8 px-3 py-2">
            <span>
              {p.color} {p.material} {p.spool_size_label}
              <span className="block font-mono text-[11px] text-zinc-500">{p.barcode_id}</span>
            </span>
            <Input
              className="w-20"
              inputMode="numeric"
              value={copies[p.id] ?? 0}
              onChange={(e) => setCopies({ ...copies, [p.id]: Number(e.target.value) })}
            />
          </label>
        ))}
      </div>
      <Button className="h-12 w-full sm:w-auto" onClick={generate}>
        Generate Label Sheet
      </Button>
    </div>
  );
}
