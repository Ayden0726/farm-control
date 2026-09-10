"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import type { Printer, Spool } from "@/lib/types";
import { StatusPill } from "@/components/status-pill";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { formatDuration, formatHours } from "@/lib/format";
import { QrDialog } from "@/components/qr-dialog";
import { toast } from "sonner";

export default function PrinterDetailPage() {
  const params = useParams<{ id: string }>();
  const [printer, setPrinter] = useState<Printer | null>(null);
  const [spools, setSpools] = useState<Spool[]>([]);
  const [notes, setNotes] = useState("");
  const [interval, setIntervalHours] = useState("200");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");

  async function load() {
    const p = await api<Printer>(`/api/v1/printers/${params.id}`);
    setPrinter(p);
    setNotes(p.maintenance_notes);
    setIntervalHours(String(p.maintenance_interval_hours));
    setBaseUrl(p.base_url || "");
    setSpools(await api<Spool[]>("/api/v1/filament"));
  }

  useEffect(() => {
    load();
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
  }, [params.id]);

  if (!printer) return <div className="text-zinc-500">Loading printer…</div>;

  async function save() {
    const id = params.id;
    try {
      await api(`/api/v1/printers/${id}`, {
        method: "PATCH",
        body: JSON.stringify({
          maintenance_notes: notes,
          maintenance_interval_hours: Number(interval),
          base_url: baseUrl || null,
          api_key: apiKey || undefined,
        }),
      });
      toast.success("Printer updated");
      setApiKey("");
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Save failed");
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle>{printer.name}</CardTitle>
            <div className="text-sm text-muted-foreground">
              {printer.model} · {printer.adapter_type}
            </div>
          </div>
          <StatusPill status={printer.status} />
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
            <div>
              <div className="text-zinc-500">Nozzle</div>
              <div className="font-mono text-lg">{printer.nozzle_temp.toFixed(1)}°</div>
            </div>
            <div>
              <div className="text-zinc-500">Bed</div>
              <div className="font-mono text-lg">{printer.bed_temp.toFixed(1)}°</div>
            </div>
            <div>
              <div className="text-zinc-500">Progress</div>
              <div className="font-mono text-lg">{printer.progress_percent.toFixed(0)}%</div>
            </div>
            <div>
              <div className="text-zinc-500">Remaining</div>
              <div className="font-mono text-lg">{formatDuration(printer.time_remaining_seconds)}</div>
            </div>
          </div>
          <div className="text-sm">
            Current file: <span className="font-mono">{printer.current_file || "—"}</span>
          </div>
          {printer.status === "waiting_for_bed_clear" && (
            <Button
              onClick={async () => {
                await api(`/api/v1/printers/${printer.id}/bed-cleared`, { method: "POST" });
                toast.success("Bed cleared");
                load();
              }}
            >
              Confirm bed cleared
            </Button>
          )}
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => api(`/api/v1/printers/${printer.id}/refresh`, { method: "POST" }).then(load)}>
              Refresh status
            </Button>
            <QrDialog kind="printer" token={printer.qr_token} label={printer.name} />
          </div>
          {printer.last_error && <p className="text-sm text-red-300">{printer.last_error}</p>}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Maintenance</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div>Print hours: {formatHours(printer.total_print_seconds)}</div>
          <div>Jobs: {printer.total_jobs} · Failed: {printer.failed_jobs}</div>
          <div>Hours until service: {printer.hours_until_maintenance ?? "—"}</div>
          <div className="space-y-1">
            <Label>Interval (print hours)</Label>
            <Input value={interval} onChange={(e) => setIntervalHours(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label>Notes</Label>
            <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>
          <Button
            variant="outline"
            onClick={async () => {
              await api(`/api/v1/maintenance/${printer.id}`, {
                method: "POST",
                body: JSON.stringify({ notes: "Shop-floor service logged from printer page", kind: "service" }),
              });
              toast.success("Maintenance logged — print-hour counter reset.");
              load();
            }}
          >
            Log maintenance now
          </Button>
        </CardContent>
      </Card>
      <Card className="lg:col-span-3">
        <CardHeader>
          <CardTitle>Connection & spool</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          <div className="space-y-2">
            <Label>Base URL</Label>
            <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="http://printer.local" />
            <Label>New API key (leave blank to keep current)</Label>
            <Input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
            <p className="text-xs text-zinc-500">
              {printer.has_api_key ? "An API key is stored on the server." : "No API key stored."} Credentials are never shown in the UI.
            </p>
            <Button onClick={save}>Save connection</Button>
          </div>
          <div className="space-y-2">
            <Label>Assigned spool</Label>
            <select
              className="h-8 w-full rounded-lg border border-input bg-transparent px-2 text-sm"
              value={printer.assigned_spool_id || ""}
              onChange={async (e) => {
                await api(`/api/v1/printers/${printer.id}/assign-spool`, {
                  method: "POST",
                  body: JSON.stringify({ spool_id: e.target.value || null }),
                });
                load();
              }}
            >
              <option value="">Unassigned</option>
              {spools.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.remaining_weight_g.toFixed(0)} g)
                </option>
              ))}
            </select>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
