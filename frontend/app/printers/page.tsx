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
  const [pending, setPending] = useState<{ type: "retire" | "delete"; printer: Printer } | null>(null);
  const [acting, setActing] = useState(false);
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

  const active = printers.filter((p) => p.is_enabled);
  const retired = printers.filter((p) => !p.is_enabled);

  async function confirmAction() {
    if (!pending) return;
    setActing(true);
    try {
      if (pending.type === "retire") {
        await api(`/api/v1/printers/${pending.printer.id}/retire`, { method: "POST" });
        toast.success(`${pending.printer.name} retired. It will not take new jobs.`);
      } else {
        await api(`/api/v1/printers/${pending.printer.id}`, { method: "DELETE" });
        toast.success(`${pending.printer.name} deleted.`);
      }
      setPending(null);
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not update printer");
    } finally {
      setActing(false);
    }
  }

  async function restore(printer: Printer) {
    try {
      await api(`/api/v1/printers/${printer.id}/restore`, { method: "POST" });
      toast.success(`${printer.name} is back on the farm.`);
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not restore printer");
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
      <PrinterTable
        printers={active}
        onRetire={(p) => setPending({ type: "retire", printer: p })}
        onDelete={(p) => setPending({ type: "delete", printer: p })}
      />
      {active.length === 0 && (
        <p className="text-sm text-zinc-500">No active printers. Add one and FarmOS will check the connection first.</p>
      )}
      {retired.length > 0 && (
        <div className="space-y-2 pt-4">
          <h2 className="text-sm font-medium text-zinc-400">Retired</h2>
          <p className="text-xs text-zinc-500">
            Retired printers keep job history but do not take new work. Restore them to put them back on the farm.
          </p>
          <PrinterTable
            printers={retired}
            onRestore={restore}
            onDelete={(p) => setPending({ type: "delete", printer: p })}
          />
        </div>
      )}
      <Dialog open={!!pending} onOpenChange={(open) => !open && setPending(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              {pending?.type === "delete" ? `Delete ${pending.printer.name}?` : `Retire ${pending?.printer.name}?`}
            </DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            {pending?.type === "delete"
              ? "This removes the printer from the farm. Print history stays. You cannot undo this — add the machine again if it comes back."
              : "It will not be assigned new jobs. Restore it later from the Retired list if the machine returns."}
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setPending(null)} disabled={acting}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={confirmAction} disabled={acting}>
              {acting ? "Working…" : pending?.type === "delete" ? "Delete printer" : "Retire printer"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function PrinterTable({
  printers,
  onRetire,
  onRestore,
  onDelete,
}: {
  printers: Printer[];
  onRetire?: (p: Printer) => void;
  onRestore?: (p: Printer) => void;
  onDelete?: (p: Printer) => void;
}) {
  if (printers.length === 0) return null;
  return (
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
          <TableRow key={p.id} className={p.is_enabled ? "" : "opacity-70"}>
            <TableCell>
              <Link href={`/printers/${p.id}`} className="font-medium hover:text-amber-200">
                {p.name}
              </Link>
              <div className="text-xs text-zinc-500">{p.model}</div>
            </TableCell>
            <TableCell className="capitalize">{p.adapter_type}</TableCell>
            <TableCell>
              <StatusPill status={p.is_enabled ? p.status : "retired"} />
            </TableCell>
            <TableCell className="font-mono text-xs">
              {p.nozzle_temp.toFixed(0)}° / {p.bed_temp.toFixed(0)}°
            </TableCell>
            <TableCell className="max-w-[180px] truncate text-xs">{p.current_file || "—"}</TableCell>
            <TableCell className="font-mono">{p.progress_percent.toFixed(0)}%</TableCell>
            <TableCell className="font-mono text-xs">{formatDuration(p.time_remaining_seconds)}</TableCell>
            <TableCell className="font-mono text-xs">{formatHours(p.total_print_seconds)}</TableCell>
            <TableCell>
              <div className="flex flex-wrap items-center justify-end gap-1">
                <QrDialog kind="printer" token={p.qr_token} label={p.name} />
                {onRestore && (
                  <Button size="xs" variant="outline" onClick={() => onRestore(p)}>
                    Restore
                  </Button>
                )}
                {onRetire && p.is_enabled && (
                  <Button size="xs" variant="outline" onClick={() => onRetire(p)}>
                    Retire
                  </Button>
                )}
                {onDelete && (
                  <Button size="xs" variant="destructive" onClick={() => onDelete(p)}>
                    Delete
                  </Button>
                )}
              </div>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
