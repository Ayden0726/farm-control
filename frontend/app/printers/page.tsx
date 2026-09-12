"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { Printer } from "@/lib/types";
import { StatusPill } from "@/components/status-pill";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { formatDuration, formatHours } from "@/lib/format";
import { toast } from "sonner";
import { QrDialog } from "@/components/qr-dialog";

const URL_HINT: Record<string, string> = {
  octoprint: "http://192.168.1.50",
  moonraker: "http://192.168.1.50:7125",
  creality: "http://192.168.1.50:4408",
};

export default function PrintersPage() {
  const [printers, setPrinters] = useState<Printer[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [howToFix, setHowToFix] = useState<string[]>([]);
  const [form, setForm] = useState({
    name: "",
    model: "",
    adapter_type: "octoprint",
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

  const urlPlaceholder = useMemo(
    () => URL_HINT[form.adapter_type] || "http://192.168.1.50",
    [form.adapter_type],
  );

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setHowToFix([]);
    setBusy(true);
    try {
      await api("/api/v1/printers", {
        method: "POST",
        body: JSON.stringify({
          ...form,
          base_url: form.base_url || null,
          api_key: form.api_key || null,
        }),
        signal: AbortSignal.timeout(45000),
      });
      toast.success("Connection verified. Printer saved.");
      setOpen(false);
      setForm({ name: "", model: "", adapter_type: "octoprint", base_url: "", api_key: "" });
      load();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not add printer";
      setError(message);
      setHowToFix(err instanceof ApiError ? err.howToFix : []);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          OctoPrint, Moonraker/Klipper, Creality K1/K2, and simulated adapters. FarmOS verifies the
          connection before it saves the printer. API keys stay on the server.
        </p>
        <Dialog
          open={open}
          onOpenChange={(next) => {
            setOpen(next);
            if (!next) {
              setError(null);
              setHowToFix([]);
            }
          }}
        >
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
                  placeholder="Creality K1 Max"
                  value={form.model}
                  onChange={(e) => setForm({ ...form, model: e.target.value })}
                />
              </div>
              <div className="space-y-1">
                <Label>Connection</Label>
                <select
                  className="h-8 w-full rounded-lg border border-input bg-transparent px-2 text-sm"
                  value={form.adapter_type}
                  onChange={(e) => setForm({ ...form, adapter_type: e.target.value, base_url: "" })}
                >
                  <option value="octoprint">OctoPrint</option>
                  <option value="moonraker">Moonraker / Klipper</option>
                  <option value="creality">Creality K1 Max / K2 Pro</option>
                  <option value="simulated">Simulated (no hardware)</option>
                </select>
              </div>
              {form.adapter_type !== "simulated" && (
                <>
                  <div className="space-y-1">
                    <Label>Printer URL</Label>
                    <Input
                      placeholder={urlPlaceholder}
                      value={form.base_url}
                      onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                      required
                    />
                    <p className="text-xs text-zinc-500">
                      Use the printer’s LAN IP as seen from this FarmOS server — not localhost.
                    </p>
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
              {error && (
                <Alert variant="destructive">
                  <AlertTitle>Could not connect</AlertTitle>
                  <AlertDescription>
                    <p>{error}</p>
                    {howToFix.length > 0 && (
                      <ul className="mt-2 list-disc space-y-1 pl-4 text-left">
                        {howToFix.map((step) => (
                          <li key={step}>{step}</li>
                        ))}
                      </ul>
                    )}
                  </AlertDescription>
                </Alert>
              )}
              <Button type="submit" className="w-full" disabled={busy}>
                {busy ? "Checking connection…" : "Verify connection and save"}
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
        <p className="text-sm text-zinc-500">No printers yet. Add one and FarmOS will check the connection first.</p>
      )}
    </div>
  );
}
