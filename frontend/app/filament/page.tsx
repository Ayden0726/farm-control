"use client";

import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Spool } from "@/lib/types";
import { StatusPill } from "@/components/status-pill";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatGrams, formatMoney } from "@/lib/format";
import { QrDialog } from "@/components/qr-dialog";
import { toast } from "sonner";

export default function FilamentPage() {
  const [spools, setSpools] = useState<Spool[]>([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    name: "",
    manufacturer: "Sunlu",
    material: "PETG",
    color: "Black",
    initial_weight_g: "1000",
    cost: "24",
    drying_status: "dry",
  });

  async function load() {
    setSpools(await api<Spool[]>("/api/v1/filament"));
  }
  useEffect(() => {
    load();
  }, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/api/v1/filament", {
        method: "POST",
        body: JSON.stringify({
          ...form,
          initial_weight_g: Number(form.initial_weight_g),
          cost: Number(form.cost),
        }),
      });
      toast.success("Spool added");
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
          PETG is the default material, but any polymer can be tracked. Usage is deducted when a print completes.
        </p>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger render={<Button />}>Add spool</DialogTrigger>
          <DialogContent className="sm:max-w-lg">
            <DialogHeader>
              <DialogTitle>Add filament spool</DialogTitle>
            </DialogHeader>
            <form onSubmit={create} className="grid gap-3 sm:grid-cols-2">
              {(
                [
                  ["name", "Name"],
                  ["manufacturer", "Manufacturer"],
                  ["material", "Material"],
                  ["color", "Colour"],
                  ["initial_weight_g", "Initial weight (g)"],
                  ["cost", "Cost"],
                ] as const
              ).map(([key, label]) => (
                <div key={key} className="space-y-1">
                  <Label>{label}</Label>
                  <Input value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} required />
                </div>
              ))}
              <div className="space-y-1 sm:col-span-2">
                <Label>Drying</Label>
                <select
                  className="h-8 w-full rounded-lg border border-input bg-transparent px-2 text-sm"
                  value={form.drying_status}
                  onChange={(e) => setForm({ ...form, drying_status: e.target.value })}
                >
                  <option value="dry">Dry</option>
                  <option value="drying">Drying</option>
                  <option value="needs_drying">Needs drying</option>
                  <option value="unknown">Unknown</option>
                </select>
              </div>
              <Button type="submit" className="sm:col-span-2">
                Save spool
              </Button>
            </form>
          </DialogContent>
        </Dialog>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Spool</TableHead>
            <TableHead>Material</TableHead>
            <TableHead>Remaining</TableHead>
            <TableHead>Cost / kg</TableHead>
            <TableHead>Printer</TableHead>
            <TableHead>Drying</TableHead>
            <TableHead></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {spools.map((s) => (
            <TableRow key={s.id} className={s.is_low ? "bg-amber-500/5" : ""}>
              <TableCell>
                <div className="font-medium">{s.name}</div>
                <div className="text-xs text-zinc-500">
                  {s.manufacturer} · {s.color}
                </div>
              </TableCell>
              <TableCell>{s.material}</TableCell>
              <TableCell className={s.is_low ? "text-amber-300" : ""}>
                {formatGrams(s.remaining_weight_g)} / {formatGrams(s.initial_weight_g)}
              </TableCell>
              <TableCell>{formatMoney(s.cost_per_kg)}</TableCell>
              <TableCell>{s.assigned_printer_name || "—"}</TableCell>
              <TableCell>
                <StatusPill status={s.drying_status} />
              </TableCell>
              <TableCell className="flex gap-1">
                <QrDialog kind="spool" token={s.qr_token} label={s.name} />
                <Button
                  size="xs"
                  variant="outline"
                  onClick={async () => {
                    await api(`/api/v1/filament/${s.id}/archive`, { method: "POST" });
                    load();
                  }}
                >
                  Archive
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
