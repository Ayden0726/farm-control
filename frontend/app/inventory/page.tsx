"use client";

import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { toast } from "sonner";
import { QrDialog } from "@/components/qr-dialog";
import type { Part } from "@/lib/types";

type Stock = {
  part_id: string;
  sku: string;
  name: string;
  quantity_on_hand: number;
  quantity_reserved: number;
  quantity_available: number;
  awaiting_qc: number;
};
type Qc = {
  id: string;
  part_sku: string;
  part_name: string;
  quantity: number;
  passed: number;
  failed: number;
  status: string;
  gcode_filename: string | null;
};
type Bin = { id: string; name: string; location: string; part_sku: string | null; qr_token: string };

export default function InventoryPage() {
  const [stock, setStock] = useState<Stock[]>([]);
  const [qc, setQc] = useState<Qc[]>([]);
  const [bins, setBins] = useState<Bin[]>([]);
  const [parts, setParts] = useState<Part[]>([]);
  const [pass, setPass] = useState<Record<string, string>>({});
  const [fail, setFail] = useState<Record<string, string>>({});
  const [binName, setBinName] = useState("");
  const [binLoc, setBinLoc] = useState("");
  const [binPart, setBinPart] = useState("");

  async function load() {
    setStock(await api<Stock[]>("/api/v1/inventory"));
    setQc(await api<Qc[]>("/api/v1/qc"));
    setBins(await api<Bin[]>("/api/v1/bins"));
    setParts(await api<Part[]>("/api/v1/parts"));
  }
  useEffect(() => {
    load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, []);

  async function inspect(id: string) {
    try {
      await api(`/api/v1/qc/${id}`, {
        method: "POST",
        body: JSON.stringify({
          passed: Number(pass[id] || 0),
          failed: Number(fail[id] || 0),
        }),
      });
      toast.success("QC recorded. Passed parts entered finished inventory; failed parts logged as scrap.");
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "QC failed");
    }
  }

  async function addBin(e: FormEvent) {
    e.preventDefault();
    await api("/api/v1/bins", {
      method: "POST",
      body: JSON.stringify({ name: binName, location: binLoc, part_id: binPart || null }),
    });
    setBinName("");
    load();
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Awaiting QC</CardTitle>
        </CardHeader>
        <CardContent>
          {qc.length === 0 && <p className="text-sm text-zinc-500">No prints waiting inspection.</p>}
          <div className="space-y-3">
            {qc.map((batch) => (
              <div key={batch.id} className="flex flex-wrap items-end gap-2 rounded-md border border-white/8 p-3">
                <div className="min-w-40 flex-1">
                  <div className="font-medium">{batch.part_sku}</div>
                  <div className="text-xs text-zinc-500">
                    {batch.gcode_filename} · {batch.quantity - batch.passed - batch.failed} of {batch.quantity} left
                  </div>
                </div>
                <div>
                  <Label className="text-xs">Passed</Label>
                  <Input
                    className="w-20"
                    type="number"
                    min={0}
                    value={pass[batch.id] ?? ""}
                    onChange={(e) => setPass({ ...pass, [batch.id]: e.target.value })}
                  />
                </div>
                <div>
                  <Label className="text-xs">Failed</Label>
                  <Input
                    className="w-20"
                    type="number"
                    min={0}
                    value={fail[batch.id] ?? ""}
                    onChange={(e) => setFail({ ...fail, [batch.id]: e.target.value })}
                  />
                </div>
                <Button onClick={() => inspect(batch.id)}>Record QC</Button>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>SKU</TableHead>
            <TableHead>On hand</TableHead>
            <TableHead>Reserved</TableHead>
            <TableHead>Available</TableHead>
            <TableHead>Awaiting QC</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {stock.map((s) => (
            <TableRow key={s.part_id}>
              <TableCell>
                <div className="font-medium">{s.sku}</div>
                <div className="text-xs text-zinc-500">{s.name}</div>
              </TableCell>
              <TableCell>{s.quantity_on_hand}</TableCell>
              <TableCell>{s.quantity_reserved}</TableCell>
              <TableCell>{s.quantity_available}</TableCell>
              <TableCell>{s.awaiting_qc}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <Card>
        <CardHeader>
          <CardTitle>Finished-part bins</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <form onSubmit={addBin} className="flex flex-wrap gap-2">
            <Input placeholder="Bin name" value={binName} onChange={(e) => setBinName(e.target.value)} required />
            <Input placeholder="Location" value={binLoc} onChange={(e) => setBinLoc(e.target.value)} />
            <select
              className="h-8 rounded-lg border border-input bg-transparent px-2 text-sm"
              value={binPart}
              onChange={(e) => setBinPart(e.target.value)}
            >
              <option value="">Part…</option>
              {parts.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.sku}
                </option>
              ))}
            </select>
            <Button type="submit">Add bin</Button>
          </form>
          {bins.map((b) => (
            <div key={b.id} className="flex items-center justify-between text-sm">
              <span>
                {b.name} · {b.location} · {b.part_sku || "mixed"}
              </span>
              <QrDialog kind="bin" token={b.qr_token} label={b.name} />
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
