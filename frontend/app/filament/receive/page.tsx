"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { FilamentNav } from "@/components/filament-nav";
import { BarcodeScanner } from "@/components/barcode-scanner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "sonner";
import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Identified = {
  kind: string;
  id: string;
  barcode_id?: string;
  manufacturer?: string;
  material?: string;
  color?: string;
  spool_size_label?: string;
  filament_weight_g?: number;
  purchase_cost?: number;
  preferred_supplier_id?: string | null;
};

type ReceiveResult = {
  message: string;
  print_path: string;
  spools: { id: string; public_code: string }[];
};

function ReceiveInner() {
  const params = useSearchParams();
  const [product, setProduct] = useState<Identified | null>(null);
  const [qty, setQty] = useState("5");
  const [cost, setCost] = useState("");
  const [pos, setPos] = useState<{ id: string; reference: string; status: string; lines: { product_id: string }[] }[]>([]);
  const [poId, setPoId] = useState("");
  const [done, setDone] = useState<ReceiveResult | null>(null);

  const identify = useCallback(async (code: string) => {
    try {
      const hit = await api<Identified>("/api/v1/filament/lookup", {
        method: "POST",
        body: JSON.stringify({ code }),
      });
      if (hit.kind !== "product") {
        toast.error("Scan a reusable product barcode (FILT-…), not a unique spool QR.");
        return;
      }
      setProduct(hit);
      setCost(String(hit.purchase_cost || ""));
      setDone(null);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Unknown barcode");
    }
  }, []);

  useEffect(() => {
    const code = params.get("code");
    if (code) identify(code);
    api<{ id: string; reference: string; status: string; lines: { product_id: string }[] }[]>("/api/v1/purchasing").then(setPos).catch(() => undefined);
  }, [params, identify]);

  async function receive() {
    if (!product) return;
    try {
      const res = await api<ReceiveResult>("/api/v1/filament/receive", {
        method: "POST",
        body: JSON.stringify({
          product_id: product.id,
          quantity: Number(qty),
          cost_per_spool: Number(cost),
          purchase_order_id: poId || null,
          supplier_id: product.preferred_supplier_id,
        }),
      });
      setDone(res);
      toast.success(res.message);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Receive failed");
    }
  }

  return (
    <div className="mx-auto max-w-xl space-y-4">
      <FilamentNav />
      <h2 className="text-xl font-semibold">Receive filament</h2>
      <p className="text-sm text-muted-foreground">
        Scan the FarmOS receiving barcode you printed for this product. The same code is reused every time more of this filament arrives.
      </p>
      <div className={product || done ? "hidden" : undefined}>
        <BarcodeScanner onDetect={identify} />
      </div>
      {product && !done && (
        <Card>
          <CardHeader>
            <CardTitle>
              {product.manufacturer} {product.material} — {product.color}
            </CardTitle>
            <p className="font-mono text-xs text-zinc-500">{product.barcode_id}</p>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="text-sm">Spool size: {product.spool_size_label}</div>
            <div className="space-y-1">
              <Label>Quantity received</Label>
              <Input className="h-12 text-lg" inputMode="numeric" value={qty} onChange={(e) => setQty(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label>Cost per spool</Label>
              <Input className="h-12 text-lg" inputMode="decimal" value={cost} onChange={(e) => setCost(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label>Purchase order (optional)</Label>
              <select className="h-12 w-full rounded-lg border border-input bg-transparent px-3" value={poId} onChange={(e) => setPoId(e.target.value)}>
                <option value="">None — walk-in / local purchase</option>
                {pos
                  .filter((p) => ["ordered", "shipped", "partially_received", "approved", "awaiting_approval", "draft"].includes(p.status))
                  .map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.reference} · {p.status}
                    </option>
                  ))}
              </select>
            </div>
            <Button className="h-12 w-full text-base" onClick={receive}>
              Add {qty} spools
            </Button>
            <Button variant="ghost" className="w-full" onClick={() => setProduct(null)}>
              Scan a different barcode
            </Button>
          </CardContent>
        </Card>
      )}
      {done && (
        <Card>
          <CardHeader>
            <CardTitle>{done.message}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <ul className="font-mono text-sm">
              {done.spools.map((s) => (
                <li key={s.id}>{s.public_code}</li>
              ))}
            </ul>
            <Link href={done.print_path} className={cn(buttonVariants(), "flex h-12 items-center justify-center")}>
              Print All Spool Labels
            </Link>
            <Button variant="outline" className="w-full" onClick={() => { setDone(null); setProduct(null); }}>
              Receive more
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default function ReceivePage() {
  return (
    <Suspense fallback={<div className="text-zinc-500">Opening receive…</div>}>
      <ReceiveInner />
    </Suspense>
  );
}
