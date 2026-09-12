"use client";

import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
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

export default function HardwarePage() {
  const [rows, setRows] = useState<Item[]>([]);
  const [form, setForm] = useState({
    sku: "",
    name: "",
    category: "hardware",
    supplier: "",
    unit_cost: "0",
    quantity_on_hand: "0",
    min_stock: "0",
    target_stock: "0",
  });

  async function load() {
    setRows(await api<Item[]>("/api/v1/hardware"));
  }
  useEffect(() => {
    load().catch((err) => toast.error(err instanceof Error ? err.message : "Failed"));
  }, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    await api("/api/v1/hardware", {
      method: "POST",
      body: JSON.stringify({
        ...form,
        unit_cost: Number(form.unit_cost),
        purchase_cost: Number(form.unit_cost),
        quantity_on_hand: Number(form.quantity_on_hand),
        min_stock: Number(form.min_stock),
        target_stock: Number(form.target_stock),
      }),
    });
    toast.success("Hardware SKU added");
    setForm({ ...form, sku: "", name: "" });
    load();
  }

  async function adjust(id: string, quantity: number) {
    await api(`/api/v1/hardware/${id}/adjust`, {
      method: "POST",
      body: JSON.stringify({ quantity, reason: "adjust" }),
    });
    load();
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Add hardware or consumable</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={create} className="grid gap-2 md:grid-cols-4">
            <div>
              <Label>SKU</Label>
              <Input value={form.sku} onChange={(e) => setForm({ ...form, sku: e.target.value })} required />
            </div>
            <div>
              <Label>Name</Label>
              <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
            </div>
            <div>
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
            <div>
              <Label>Supplier</Label>
              <Input value={form.supplier} onChange={(e) => setForm({ ...form, supplier: e.target.value })} />
            </div>
            <div>
              <Label>Unit cost</Label>
              <Input value={form.unit_cost} onChange={(e) => setForm({ ...form, unit_cost: e.target.value })} />
            </div>
            <div>
              <Label>On hand</Label>
              <Input value={form.quantity_on_hand} onChange={(e) => setForm({ ...form, quantity_on_hand: e.target.value })} />
            </div>
            <div>
              <Label>Minimum</Label>
              <Input value={form.min_stock} onChange={(e) => setForm({ ...form, min_stock: e.target.value })} />
            </div>
            <div>
              <Label>Target</Label>
              <Input value={form.target_stock} onChange={(e) => setForm({ ...form, target_stock: e.target.value })} />
            </div>
            <Button type="submit" className="md:col-span-4">
              Save item
            </Button>
          </form>
          <Button
            className="mt-3"
            variant="outline"
            onClick={async () => {
              try {
                const res = await api<{ created: unknown[] }>("/api/v1/hardware/reorder/run", { method: "POST" });
                toast.success(`Created ${res.created.length} hardware reorder suggestion(s)`);
              } catch (err) {
                toast.error(err instanceof Error ? err.message : "Reorder failed");
              }
            }}
          >
            Run hardware reorder now
          </Button>
        </CardContent>
      </Card>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>SKU</TableHead>
            <TableHead>Physical</TableHead>
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
                </div>
              </TableCell>
              <TableCell>{r.quantity_on_hand}</TableCell>
              <TableCell>{r.quantity_reserved}</TableCell>
              <TableCell>{r.quantity_available}</TableCell>
              <TableCell>
                {r.min_stock} / {r.target_stock}
              </TableCell>
              <TableCell className="space-x-1">
                <Button size="sm" variant="outline" onClick={() => adjust(r.id, 1)}>
                  +1
                </Button>
                <Button size="sm" variant="outline" onClick={() => adjust(r.id, -1)}>
                  −1
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
