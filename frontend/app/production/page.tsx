"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { GCode, Part, Printer, Product, ProductionRun } from "@/lib/types";
import { StatusPill } from "@/components/status-pill";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";

export default function ProductionPage() {
  const [runs, setRuns] = useState<ProductionRun[]>([]);
  const [parts, setParts] = useState<Part[]>([]);
  const [gcode, setGcode] = useState<GCode[]>([]);
  const [printers, setPrinters] = useState<Printer[]>([]);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [selectedPrinters, setSelectedPrinters] = useState<string[]>([]);
  const [items, setItems] = useState<{ part_id: string; gcode_file_id: string; required_qty: number }[]>([
    { part_id: "", gcode_file_id: "", required_qty: 1 },
  ]);
  const [products, setProducts] = useState<Product[]>([]);
  const [productId, setProductId] = useState("");
  const [productQty, setProductQty] = useState("1");
  const [includeOptional, setIncludeOptional] = useState(false);
  const [addingProduct, setAddingProduct] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<ProductionRun | null>(null);
  const [deleting, setDeleting] = useState(false);

  async function load() {
    setRuns(await api<ProductionRun[]>("/api/v1/production-runs"));
    setParts(await api<Part[]>("/api/v1/parts"));
    setGcode(await api<GCode[]>("/api/v1/gcode"));
    setPrinters(await api<Printer[]>("/api/v1/printers"));
    setProducts(await api<Product[]>("/api/v1/products"));
  }
  useEffect(() => {
    load();
  }, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/api/v1/production-runs", {
        method: "POST",
        body: JSON.stringify({
          name,
          printer_ids: selectedPrinters,
          start_immediately: true,
          items: items
            .filter((i) => i.part_id && i.required_qty > 0)
            .map((i) => ({
              part_id: i.part_id,
              gcode_file_id: i.gcode_file_id || null,
              required_qty: i.required_qty,
            })),
        }),
      });
      toast.success("Production run created and queued");
      setOpen(false);
      setName("");
      setProductId("");
      setItems([{ part_id: "", gcode_file_id: "", required_qty: 1 }]);
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    }
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await api(`/api/v1/production-runs/${pendingDelete.id}`, { method: "DELETE" });
      toast.success(`Deleted ${pendingDelete.batch_code || pendingDelete.name}`);
      setPendingDelete(null);
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not delete run");
    } finally {
      setDeleting(false);
    }
  }

  async function addProductBom() {
    if (!productId) {
      toast.error("Pick a product from the catalog first");
      return;
    }
    setAddingProduct(true);
    try {
      const qty = Math.max(1, Number(productQty) || 1);
      const res = await api<{
        product_sku: string;
        product_name: string;
        items: { part_id: string; gcode_file_id: string | null; gcode_filename: string | null; required_qty: number }[];
        missing_gcode: string[];
        optional_skipped: string[];
        multi_file_parts: string[];
      }>(`/api/v1/products/${productId}/run-items?quantity=${qty}&include_optional=${includeOptional}`);
      const next = res.items.map((row) => ({
        part_id: row.part_id,
        gcode_file_id: row.gcode_file_id || "",
        required_qty: row.required_qty,
      }));
      if (!next.length) {
        toast.error(`${res.product_sku} has no BOM parts to produce`);
        return;
      }
      setItems((cur) => {
        const kept = cur.filter((row) => row.part_id);
        return kept.length ? [...kept, ...next] : next;
      });
      if (!name.trim()) {
        setName(`${res.product_sku} × ${qty}`);
      }
      const files = res.items.filter((row) => row.gcode_file_id).length;
      toast.success(
        `Added ${files} G-code file${files === 1 ? "" : "s"} from ${res.product_sku} (${res.items.length} part line${res.items.length === 1 ? "" : "s"}).`,
      );
      if (res.missing_gcode.length) {
        toast.message(`No G-code tagged for ${res.missing_gcode.join(", ")}. Tag files on the Library tab.`);
      }
      if (res.multi_file_parts.length) {
        toast.message(
          `${res.multi_file_parts.join(", ")} has more than one tagged file; each was added at full quantity. Remove extras if you only want one plate.`,
        );
      }
      if (res.optional_skipped.length) {
        toast.message(`Skipped optional ${res.optional_skipped.join(", ")}.`);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not load product BOM");
    } finally {
      setAddingProduct(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          A run can include a catalog product (BOM + tagged G-code) or individual parts. Remaining quantity is required
          minus QC-passed parts.
        </p>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger render={<Button />}>New production run</DialogTrigger>
          <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
            <DialogHeader>
              <DialogTitle>Create production run</DialogTitle>
            </DialogHeader>
            <form onSubmit={create} className="space-y-3">
              <div className="space-y-1">
                <Label>Name</Label>
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="RK-FR5 × 5" required />
              </div>
              <div className="space-y-2 rounded-md border border-white/10 p-3">
                <Label>Add from Products / BOM</Label>
                <p className="text-xs text-zinc-500">
                  Pulls every required BOM part and every non-archived G-code tagged to that part.
                </p>
                <div className="grid gap-2 sm:grid-cols-[1fr_70px_auto]">
                  <select
                    className="h-8 rounded-lg border border-input bg-transparent px-2 text-sm"
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
                  <Input
                    type="number"
                    min={1}
                    value={productQty}
                    onChange={(e) => setProductQty(e.target.value)}
                    aria-label="Product quantity"
                  />
                  <Button type="button" variant="outline" disabled={addingProduct || !productId} onClick={addProductBom}>
                    {addingProduct ? "Adding…" : "Add product"}
                  </Button>
                </div>
                <label className="flex items-center gap-2 text-xs text-zinc-400">
                  <input type="checkbox" checked={includeOptional} onChange={(e) => setIncludeOptional(e.target.checked)} />
                  Include optional BOM accessories
                </label>
              </div>
              <div className="space-y-1">
                <Label>Allowed printers</Label>
                <div className="grid gap-1">
                  {printers.map((p) => (
                    <label key={p.id} className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={selectedPrinters.includes(p.id)}
                        onChange={(e) =>
                          setSelectedPrinters((cur) =>
                            e.target.checked ? [...cur, p.id] : cur.filter((id) => id !== p.id),
                          )
                        }
                      />
                      {p.name}
                    </label>
                  ))}
                </div>
              </div>
              {items.map((item, idx) => (
                <div key={idx} className="grid gap-2 rounded-md border border-white/10 p-2 sm:grid-cols-[1fr_1fr_70px_auto]">
                  <select
                    className="h-8 rounded-lg border border-input bg-transparent px-2 text-sm"
                    value={item.part_id}
                    onChange={(e) => {
                      const partId = e.target.value;
                      const match = gcode.find((g) => !g.is_archived && g.part_id === partId);
                      setItems((cur) =>
                        cur.map((c, i) =>
                          i === idx
                            ? {
                                ...c,
                                part_id: partId,
                                gcode_file_id: match?.id || "",
                                required_qty: match?.quantity_per_file || c.required_qty,
                              }
                            : c,
                        ),
                      );
                    }}
                  >
                    <option value="">Part…</option>
                    {parts.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.sku}
                      </option>
                    ))}
                  </select>
                  <select
                    className="h-8 rounded-lg border border-input bg-transparent px-2 text-sm"
                    value={item.gcode_file_id}
                    onChange={(e) => {
                      const gcodeId = e.target.value;
                      const match = gcode.find((g) => g.id === gcodeId);
                      setItems((cur) =>
                        cur.map((c, i) =>
                          i === idx
                            ? {
                                ...c,
                                gcode_file_id: gcodeId,
                                required_qty: match?.quantity_per_file || c.required_qty,
                              }
                            : c,
                        ),
                      );
                    }}
                  >
                    <option value="">G-code…</option>
                    {gcode
                      .filter((g) => !g.is_archived && (!item.part_id || g.part_id === item.part_id))
                      .map((g) => (
                        <option key={g.id} value={g.id}>
                          {g.filename} (×{g.quantity_per_file})
                        </option>
                      ))}
                  </select>
                  <Input
                    type="number"
                    min={1}
                    value={item.required_qty}
                    onChange={(e) =>
                      setItems((cur) =>
                        cur.map((c, i) => (i === idx ? { ...c, required_qty: Number(e.target.value) } : c)),
                      )
                    }
                  />
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      setItems((cur) =>
                        cur.length <= 1
                          ? [{ part_id: "", gcode_file_id: "", required_qty: 1 }]
                          : cur.filter((_, i) => i !== idx),
                      )
                    }
                  >
                    Remove
                  </Button>
                </div>
              ))}
              <Button
                type="button"
                variant="outline"
                onClick={() => setItems((c) => [...c, { part_id: "", gcode_file_id: "", required_qty: 1 }])}
              >
                Add part
              </Button>
              <Button type="submit" className="w-full">
                Queue production
              </Button>
            </form>
          </DialogContent>
        </Dialog>
      </div>
      <div className="grid gap-4">
        {runs.map((run) => (
          <Card key={run.id}>
            <CardHeader className="flex flex-row items-center justify-between">
              <div>
                <CardTitle>
                  <Link href={`/production/${run.id}`} className="hover:text-amber-200">
                    {run.batch_code ? `${run.batch_code} · ${run.name}` : run.name}
                  </Link>
                </CardTitle>
                <div className="text-xs text-zinc-500">
                  {run.needed_by ? `Needed by ${run.needed_by.slice(0, 10)} · ` : ""}
                  {run.queued_jobs} queued · {run.printing_jobs} printing · {run.completed_jobs} complete
                </div>
              </div>
              <div className="flex items-center gap-2">
                <StatusPill status={run.status} />
                <Button size="sm" variant="destructive" onClick={() => setPendingDelete(run)}>
                  Delete
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                {run.items.map((item) => (
                  <div key={item.id} className="rounded-md border border-white/8 p-3 text-sm">
                    <div className="font-medium">{item.part_sku}</div>
                    <div className="text-xs text-zinc-500">{item.gcode_filename}</div>
                    <div className="mt-2 grid grid-cols-2 gap-1 font-mono text-xs">
                      <span>Req {item.required_qty}</span>
                      <span>Printed {item.printed_qty}</span>
                      <span>Passed {item.passed_qc}</span>
                      <span>Failed {item.failed_qc}</span>
                      <span className="col-span-2 text-amber-200">Remaining {item.remaining_qty}</span>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        ))}
        {runs.length === 0 && (
          <p className="text-sm text-muted-foreground">No production runs yet. Create one to queue plates.</p>
        )}
      </div>
      <Dialog open={!!pendingDelete} onOpenChange={(next) => !next && setPendingDelete(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Delete {pendingDelete?.batch_code || pendingDelete?.name}?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            This removes the run from Production. Queued plates are cancelled. Finished print jobs stay in history,
            unlinked from the batch. If a printer is still running a plate from this run, FarmOS will refuse until that
            job finishes.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setPendingDelete(null)} disabled={deleting}>
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
