"use client";

import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Part, Product } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";

type BomRow = { part_id: string; quantity: number; is_optional: boolean };
type HwRow = { hardware_item_id: string; quantity: number; is_optional: boolean };

function emptyBom(): BomRow[] {
  return [{ part_id: "", quantity: 1, is_optional: false }];
}

export default function ProductsPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [parts, setParts] = useState<Part[]>([]);
  const [hardware, setHardware] = useState<{ id: string; sku: string; name: string }[]>([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Product | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Product | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [sku, setSku] = useState("");
  const [name, setName] = useState("");
  const [wooId, setWooId] = useState("");
  const [shopifyId, setShopifyId] = useState("");
  const [bom, setBom] = useState<BomRow[]>(emptyBom());
  const [hwBom, setHwBom] = useState<HwRow[]>([]);
  const [presetQty, setPresetQty] = useState("5");
  const [partSku, setPartSku] = useState("");
  const [partName, setPartName] = useState("");

  async function load() {
    try {
      setProducts(await api<Product[]>("/api/v1/products"));
      setParts(await api<Part[]>("/api/v1/parts"));
      try {
        setHardware(await api("/api/v1/hardware"));
      } catch {
        setHardware([]);
      }
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Failed to load products");
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    load();
  }, []);

  function resetForm() {
    setEditing(null);
    setSku("");
    setName("");
    setWooId("");
    setShopifyId("");
    setBom(emptyBom());
    setHwBom([]);
  }

  function startCreate() {
    resetForm();
    setOpen(true);
  }

  function startEdit(product: Product) {
    setEditing(product);
    setSku(product.sku);
    setName(product.name);
    setWooId(product.woocommerce_product_id ? String(product.woocommerce_product_id) : "");
    setShopifyId(product.shopify_product_id || "");
    setBom(
      product.bom.length
        ? product.bom.map((b) => ({
            part_id: b.part_id,
            quantity: b.quantity,
            is_optional: b.is_optional,
          }))
        : emptyBom(),
    );
    setHwBom(
      (product.hardware_bom || []).map((b) => ({
        hardware_item_id: b.hardware_item_id,
        quantity: b.quantity,
        is_optional: b.is_optional,
      })),
    );
    setOpen(true);
  }

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

  async function saveProduct(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const body = {
        sku,
        name,
        woocommerce_product_id: wooId ? Number(wooId) : null,
        shopify_product_id: shopifyId.trim() || null,
        bom: bom.filter((b) => b.part_id),
        hardware_bom: hwBom.filter((b) => b.hardware_item_id),
      };
      if (editing) {
        await api(`/api/v1/products/${editing.id}`, {
          method: "PUT",
          body: JSON.stringify(body),
        });
        toast.success(`Updated ${sku}`);
      } else {
        await api("/api/v1/products", {
          method: "POST",
          body: JSON.stringify(body),
        });
        toast.success("Product saved. Future SKUs can be added here without code changes.");
      }
      setOpen(false);
      resetForm();
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    } finally {
      setSaving(false);
    }
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await api(`/api/v1/products/${pendingDelete.id}`, { method: "DELETE" });
      toast.success(`Deleted ${pendingDelete.sku}`);
      setPendingDelete(null);
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not delete product");
    } finally {
      setDeleting(false);
    }
  }

  if (loading) return <div className="text-zinc-500">Loading products…</div>;
  if (loadError) return <div className="text-red-300">{loadError}</div>;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          Bills of materials drive order explosion. Optional accessories are not auto-produced. Edit a SKU to change
          its BOM; delete only works when no orders or kits still point at it.
        </p>
        <Button onClick={startCreate}>Add product</Button>
      </div>
      <form onSubmit={addPart} className="flex flex-wrap gap-2 rounded-xl border border-white/8 p-3">
        <Input placeholder="New part SKU" value={partSku} onChange={(e) => setPartSku(e.target.value)} required />
        <Input placeholder="Name" value={partName} onChange={(e) => setPartName(e.target.value)} required />
        <Button type="submit" variant="outline">
          Add part
        </Button>
      </form>
      {products.length === 0 && (
        <p className="rounded-xl border border-dashed border-white/12 px-4 py-8 text-center text-sm text-zinc-500">
          No products yet. Add a SKU and BOM so incoming orders can explode into print jobs.
        </p>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        {products.map((p) => (
          <Card key={p.id}>
            <CardHeader className="flex flex-row items-start justify-between gap-2 space-y-0">
              <CardTitle>
                {p.sku} · {p.name}
              </CardTitle>
              <div className="flex shrink-0 gap-1">
                <Button size="sm" variant="outline" onClick={() => startEdit(p)}>
                  Edit
                </Button>
                <Button size="sm" variant="destructive" onClick={() => setPendingDelete(p)}>
                  Delete
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-1 text-sm">
              {(p.woocommerce_product_id || p.shopify_product_id) && (
                <div className="text-xs text-zinc-500">
                  {p.woocommerce_product_id ? `Woo #${p.woocommerce_product_id}` : ""}
                  {p.woocommerce_product_id && p.shopify_product_id ? " · " : ""}
                  {p.shopify_product_id ? `Shopify #${p.shopify_product_id}` : ""}
                </div>
              )}
              {p.bom.length === 0 && (p.hardware_bom || []).length === 0 && (
                <p className="text-xs text-zinc-500">No BOM lines. Edit this product to add printed parts.</p>
              )}
              {p.bom.map((b) => (
                <div key={b.id} className="flex justify-between">
                  <span>
                    {b.part_sku} {b.is_optional ? "(optional)" : ""}
                  </span>
                  <span className="font-mono">×{b.quantity}</span>
                </div>
              ))}
              {(p.hardware_bom || []).map((b) => (
                <div key={b.id} className="flex justify-between text-zinc-400">
                  <span>
                    HW {b.sku} {b.is_optional ? "(optional)" : ""}
                  </span>
                  <span className="font-mono">×{b.quantity}</span>
                </div>
              ))}
              <div className="flex flex-wrap gap-2 pt-2">
                <Input className="w-16" value={presetQty} onChange={(e) => setPresetQty(e.target.value)} />
                <Button
                  size="sm"
                  variant="outline"
                  onClick={async () => {
                    try {
                      const res = await api<{ batch_code?: string; message?: string }>("/api/v1/presets/produce", {
                        method: "POST",
                        body: JSON.stringify({ product_id: p.id, quantity: Number(presetQty), build_stock: false }),
                      });
                      toast.success(
                        res.batch_code
                          ? `Queued ${presetQty} × ${p.sku} as ${res.batch_code}`
                          : res.message || "Production requirements created",
                      );
                    } catch (err) {
                      toast.error(err instanceof Error ? err.message : "Preset failed");
                    }
                  }}
                >
                  Produce {presetQty} × {p.sku}
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Dialog
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (!next) resetForm();
        }}
      >
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{editing ? `Edit ${editing.sku}` : "New product + BOM"}</DialogTitle>
          </DialogHeader>
          <form onSubmit={saveProduct} className="space-y-3">
            <div className="space-y-1">
              <Label>SKU</Label>
              <Input placeholder="RK-FR5" value={sku} onChange={(e) => setSku(e.target.value)} required />
            </div>
            <div className="space-y-1">
              <Label>Name</Label>
              <Input placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} required />
            </div>
            <Input placeholder="WooCommerce product ID (optional)" value={wooId} onChange={(e) => setWooId(e.target.value)} />
            <Input
              placeholder="Shopify product ID (optional)"
              value={shopifyId}
              onChange={(e) => setShopifyId(e.target.value)}
            />
            <p className="text-xs text-zinc-500">Printed parts</p>
            {bom.map((row, idx) => (
              <div key={idx} className="flex flex-wrap items-center gap-2">
                <select
                  className="h-8 min-w-[8rem] flex-1 rounded-lg border border-input bg-transparent px-2 text-sm"
                  value={row.part_id}
                  onChange={(e) => setBom((c) => c.map((x, i) => (i === idx ? { ...x, part_id: e.target.value } : x)))}
                >
                  <option value="">Part…</option>
                  {parts.map((part) => (
                    <option key={part.id} value={part.id}>
                      {part.sku}
                    </option>
                  ))}
                </select>
                <Input
                  type="number"
                  min={1}
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
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => setBom((c) => (c.length <= 1 ? emptyBom() : c.filter((_, i) => i !== idx)))}
                >
                  Remove
                </Button>
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              onClick={() => setBom((c) => [...c, { part_id: "", quantity: 1, is_optional: false }])}
            >
              Add BOM line
            </Button>
            <p className="text-xs text-zinc-500">Hardware / packaging</p>
            {hwBom.map((row, idx) => (
              <div key={`hw-${idx}`} className="grid grid-cols-[1fr_70px_auto] gap-2">
                <select
                  className="h-8 rounded-lg border border-input bg-transparent px-2 text-sm"
                  value={row.hardware_item_id}
                  onChange={(e) =>
                    setHwBom((c) => c.map((x, i) => (i === idx ? { ...x, hardware_item_id: e.target.value } : x)))
                  }
                >
                  <option value="">Hardware…</option>
                  {hardware.map((h) => (
                    <option key={h.id} value={h.id}>
                      {h.sku} {h.name}
                    </option>
                  ))}
                </select>
                <Input
                  type="number"
                  value={row.quantity}
                  onChange={(e) =>
                    setHwBom((c) => c.map((x, i) => (i === idx ? { ...x, quantity: Number(e.target.value) } : x)))
                  }
                />
                <Button type="button" size="sm" variant="ghost" onClick={() => setHwBom((c) => c.filter((_, i) => i !== idx))}>
                  Remove
                </Button>
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              onClick={() => setHwBom((c) => [...c, { hardware_item_id: "", quantity: 1, is_optional: false }])}
            >
              Add hardware / packaging line
            </Button>
            <Button type="submit" className="w-full" disabled={saving}>
              {saving ? "Saving…" : editing ? "Save changes" : "Save product"}
            </Button>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={!!pendingDelete} onOpenChange={(next) => !next && setPendingDelete(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Delete {pendingDelete?.sku}?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            This removes the product and its BOM. If any order or assembly kit still uses {pendingDelete?.sku}, FarmOS
            will refuse so history stays intact — edit the BOM instead.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setPendingDelete(null)} disabled={deleting}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={confirmDelete} disabled={deleting}>
              {deleting ? "Deleting…" : "Delete product"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
