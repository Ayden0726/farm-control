"use client";

import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Part, Product } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";

export default function ProductsPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [parts, setParts] = useState<Part[]>([]);
  const [open, setOpen] = useState(false);
  const [sku, setSku] = useState("");
  const [name, setName] = useState("");
  const [wooId, setWooId] = useState("");
  const [bom, setBom] = useState<{ part_id: string; quantity: number; is_optional: boolean }[]>([
    { part_id: "", quantity: 1, is_optional: false },
  ]);
  const [partSku, setPartSku] = useState("");
  const [partName, setPartName] = useState("");

  async function load() {
    setProducts(await api<Product[]>("/api/v1/products"));
    setParts(await api<Part[]>("/api/v1/parts"));
  }
  useEffect(() => {
    load();
  }, []);

  async function addPart(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/api/v1/parts", {
        method: "POST",
        body: JSON.stringify({ sku: partSku, name: partName }),
      });
      toast.success("Part added");
      setPartSku("");
      setPartName("");
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    }
  }

  async function createProduct(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/api/v1/products", {
        method: "POST",
        body: JSON.stringify({
          sku,
          name,
          woocommerce_product_id: wooId ? Number(wooId) : null,
          bom: bom.filter((b) => b.part_id),
        }),
      });
      toast.success("Product saved. Future SKUs can be added here without code changes.");
      setOpen(false);
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          Bills of materials drive order explosion. Optional accessories are not auto-produced.
        </p>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger render={<Button />}>Add product</DialogTrigger>
          <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
            <DialogHeader>
              <DialogTitle>New product + BOM</DialogTitle>
            </DialogHeader>
            <form onSubmit={createProduct} className="space-y-3">
              <Input placeholder="SKU" value={sku} onChange={(e) => setSku(e.target.value)} required />
              <Input placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} required />
              <Input placeholder="WooCommerce product ID (optional)" value={wooId} onChange={(e) => setWooId(e.target.value)} />
              {bom.map((row, idx) => (
                <div key={idx} className="grid grid-cols-[1fr_70px_auto] gap-2">
                  <select
                    className="h-8 rounded-lg border border-input bg-transparent px-2 text-sm"
                    value={row.part_id}
                    onChange={(e) => setBom((c) => c.map((x, i) => (i === idx ? { ...x, part_id: e.target.value } : x)))}
                  >
                    <option value="">Part…</option>
                    {parts.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.sku}
                      </option>
                    ))}
                  </select>
                  <Input
                    type="number"
                    value={row.quantity}
                    onChange={(e) =>
                      setBom((c) => c.map((x, i) => (i === idx ? { ...x, quantity: Number(e.target.value) } : x)))
                    }
                  />
                  <label className="flex items-center gap-1 text-xs">
                    <input
                      type="checkbox"
                      checked={row.is_optional}
                      onChange={(e) =>
                        setBom((c) => c.map((x, i) => (i === idx ? { ...x, is_optional: e.target.checked } : x)))
                      }
                    />
                    opt
                  </label>
                </div>
              ))}
              <Button type="button" variant="outline" onClick={() => setBom((c) => [...c, { part_id: "", quantity: 1, is_optional: false }])}>
                Add BOM line
              </Button>
              <Button type="submit" className="w-full">
                Save product
              </Button>
            </form>
          </DialogContent>
        </Dialog>
      </div>
      <form onSubmit={addPart} className="flex flex-wrap gap-2 rounded-xl border border-white/8 p-3">
        <Input placeholder="New part SKU" value={partSku} onChange={(e) => setPartSku(e.target.value)} required />
        <Input placeholder="Name" value={partName} onChange={(e) => setPartName(e.target.value)} required />
        <Button type="submit" variant="outline">
          Add part
        </Button>
      </form>
      <div className="grid gap-4 md:grid-cols-2">
        {products.map((p) => (
          <Card key={p.id}>
            <CardHeader>
              <CardTitle>
                {p.sku} · {p.name}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-1 text-sm">
              {p.bom.map((b) => (
                <div key={b.id} className="flex justify-between">
                  <span>
                    {b.part_sku} {b.is_optional ? "(optional)" : ""}
                  </span>
                  <span className="font-mono">×{b.quantity}</span>
                </div>
              ))}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
