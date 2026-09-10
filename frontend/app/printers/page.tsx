"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Printer } from "@/lib/types";
import { StatusPill } from "@/components/status-pill";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDuration, formatHours } from "@/lib/format";
import { toast } from "sonner";
import { QrDialog } from "@/components/qr-dialog";

export default function PrintersPage() {
  const [printers, setPrinters] = useState<Printer[]>([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    name: "",
    model: "",
    adapter_type: "simulated",
    base_url: "",
    api_key: "",
  });

  async function load() {
    setPrinters(await api<Printer[]>("/api/v1/printers"));
  }
  useEffect(() => {
    load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, []);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/api/v1/printers", {
        method: "POST",
        body: JSON.stringify({
          ...form,
          base_url: form.base_url || null,
          api_key: form.api_key || null,
        }),
      });
      toast.success("Printer added");
      setOpen(false);
      setForm({ name: "", model: "", adapter_type: "simulated", base_url: "", api_key: "" });
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          OctoPrint, Moonraker/Klipper, Creality K1/K2, and simulated adapters. API keys stay on the server.
        </p>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger render={<Button />}>Add printer</DialogTrigger>
          <DialogContent className="sm:max-w-lg">
            <DialogHeader>
              <DialogTitle>Add printer</DialogTitle>
            </DialogHeader>
            <form onSubmit={onCreate} className="space-y-3">
              <div className="space-y-1">
                <Label>Name</Label>
                <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
              </div>
              <div className="space-y-1">
                <Label>Model</Label>
                <Input
                  placeholder="Creality CR-6 Max"
                  value={form.model}
                  onChange={(e) => setForm({ ...form, model: e.target.value })}
                />
              </div>
              <div className="space-y-1">
                <Label>Connection</Label>
                <select
                  className="h-8 w-full rounded-lg border border-input bg-transparent px-2 text-sm"
                  value={form.adapter_type}
                  onChange={(e) => setForm({ ...form, adapter_type: e.target.value })}
                >
                  <option value="simulated">Simulated (development)</option>
                  <option value="octoprint">OctoPrint</option>
                  <option value="moonraker">Moonraker / Klipper</option>
                  <option value="creality">Creality K1 Max / K2 Pro</option>
                </select>
              </div>
              {form.adapter_type !== "simulated" && (
                <>
                  <div className="space-y-1">
                    <Label>Base URL</Label>
                    <Input
                      placeholder="http://192.168.1.50:80"
                      value={form.base_url}
                      onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                    />
                  </div>
                  <div className="space-y-1">
                    <Label>API key (stored encrypted, never sent back)</Label>
                    <Input
                      type="password"
                      value={form.api_key}
                      onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                    />
                  </div>
                </>
              )}
              <Button type="submit" className="w-full">
                Save printer
              </Button>
            </form>
          </DialogContent>
        </Dialog>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Printer</TableHead>
            <TableHead>Connection</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Temps</TableHead>
            <TableHead>Current file</TableHead>
            <TableHead>Progress</TableHead>
            <TableHead>Remaining</TableHead>
            <TableHead>Hours</TableHead>
            <TableHead></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {printers.map((p) => (
            <TableRow key={p.id}>
              <TableCell>
                <Link href={`/printers/${p.id}`} className="font-medium hover:text-amber-200">
                  {p.name}
                </Link>
                <div className="text-xs text-zinc-500">{p.model}</div>
              </TableCell>
              <TableCell className="capitalize">{p.adapter_type}</TableCell>
              <TableCell>
                <StatusPill status={p.status} />
              </TableCell>
              <TableCell className="font-mono text-xs">
                {p.nozzle_temp.toFixed(0)}° / {p.bed_temp.toFixed(0)}°
              </TableCell>
              <TableCell className="max-w-[180px] truncate text-xs">{p.current_file || "—"}</TableCell>
              <TableCell className="font-mono">{p.progress_percent.toFixed(0)}%</TableCell>
              <TableCell className="font-mono text-xs">{formatDuration(p.time_remaining_seconds)}</TableCell>
              <TableCell className="font-mono text-xs">{formatHours(p.total_print_seconds)}</TableCell>
              <TableCell>
                <QrDialog kind="printer" token={p.qr_token} label={p.name} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {printers.length === 0 && (
        <p className="text-sm text-zinc-500">No printers yet. Add a simulated printer to test the queue.</p>
      )}
    </div>
  );
}
