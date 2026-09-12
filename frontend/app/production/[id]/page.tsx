"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { Product, ProductionRun } from "@/lib/types";
import { StatusPill } from "@/components/status-pill";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";

export default function ProductionDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [run, setRun] = useState<ProductionRun | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [productId, setProductId] = useState("");
  const [productQty, setProductQty] = useState("1");
  const [includeOptional, setIncludeOptional] = useState(false);
  const [adding, setAdding] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [filament, setFilament] = useState<{
    overall: string;
    materials: { product_id: string; label: string; required_g: number; available_g: number; on_order_g: number }[];
  } | null>(null);

  async function load() {
    setRun(await api<ProductionRun>(`/api/v1/production-runs/${params.id}`));
    try {
      setProducts(await api<Product[]>("/api/v1/products"));
    } catch {
      setProducts([]);
    }
    try {
      setFilament(await api(`/api/v1/production-runs/${params.id}/filament-check`));
    } catch {
      setFilament(null);
    }
  }
  useEffect(() => {
    load();
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
  }, [params.id]);

  if (!run) return <div className="text-zinc-500">Loading run…</div>;

  async function act(action: string) {
    const id = params.id;
    try {
      await api(`/api/v1/production-runs/${id}/${action}`, { method: "POST" });
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    }
  }

  async function addProduct() {
    if (!productId) {
      toast.error("Pick a product from the catalog first");
      return;
    }
    setAdding(true);
    try {
      const res = await api<{
        added: number;
        missing_gcode: string[];
        optional_skipped: string[];
        multi_file_parts?: string[];
        product_sku: string;
      }>(`/api/v1/production-runs/${params.id}/add-product`, {
        method: "POST",
        body: JSON.stringify({
          product_id: productId,
          quantity: Math.max(1, Number(productQty) || 1),
          include_optional: includeOptional,
        }),
      });
      toast.success(`Added ${res.added} line${res.added === 1 ? "" : "s"} from ${res.product_sku}`);
      if (res.missing_gcode.length) {
        toast.message(`No G-code tagged for ${res.missing_gcode.join(", ")}. Tag files on the Library tab.`);
      }
      if (res.multi_file_parts?.length) {
        toast.message(
          `${res.multi_file_parts.join(", ")} has more than one tagged file; each was added at full quantity.`,
        );
      }
      if (res.optional_skipped.length) {
        toast.message(`Skipped optional ${res.optional_skipped.join(", ")}.`);
      }
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not add product");
    } finally {
      setAdding(false);
    }
  }

  async function confirmDelete() {
    if (!run) return;
    setDeleting(true);
    try {
      await api(`/api/v1/production-runs/${run.id}`, { method: "DELETE" });
      toast.success(`Deleted ${run.batch_code || run.name}`);
      router.push("/production");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not delete run");
      setDeleting(false);
      setPendingDelete(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-xl font-semibold">{run.batch_code ? `${run.batch_code} · ${run.name}` : run.name}</h2>
          <p className="text-sm text-muted-foreground">
            {run.needed_by ? `Needed by ${run.needed_by.slice(0, 10)}` : "No needed-by date"}
            {run.notes ? ` · ${run.notes}` : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <StatusPill status={run.status} />
          <Button variant="outline" size="sm" onClick={() => act("pause")}>
            Pause queued work
          </Button>
          <Button variant="outline" size="sm" onClick={() => act("resume")}>
            Resume
          </Button>
          <Button variant="outline" size="sm" onClick={() => act("requeue-scrap")}>
            Requeue scrap
          </Button>
          <Button variant="destructive" size="sm" onClick={() => act("cancel")}>
            Cancel remaining
          </Button>
          <Button variant="destructive" size="sm" onClick={() => setPendingDelete(true)}>
            Delete run
          </Button>
        </div>
      </div>
      {run.status !== "completed" && run.status !== "cancelled" && (
        <Card>
          <CardHeader>
            <CardTitle>Add product from catalog</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-xs text-zinc-500">
              Adds every required BOM part and every G-code file tagged to those parts. Same part+file increases
              quantity on the existing line.
            </p>
            <div className="grid gap-2 md:grid-cols-[1fr_80px_auto]">
              <div>
                <Label>Product</Label>
                <select
                  className="h-8 w-full rounded-lg border border-input bg-transparent px-2 text-sm"
                  value={productId}
                  onChange={(e) => setProductId(e.target.value)}
                >
                  <option value="">Product…</option>
                  {products.filter((p) => p.is_active).map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.sku} · {p.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <Label>Qty</Label>
                <Input type="number" min={1} value={productQty} onChange={(e) => setProductQty(e.target.value)} />
              </div>
              <div className="flex items-end">
                <Button type="button" disabled={adding || !productId} onClick={addProduct}>
                  {adding ? "Adding…" : "Add product"}
                </Button>
              </div>
            </div>
            <label className="flex items-center gap-2 text-xs text-zinc-400">
              <input type="checkbox" checked={includeOptional} onChange={(e) => setIncludeOptional(e.target.checked)} />
              Include optional BOM accessories
            </label>
          </CardContent>
        </Card>
      )}
      {filament && (
        <Card className={filament.overall !== "can_start" ? "border-amber-500/40" : ""}>
          <CardHeader>
            <CardTitle>Filament for this batch</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="font-medium">
              {filament.overall === "can_start"
                ? "Can start now"
                : filament.overall === "partial"
                  ? "Can partially start"
                  : filament.overall === "wait_for_stock"
                    ? "Should wait for stock on order"
                    : "Requires another purchase"}
            </div>
            {filament.materials.map((m) => (
              <div key={m.product_id} className="flex justify-between gap-3">
                <span>
                  {m.label}: {(m.required_g / 1000).toFixed(1)} kg required
                </span>
                <span className="font-mono">
                  avail {(m.available_g / 1000).toFixed(1)} kg · on order {(m.on_order_g / 1000).toFixed(1)} kg
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
      <div className="grid gap-3 md:grid-cols-2">
        {run.items.map((item) => (
          <Card key={item.id}>
            <CardHeader>
              <CardTitle className="text-base">
                {item.part_sku} · {item.part_name}
              </CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-2 font-mono text-sm">
              <span>Required {item.required_qty}</span>
              <span>Printed {item.printed_qty}</span>
              <span>Passed QC {item.passed_qc}</span>
              <span>Failed QC {item.failed_qc}</span>
              <span>Still to print {item.remaining_to_print}</span>
              <span className="text-amber-200">Remaining good {item.remaining_qty}</span>
              <span className="col-span-2 text-xs text-zinc-500">{item.gcode_filename}</span>
            </CardContent>
          </Card>
        ))}
      </div>
      <Dialog open={pendingDelete} onOpenChange={(next) => !next && !deleting && setPendingDelete(false)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Delete {run.batch_code || run.name}?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            This removes the run from Production. Queued plates are cancelled. Finished print jobs stay in history. If a
            printer is still running a plate from this run, FarmOS will refuse until that job finishes.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setPendingDelete(false)} disabled={deleting}>
              Keep run
            </Button>
            <Button variant="destructive" onClick={confirmDelete} disabled={deleting}>
              {deleting ? "Deleting…" : "Delete run"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
