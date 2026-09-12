"use client";

import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import Link from "next/link";

type Product = { id: string; sku: string; name: string };
type Kit = {
  id: string;
  public_code: string;
  product_sku: string;
  product_name: string;
  quantity: number;
  status: string;
  lines: { sku: string; name: string; required_qty: number; reserved_qty: number; available_qty: number; kind: string }[];
};

export default function KitsPage() {
  const [kits, setKits] = useState<Kit[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [productId, setProductId] = useState("");
  const [qty, setQty] = useState("1");

  async function load() {
    setKits(await api<Kit[]>("/api/v1/kits"));
    setProducts(await api<Product[]>("/api/v1/products"));
  }
  useEffect(() => {
    load().catch((err) => toast.error(err instanceof Error ? err.message : "Failed"));
  }, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    await api("/api/v1/kits", { method: "POST", body: JSON.stringify({ product_id: productId, quantity: Number(qty) }) });
    toast.success("Kit created");
    load();
  }

  async function reserve(id: string) {
    try {
      await api(`/api/v1/kits/${id}/reserve`, { method: "POST" });
      toast.success("Components reserved into kit");
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Cannot reserve");
    }
  }

  async function advance(id: string, status: string) {
    await api(`/api/v1/kits/${id}/status`, { method: "POST", body: JSON.stringify({ status }) });
    load();
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>New assembly kit</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={create} className="flex flex-wrap gap-2">
            <select
              className="h-8 rounded-lg border border-input bg-transparent px-2 text-sm"
              value={productId}
              onChange={(e) => setProductId(e.target.value)}
              required
            >
              <option value="">Product…</option>
              {products.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.sku} {p.name}
                </option>
              ))}
            </select>
            <Input className="w-24" value={qty} onChange={(e) => setQty(e.target.value)} />
            <Button type="submit">Create kit</Button>
          </form>
        </CardContent>
      </Card>
      {kits.map((kit) => (
        <Card key={kit.id}>
          <CardHeader>
            <CardTitle>
              {kit.public_code} · {kit.product_sku} × {kit.quantity}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="text-amber-200">
              {kit.status === "kit_ready" ? "Kit Ready" : kit.status.replaceAll("_", " ")}
            </div>
            {kit.lines.map((ln) => (
              <div key={ln.sku + ln.kind} className="flex justify-between">
                <span>
                  {ln.kind === "hardware" ? "HW" : "Part"} {ln.sku} {ln.name}
                </span>
                <span>
                  {ln.available_qty}/{ln.required_qty} avail · reserved {ln.reserved_qty}
                </span>
              </div>
            ))}
            <div className="flex flex-wrap gap-2 pt-2">
              <Button size="sm" onClick={() => reserve(kit.id)}>
                Reserve into kit
              </Button>
              <Button size="sm" variant="outline" onClick={() => advance(kit.id, "assembly")}>
                Start assembly
              </Button>
              <Button size="sm" variant="outline" onClick={() => advance(kit.id, "qc")}>
                Kit QC
              </Button>
              <Button size="sm" variant="outline" onClick={() => advance(kit.id, "ready_to_pack")}>
                Ready to pack
              </Button>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
