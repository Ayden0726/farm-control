"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";

type Kind = "product" | "spool" | "printer" | "bin";

export default function LabelsHubPage() {
  const [kind, setKind] = useState<Kind>("product");
  const [items, setItems] = useState<{ id: string; label: string }[]>([]);
  const [selected, setSelected] = useState<Record<string, boolean>>({});

  useEffect(() => {
    async function load() {
      setSelected({});
      if (kind === "product") {
        const rows = await api<{ id: string; manufacturer: string; material: string; color: string }[]>("/api/v1/filament/products");
        setItems(rows.map((r) => ({ id: r.id, label: `${r.manufacturer} ${r.material} ${r.color}` })));
      } else if (kind === "printer") {
        const rows = await api<{ id: string; name: string }[]>("/api/v1/printers");
        setItems(rows.map((r) => ({ id: r.id, label: r.name })));
      } else if (kind === "bin") {
        const rows = await api<{ id: string; name: string }[]>("/api/v1/bins");
        setItems(rows.map((r) => ({ id: r.id, label: r.name })));
      } else {
        const rows = await api<{ id: string; public_code?: string; name: string }[]>("/api/v1/filament");
        setItems(rows.map((r) => ({ id: r.id, label: r.public_code || r.name })));
      }
    }
    load();
  }, [kind]);

  async function printSelected() {
    const ids = Object.entries(selected).filter(([, v]) => v).map(([k]) => k);
    if (!ids.length) {
      toast.error("Select labels to print");
      return;
    }
    const res = await api<{ html: string }>("/api/v1/labels/sheet", {
      method: "POST",
      body: JSON.stringify({ kind, items: ids.map((id) => ({ id, copies: 1 })), width_mm: 54, height_mm: 70, columns: 3 }),
    });
    const w = window.open("", "_blank");
    if (!w) return;
    w.document.write(res.html);
    w.document.close();
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">FarmOS labels</h2>
        <p className="text-sm text-muted-foreground">
          Print FarmOS-generated QR and Code 128 labels for products, spools, printers, and bins. No external barcode website.
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        {(["product", "spool", "printer", "bin"] as Kind[]).map((k) => (
          <Button key={k} variant={kind === k ? "default" : "outline"} onClick={() => setKind(k)}>
            {k === "product" ? "Filament types" : k === "spool" ? "Spools" : k === "printer" ? "Printers" : "Bins"}
          </Button>
        ))}
      </div>
      <div className="grid gap-2 md:grid-cols-2">
        {items.map((item) => (
          <label key={item.id} className="flex items-center gap-2 rounded-lg border border-white/8 px-3 py-2 text-sm">
            <input
              type="checkbox"
              checked={!!selected[item.id]}
              onChange={(e) => setSelected({ ...selected, [item.id]: e.target.checked })}
            />
            {item.label}
          </label>
        ))}
      </div>
      <Button className="h-11" onClick={printSelected}>
        Print selected
      </Button>
    </div>
  );
}
