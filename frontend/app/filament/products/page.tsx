"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { FilamentNav } from "@/components/filament-nav";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { toast } from "sonner";

type Product = {
  id: string;
  barcode_id: string;
  manufacturer: string;
  product_name: string;
  material: string;
  color: string;
  spool_size_label: string;
  purchase_cost: number;
  supplier_url: string;
  stock: { physical_kg: number; available_kg: number; below_minimum: boolean };
  recommend: { needed: boolean; rolls: number };
};

const empty = {
  manufacturer: "Siddament",
  product_name: "",
  material: "PETG",
  color: "Black",
  spool_size_label: "3 kg",
  filament_weight_g: "3000",
  purchase_cost: "57",
  nozzle_temp_c: "250",
  bed_temp_c: "80",
  min_stock_g: "6000",
  target_stock_g: "18000",
  supplier_url: "",
  supplier_sku: "",
};

export default function ProductsPage() {
  const [rows, setRows] = useState<Product[]>([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(empty);

  async function load() {
    setRows(await api<Product[]>("/api/v1/filament/products"));
  }
  useEffect(() => {
    load();
  }, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/api/v1/filament/products", {
        method: "POST",
        body: JSON.stringify({
          ...form,
          filament_weight_g: Number(form.filament_weight_g),
          purchase_cost: Number(form.purchase_cost),
          min_stock_g: Number(form.min_stock_g),
          target_stock_g: Number(form.target_stock_g),
          preferred_spool_weight_g: Number(form.filament_weight_g),
          normal_price: Number(form.purchase_cost),
          nozzle_temp_c: form.nozzle_temp_c ? Number(form.nozzle_temp_c) : null,
          bed_temp_c: form.bed_temp_c ? Number(form.bed_temp_c) : null,
        }),
      });
      toast.success("Filament profile saved. Add rolls from the profile — do not re-enter this information.");
      setOpen(false);
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not create product");
    }
  }

  return (
    <div className="space-y-4">
      <FilamentNav />
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Create a filament profile once. FarmOS generates a reusable FILT- barcode. New rolls get sequential SPOOL numbers — you do not re-enter colour, size, or temperatures.
        </p>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger render={<Button />}>New filament profile</DialogTrigger>
          <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
            <DialogHeader>
              <DialogTitle>Create filament profile</DialogTitle>
            </DialogHeader>
            <form onSubmit={create} className="grid gap-3 sm:grid-cols-2">
              {(
                [
                  ["manufacturer", "Manufacturer"],
                  ["product_name", "Product name"],
                  ["material", "Material"],
                  ["color", "Colour"],
                  ["spool_size_label", "Spool size"],
                  ["filament_weight_g", "Filament weight (g)"],
                  ["purchase_cost", "Purchase cost"],
                  ["supplier_sku", "Supplier SKU"],
                  ["supplier_url", "Supplier URL"],
                  ["nozzle_temp_c", "Nozzle °C"],
                  ["bed_temp_c", "Bed °C"],
                  ["min_stock_g", "Minimum stock (g)"],
                  ["target_stock_g", "Target stock (g)"],
                ] as const
              ).map(([key, label]) => (
                <div key={key} className="space-y-1 sm:col-span-1">
                  <Label>{label}</Label>
                  <Input value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} />
                </div>
              ))}
              <Button type="submit" className="sm:col-span-2">
                Create and generate barcode
              </Button>
            </form>
          </DialogContent>
        </Dialog>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Profile</TableHead>
            <TableHead>FarmOS barcode</TableHead>
            <TableHead>Physical</TableHead>
            <TableHead>Available</TableHead>
            <TableHead></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((p) => (
            <TableRow key={p.id} className={p.stock.below_minimum ? "bg-amber-500/5" : ""}>
              <TableCell>
                <div className="font-medium">
                  {p.manufacturer} {p.material} — {p.color}
                </div>
                <div className="text-xs text-zinc-500">{p.spool_size_label}</div>
              </TableCell>
              <TableCell className="font-mono text-xs">{p.barcode_id}</TableCell>
              <TableCell>{p.stock.physical_kg.toFixed(1)} kg</TableCell>
              <TableCell className={p.stock.below_minimum ? "text-amber-300" : ""}>
                {p.stock.available_kg.toFixed(1)} kg
                {p.recommend.needed ? ` · buy ${p.recommend.rolls}` : ""}
              </TableCell>
              <TableCell className="space-x-3">
                <Link href={`/filament/products/${p.id}?add=1`} className="text-xs text-amber-300 hover:underline">
                  Add rolls
                </Link>
                <Link href={`/filament/products/${p.id}`} className="text-xs text-zinc-400 hover:underline">
                  Profile
                </Link>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
