"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Order, Product } from "@/lib/types";
import { StatusPill } from "@/components/status-pill";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { toast } from "sonner";

export default function OrdersPage() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [open, setOpen] = useState(false);
  const [reference, setReference] = useState("");
  const [customer, setCustomer] = useState("");
  const [productId, setProductId] = useState("");
  const [qty, setQty] = useState("1");

  async function load() {
    setOrders(await api<Order[]>("/api/v1/orders"));
    setProducts(await api<Product[]>("/api/v1/products"));
  }
  useEffect(() => {
    load();
  }, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/api/v1/orders", {
        method: "POST",
        body: JSON.stringify({
          reference,
          customer_name: customer,
          lines: [{ product_id: productId, quantity: Number(qty) }],
          create_production: true,
        }),
      });
      toast.success("Order created. Available finished parts were reserved; missing parts queued for production.");
      setOpen(false);
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    }
  }

  async function syncWoo() {
    try {
      const res = await api<{ imported: number }>("/api/v1/woocommerce/sync", { method: "POST" });
      toast.success(`Imported ${res.imported} WooCommerce orders`);
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "WooCommerce sync failed");
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          New → Awaiting production → In production → QC → Ready to ship → Shipped. BOM explosion drives production.
        </p>
        <div className="flex gap-2">
          <Button variant="outline" onClick={syncWoo}>
            Sync WooCommerce
          </Button>
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger render={<Button />}>New order</DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Create order</DialogTitle>
              </DialogHeader>
              <form onSubmit={create} className="space-y-3">
                <div className="space-y-1">
                  <Label>Reference</Label>
                  <Input value={reference} onChange={(e) => setReference(e.target.value)} required />
                </div>
                <div className="space-y-1">
                  <Label>Customer</Label>
                  <Input value={customer} onChange={(e) => setCustomer(e.target.value)} />
                </div>
                <div className="space-y-1">
                  <Label>Product</Label>
                  <select
                    className="h-8 w-full rounded-lg border border-input bg-transparent px-2 text-sm"
                    value={productId}
                    onChange={(e) => setProductId(e.target.value)}
                    required
                  >
                    <option value="">Select…</option>
                    {products.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.sku} · {p.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="space-y-1">
                  <Label>Quantity</Label>
                  <Input type="number" min={1} value={qty} onChange={(e) => setQty(e.target.value)} />
                </div>
                <Button type="submit" className="w-full">
                  Create and reserve / produce
                </Button>
              </form>
            </DialogContent>
          </Dialog>
        </div>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Reference</TableHead>
            <TableHead>Customer</TableHead>
            <TableHead>Source</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Packing</TableHead>
            <TableHead>To produce</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {orders.map((o) => (
            <TableRow key={o.id}>
              <TableCell>
                <Link href={`/orders/${o.id}`} className="font-medium hover:text-amber-200">
                  {o.reference}
                </Link>
              </TableCell>
              <TableCell>{o.customer_name}</TableCell>
              <TableCell className="capitalize">{o.source}</TableCell>
              <TableCell>
                <StatusPill status={o.status} />
              </TableCell>
              <TableCell className="text-xs">{o.packing_status || "unpacked"}</TableCell>
              <TableCell>{o.part_needs.reduce((n, p) => n + p.to_produce, 0)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
