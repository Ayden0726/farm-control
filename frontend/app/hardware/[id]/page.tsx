"use client";

import Link from "next/link";
import { FormEvent, Suspense, useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { AddHardwareStockPanel } from "@/components/add-hardware-stock-panel";
import { HardwareNav } from "@/components/hardware-nav";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatPcs } from "@/lib/pcs";
import { toast } from "sonner";

type Detail = {
  id: string;
  sku: string;
  name: string;
  category: string;
  supplier: string;
  supplier_url: string;
  unit_cost: number;
  purchase_cost: number;
  quantity_on_hand: number;
  quantity_reserved: number;
  quantity_available: number;
  min_stock: number;
  target_stock: number;
  storage_location: string;
  reorder_mode: string;
  approval_required: boolean;
  public_code: string | null;
  notes: string;
  low: boolean;
  movements: { id: string; quantity: number; reason: string; notes: string; created_at: string | null }[];
};

function HardwareDetailInner() {
  const params = useParams<{ id: string }>();
  const search = useSearchParams();
  const router = useRouter();
  const [row, setRow] = useState<Detail | null>(null);
  const [pendingDelete, setPendingDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  async function load() {
    setRow(await api<Detail>(`/api/v1/hardware/${params.id}`));
  }
  useEffect(() => {
    load().catch((err) => toast.error(err instanceof Error ? err.message : "Failed"));
  }, [params.id]);

  if (!row) return <div className="text-zinc-500">Loading hardware…</div>;
  const item = row;

  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!row) return;
    const fd = new FormData(e.currentTarget);
    try {
      await api(`/api/v1/hardware/${row.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          sku: row.sku,
          name: String(fd.get("name") || row.name),
          category: String(fd.get("category") || row.category),
          supplier: String(fd.get("supplier") || ""),
          supplier_url: String(fd.get("supplier_url") || ""),
          unit_cost: Number(fd.get("unit_cost")),
          purchase_cost: Number(fd.get("unit_cost")),
          quantity_on_hand: row.quantity_on_hand,
          min_stock: Number(fd.get("min_stock")),
          target_stock: Number(fd.get("target_stock")),
          storage_location: String(fd.get("storage_location") || ""),
          reorder_mode: String(fd.get("reorder_mode")),
          approval_required: fd.get("approval_required") === "on",
          notes: String(fd.get("notes") || ""),
          is_active: true,
        }),
      });
      toast.success("Hardware profile saved");
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Save failed");
    }
  }

  async function confirmDelete() {
    setDeleting(true);
    try {
      await api(`/api/v1/hardware/${item.id}`, { method: "DELETE" });
      toast.success(`Deleted ${item.sku}`);
      router.push("/hardware");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not delete");
      setDeleting(false);
      setPendingDelete(false);
    }
  }

  return (
    <div className="space-y-4">
      <HardwareNav />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">
            {row.sku} · {row.name}
          </h2>
          <p className="text-sm text-zinc-400">{row.category}</p>
          {row.public_code && <p className="font-mono text-sm text-amber-200">{row.public_code}</p>}
          <p className="text-sm text-zinc-500">Saved once. Incoming shipments add pcs to this SKU.</p>
        </div>
        <Button variant="destructive" onClick={() => setPendingDelete(true)}>
          Delete SKU
        </Button>
      </div>
      <AddHardwareStockPanel item={row} defaultOpen={search.get("add") === "1" || row.quantity_on_hand === 0} onReceived={load} />
      <div className="grid gap-3 md:grid-cols-4">
        <Card>
          <CardHeader>
            <CardTitle>On hand</CardTitle>
          </CardHeader>
          <CardContent className="font-mono">{formatPcs(row.quantity_on_hand)}</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Reserved</CardTitle>
          </CardHeader>
          <CardContent className="font-mono">{formatPcs(row.quantity_reserved)}</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Available</CardTitle>
          </CardHeader>
          <CardContent className={`font-mono ${row.low ? "text-amber-200" : ""}`}>
            {formatPcs(row.quantity_available)}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Location</CardTitle>
          </CardHeader>
          <CardContent className="text-sm">{row.storage_location || "—"}</CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Profile & reorder</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={save} className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1 sm:col-span-2">
              <Label>Name</Label>
              <Input name="name" defaultValue={row.name} />
            </div>
            <div className="space-y-1">
              <Label>Category</Label>
              <select name="category" defaultValue={row.category} className="h-8 w-full rounded-lg border border-input bg-transparent px-2 text-sm">
                {["hardware", "fasteners", "packaging", "shipping", "labels", "spares", "consumable"].map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label>Cost per piece</Label>
              <Input name="unit_cost" defaultValue={String(row.unit_cost)} />
            </div>
            <div className="space-y-1">
              <Label>Minimum (pcs)</Label>
              <Input name="min_stock" defaultValue={String(row.min_stock)} />
            </div>
            <div className="space-y-1">
              <Label>Target (pcs)</Label>
              <Input name="target_stock" defaultValue={String(row.target_stock)} />
            </div>
            <div className="space-y-1">
              <Label>Supplier</Label>
              <Input name="supplier" defaultValue={row.supplier} />
            </div>
            <div className="space-y-1 sm:col-span-2">
              <Label>Supplier URL</Label>
              <Input name="supplier_url" defaultValue={row.supplier_url} />
            </div>
            <div className="space-y-1 sm:col-span-3">
              <Label>Storage location</Label>
              <Input name="storage_location" defaultValue={row.storage_location} />
            </div>
            <div className="space-y-1">
              <Label>Reorder mode</Label>
              <select name="reorder_mode" defaultValue={row.reorder_mode} className="h-8 w-full rounded-lg border border-input bg-transparent px-2 text-sm">
                <option value="off">Off</option>
                <option value="suggest_only">Suggest only</option>
                <option value="create_purchase_order">Create purchase order</option>
                <option value="approve_and_order">Approve and order</option>
                <option value="full_auto">Full auto (disabled unless spending control is on)</option>
              </select>
            </div>
            <div className="space-y-1 sm:col-span-2">
              <Label>Notes</Label>
              <Input name="notes" defaultValue={row.notes} />
            </div>
            <label className="flex items-center gap-2 text-sm sm:col-span-2">
              <input type="checkbox" name="approval_required" defaultChecked={row.approval_required} />
              Approval required
            </label>
            <Button type="submit">Save profile</Button>
          </form>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Receive history</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          {row.movements.length === 0 && <p className="text-zinc-500">No receives yet. Use Add pcs when a box arrives.</p>}
          {row.movements.map((m) => (
            <div key={m.id} className="flex justify-between gap-2 rounded-md bg-white/5 px-3 py-2 font-mono text-xs">
              <span>
                {m.reason} · {m.quantity > 0 ? "+" : ""}
                {formatPcs(m.quantity)}
              </span>
              <span className="text-zinc-500">{m.created_at ? m.created_at.slice(0, 16).replace("T", " ") : ""}</span>
            </div>
          ))}
        </CardContent>
      </Card>
      <p className="text-xs text-zinc-500">
        <Link href="/hardware" className="text-amber-300 hover:underline">
          Back to catalog
        </Link>
      </p>
      <Dialog open={pendingDelete} onOpenChange={(next) => !next && !deleting && setPendingDelete(false)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Delete {row.sku}?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            This removes the SKU. If a product BOM, kit, or open purchase order still uses it, FarmOS will refuse.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setPendingDelete(false)} disabled={deleting}>
              Keep SKU
            </Button>
            <Button variant="destructive" onClick={confirmDelete} disabled={deleting}>
              {deleting ? "Deleting…" : "Delete hardware"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function HardwareDetailPage() {
  return (
    <Suspense fallback={<div className="text-zinc-500">Loading hardware…</div>}>
      <HardwareDetailInner />
    </Suspense>
  );
}
