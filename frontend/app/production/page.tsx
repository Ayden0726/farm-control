"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { GCode, Part, Printer, ProductionRun } from "@/lib/types";
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
  const [name, setName] = useState("Flex Rack 5 — Batch ");
  const [selectedPrinters, setSelectedPrinters] = useState<string[]>([]);
  const [items, setItems] = useState<{ part_id: string; gcode_file_id: string; required_qty: number }[]>([
    { part_id: "", gcode_file_id: "", required_qty: 1 },
  ]);

  async function load() {
    setRuns(await api<ProductionRun[]>("/api/v1/production-runs"));
    setParts(await api<Part[]>("/api/v1/parts"));
    setGcode(await api<GCode[]>("/api/v1/gcode"));
    setPrinters(await api<Printer[]>("/api/v1/printers"));
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
          items: items.filter((i) => i.part_id && i.required_qty > 0),
        }),
      });
      toast.success("Production run created and queued");
      setOpen(false);
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          A run can include multiple G-code files, copy counts, and a restricted printer pool. Remaining quantity is
          required minus QC-passed parts.
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
                <Input value={name} onChange={(e) => setName(e.target.value)} required />
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
                <div key={idx} className="grid gap-2 rounded-md border border-white/10 p-2 sm:grid-cols-3">
                  <select
                    className="h-8 rounded-lg border border-input bg-transparent px-2 text-sm"
                    value={item.part_id}
                    onChange={(e) => {
                      const partId = e.target.value;
                      const match = gcode.find((g) => g.part_id === partId);
                      setItems((cur) =>
                        cur.map((c, i) =>
                          i === idx ? { ...c, part_id: partId, gcode_file_id: match?.id || "" } : c,
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
                    onChange={(e) =>
                      setItems((cur) => cur.map((c, i) => (i === idx ? { ...c, gcode_file_id: e.target.value } : c)))
                    }
                  >
                    <option value="">G-code…</option>
                    {gcode
                      .filter((g) => !item.part_id || g.part_id === item.part_id)
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
                  {run.queued_jobs} queued · {run.printing_jobs} printing · {run.completed_jobs} complete
                </div>
              </div>
              <StatusPill status={run.status} />
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
      </div>
    </div>
  );
}
