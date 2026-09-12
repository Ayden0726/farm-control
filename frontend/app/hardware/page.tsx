"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { HardwareNav } from "@/components/hardware-nav";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatPcs } from "@/lib/pcs";
import { toast } from "sonner";

type Item = {
  id: string;
  sku: string;
  name: string;
  category: string;
  supplier: string;
  quantity_on_hand: number;
  quantity_reserved: number;
  quantity_available: number;
  min_stock: number;
  target_stock: number;
  unit_cost: number;
  low: boolean;
  public_code: string | null;
};

const empty = {
  sku: "",
  name: "",
  category: "hardware",
  supplier: "",
  unit_cost: "0",
  min_stock: "0",
  target_stock: "0",
};

export default function HardwarePage() {
  const [rows, setRows] = useState<Item[]>([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(empty);
  const [pendingDelete, setPendingDelete] = useState<Item | null>(null);
  const [deleting, setDeleting] = useState(false);

  async function load() {
    setRows(await api<Item[]>("/api/v1/hardware"));
  }
  useEffect(() => {
    load().catch((err) => toast.error(err instanceof Error ? err.message : "Failed"));
  }, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/api/v1/hardware", {
        method: "POST",
        body: JSON.stringify({
          sku: form.sku,
          name: form.name,
          category: form.category,
          supplier: form.supplier,
          unit_cost: Number(form.unit_cost),
          purchase_cost: Number(form.unit_cost),
          quantity_on_hand: 0,
          min_stock: Number(form.min_stock),
          target_stock: Number(form.target_stock),
          reorder_mode: "off",
        }),
      });
      toast.success("Hardware profile saved. Add pieces from the SKU — do not re-enter this information.");
      setOpen(false);
      setForm(empty);
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not create hardware");
    }
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await api(`/api/v1/hardware/${pendingDelete.id}`, { method: "DELETE" });
      toast.success(`Deleted ${pendingDelete.sku}`);
      setPendingDelete(null);
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not delete");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="space-y-4">
      <HardwareNav />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          Create a hardware SKU once. Then receive pieces as they arrive — same idea as filament rolls, counted in pcs
          instead of grams. FarmOS does not dump a catalog of fasteners for you.
        </p>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger render={<Button />}>New hardware SKU</DialogTrigger>
          <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
            <DialogHeader>
              <DialogTitle>Create hardware profile</DialogTitle>
            </DialogHeader>
            <form onSubmit={create} className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1">
                <Label>SKU</Label>
                <Input value={form.sku} onChange={(e) => setForm({ ...form, sku: e.target.value })} required />
              </div>
              <div className="space-y-1">
                <Label>Name</Label>
                <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
              </div>
              <div className="space-y-1">
                <Label>Category</Label>
                <select
                  className="h-8 w-full rounded-lg border border-input bg-transparent px-2 text-sm"
                  value={form.category}
                  onChange={(e) => setForm({ ...form, category: e.target.value })}
                >
                  {["hardware", "fasteners", "packaging", "shipping", "labels", "spares", "consumable"].map((c) => (
                    <option key={c}>{c}</option>
                  ))}
                </select>
              </div>
              <div className="space-y-1">
                <Label>Supplier</Label>
                <Input value={form.supplier} onChange={(e) => setForm({ ...form, supplier: e.target.value })} />
              </div>
              <div className="space-y-1">
                <Label>Cost per piece</Label>
                <Input value={form.unit_cost} onChange={(e) => setForm({ ...form, unit_cost: e.target.value })} />
              </div>
              <div className="space-y-1">
                <Label>Minimum (pcs)</Label>
                <Input value={form.min_stock} onChange={(e) => setForm({ ...form, min_stock: e.target.value })} />
              </div>
              <div className="space-y-1 sm:col-span-2">
                <Label>Target (pcs)</Label>
                <Input value={form.target_stock} onChange={(e) => setForm({ ...form, target_stock: e.target.value })} />
              </div>
              <p className="text-xs text-zinc-500 sm:col-span-2">
                On-hand starts at 0 pcs. Open the SKU and use Add pcs when a shipment arrives.
              </p>
              <Button type="submit" className="sm:col-span-2">
                Create SKU
              </Button>
            </form>
          </DialogContent>
        </Dialog>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>SKU</TableHead>
            <TableHead>On hand</TableHead>
            <TableHead>Reserved</TableHead>
            <TableHead>Available</TableHead>
            <TableHead>Min / target</TableHead>
            <TableHead></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={r.id} className={r.low ? "bg-amber-500/5" : ""}>
              <TableCell>
                <div className="font-medium">{r.sku}</div>
                <div className="text-xs text-zinc-500">
                  {r.name} · {r.category}
                  {r.public_code ? ` · ${r.public_code}` : ""}
                </div>
              </TableCell>
              <TableCell className="font-mono">{formatPcs(r.quantity_on_hand)}</TableCell>
              <TableCell className="font-mono">{formatPcs(r.quantity_reserved)}</TableCell>
              <TableCell className={`font-mono ${r.low ? "text-amber-300" : ""}`}>
                {formatPcs(r.quantity_available)}
              </TableCell>
              <TableCell className="font-mono text-xs">
                {formatPcs(r.min_stock)} / {formatPcs(r.target_stock)}
              </TableCell>
              <TableCell className="space-x-3">
                <Link href={`/hardware/${r.id}?add=1`} className="text-xs text-amber-300 hover:underline">
                  Add pcs
                </Link>
                <Link href={`/hardware/${r.id}`} className="text-xs text-zinc-400 hover:underline">
                  Profile
                </Link>
                <button
                  type="button"
                  className="text-xs text-red-300 hover:underline"
                  onClick={() => setPendingDelete(r)}
                >
                  Delete
                </button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {rows.length === 0 && (
        <p className="text-sm text-zinc-500">
          No hardware SKUs yet. Add inserts, screws, boxes, and labels as you buy them — nothing is preloaded.
        </p>
      )}
      <Dialog open={!!pendingDelete} onOpenChange={(next) => !next && setPendingDelete(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Delete {pendingDelete?.sku}?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            This removes the SKU and its receive history. If a product BOM, kit, or open purchase order still uses{" "}
            {pendingDelete?.sku}, FarmOS will refuse — take it off the BOM first.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setPendingDelete(null)} disabled={deleting}>
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
