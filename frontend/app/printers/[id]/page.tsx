"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ApiError, api } from "@/lib/api";
import type { Printer, Spool } from "@/lib/types";
import { StatusPill } from "@/components/status-pill";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { formatDuration, formatHours } from "@/lib/format";
import { QrDialog } from "@/components/qr-dialog";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import { PrinterCamera } from "@/components/printer-camera";
import { NozzleFields } from "@/components/nozzle-fields";
import { optionalMm } from "@/lib/printer-geometry";

export default function PrinterDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [printer, setPrinter] = useState<Printer | null>(null);
  const [spools, setSpools] = useState<Spool[]>([]);
  const [notes, setNotes] = useState("");
  const [interval, setIntervalHours] = useState("200");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [howToFix, setHowToFix] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<"retire" | "delete" | null>(null);
  const [acting, setActing] = useState(false);
  const [profile, setProfile] = useState({
    build_x_mm: "",
    build_y_mm: "",
    build_z_mm: "",
    usable_x_mm: "",
    usable_y_mm: "",
    usable_z_mm: "",
    nozzle_diameter_mm: "",
    nozzle_material: "",
    supported_materials: "",
    max_nozzle_temp_c: "",
    max_bed_temp_c: "",
    build_plate_type: "",
    slicer_profile: "",
    firmware: "",
    unattended_mode: "allowed",
    avg_power_watts: "180",
    machine_rate_per_hour: "0",
    camera_snapshot_url: "",
    camera_stream_url: "",
    camera_auth: "",
  });
  const [downtimeReason, setDowntimeReason] = useState("planned_maintenance");
  const [cameraOpen, setCameraOpen] = useState(false);
  const [templateName, setTemplateName] = useState("");
  const [maintKind, setMaintKind] = useState("service");
  const [maintNozzle, setMaintNozzle] = useState("");
  const [maintNozzleMaterial, setMaintNozzleMaterial] = useState("");
  const [loggingMaint, setLoggingMaint] = useState(false);

  async function load() {
    const p = await api<Printer>(`/api/v1/printers/${params.id}`);
    setPrinter(p);
    setNotes(p.maintenance_notes);
    setIntervalHours(String(p.maintenance_interval_hours));
    setBaseUrl(p.base_url || "");
    setMaintNozzle(p.nozzle_diameter_mm != null ? String(p.nozzle_diameter_mm) : "0.4");
    setMaintNozzleMaterial(p.nozzle_material || "Brass");
    setTemplateName(p.model ? `${p.model} ${p.nozzle_diameter_mm ?? ""}mm`.trim() : p.name);
    setProfile({
      build_x_mm: p.build_x_mm != null ? String(p.build_x_mm) : "",
      build_y_mm: p.build_y_mm != null ? String(p.build_y_mm) : "",
      build_z_mm: p.build_z_mm != null ? String(p.build_z_mm) : "",
      usable_x_mm: p.usable_x_mm != null ? String(p.usable_x_mm) : "",
      usable_y_mm: p.usable_y_mm != null ? String(p.usable_y_mm) : "",
      usable_z_mm: p.usable_z_mm != null ? String(p.usable_z_mm) : "",
      nozzle_diameter_mm: p.nozzle_diameter_mm != null ? String(p.nozzle_diameter_mm) : "",
      nozzle_material: p.nozzle_material || "",
      supported_materials: (p.supported_materials || []).join(", "),
      max_nozzle_temp_c: p.max_nozzle_temp_c != null ? String(p.max_nozzle_temp_c) : "",
      max_bed_temp_c: p.max_bed_temp_c != null ? String(p.max_bed_temp_c) : "",
      build_plate_type: p.build_plate_type || "",
      slicer_profile: p.slicer_profile || "",
      firmware: p.firmware || "",
      unattended_mode: p.unattended_mode || "allowed",
      avg_power_watts: String(p.avg_power_watts ?? 180),
      machine_rate_per_hour: String(p.machine_rate_per_hour ?? 0),
      camera_snapshot_url: "",
      camera_stream_url: "",
      camera_auth: "",
    });
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
    setError(null);
    setHowToFix([]);
    setBusy(true);
    try {
      await api(`/api/v1/printers/${id}`, {
        method: "PATCH",
        body: JSON.stringify({
          maintenance_notes: notes,
          maintenance_interval_hours: Number(interval),
          base_url: baseUrl || null,
          api_key: apiKey || undefined,
        }),
        signal: AbortSignal.timeout(45000),
      });
      toast.success("Connection verified. Printer updated.");
      setApiKey("");
      load();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Save failed";
      setError(message);
      setHowToFix(err instanceof ApiError ? err.howToFix : []);
      toast.error(message);
    } finally {
      setBusy(false);
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
          <StatusPill status={printer.is_enabled ? printer.status : "retired"} />
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
          {printer.camera_configured && (
            <div className="space-y-2">
              <PrinterCamera printerId={printer.id} className="h-40 w-full" />
              <div className="flex items-center justify-between text-xs text-zinc-500">
                <span>Camera {printer.camera_status || "unknown"} — credentials stay on the server</span>
                <Button size="xs" variant="outline" onClick={() => setCameraOpen(true)}>
                  Larger view
                </Button>
              </div>
            </div>
          )}
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
          {!printer.is_enabled && (
            <p className="text-sm text-amber-200">
              This printer is retired. It will not take new jobs until you restore it.
            </p>
          )}
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
          <div className="space-y-1">
            <Label>Kind</Label>
            <select
              className="h-8 w-full rounded-lg border border-input bg-transparent px-2 text-sm"
              value={maintKind}
              onChange={(e) => setMaintKind(e.target.value)}
            >
              <option value="service">Service</option>
              <option value="nozzle">Nozzle change</option>
              <option value="other">Other</option>
            </select>
          </div>
          <NozzleFields
            diameter={maintNozzle}
            material={maintNozzleMaterial}
            onDiameter={setMaintNozzle}
            onMaterial={setMaintNozzleMaterial}
          />
          <p className="text-xs text-zinc-500">
            Logging a nozzle size updates this printer and writes it on the maintenance history. The slicer uses the
            installed nozzle for packing.
          </p>
          <Button
            variant="outline"
            disabled={loggingMaint}
            onClick={async () => {
              setLoggingMaint(true);
              try {
                await api(`/api/v1/maintenance/${printer.id}`, {
                  method: "POST",
                  body: JSON.stringify({
                    notes: notes || undefined,
                    kind: maintKind,
                    nozzle_diameter_mm: optionalMm(maintNozzle),
                    nozzle_material: maintNozzleMaterial,
                  }),
                });
                toast.success("Maintenance logged — nozzle and print-hour counter saved.");
                load();
              } catch (err) {
                toast.error(err instanceof Error ? err.message : "Could not log maintenance");
              } finally {
                setLoggingMaint(false);
              }
            }}
          >
            {loggingMaint ? "Saving…" : "Log maintenance"}
          </Button>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Remove from farm</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p className="text-muted-foreground">
            Retire keeps the printer and its history but stops new jobs. Delete removes it from the farm; job
            history stays.
          </p>
          <div className="flex flex-wrap gap-2">
            {printer.is_enabled ? (
              <Button variant="outline" onClick={() => setPending("retire")}>
                Retire printer
              </Button>
            ) : (
              <Button
                variant="outline"
                onClick={async () => {
                  try {
                    await api(`/api/v1/printers/${printer.id}/restore`, { method: "POST" });
                    toast.success("Printer restored to the farm.");
                    load();
                  } catch (err) {
                    toast.error(err instanceof Error ? err.message : "Could not restore");
                  }
                }}
              >
                Restore printer
              </Button>
            )}
            <Button variant="destructive" onClick={() => setPending("delete")}>
              Delete printer
            </Button>
          </div>
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
              {printer.has_api_key ? "An API key is stored on the server." : "No API key stored."} Credentials are never
              shown in the UI. Use http:// and the printer’s LAN IP, not localhost, and not https://.
            </p>
            {error && (
              <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-200">
                <div className="font-medium">Could not connect</div>
                <p className="mt-1">{error}</p>
                {howToFix.length > 0 && (
                  <ul className="mt-2 list-disc space-y-1 pl-4">
                    {howToFix.map((step) => (
                      <li key={step}>{step}</li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            <Button onClick={save} disabled={busy}>
              {busy ? "Checking connection…" : "Verify connection and save"}
            </Button>
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
      <Card className="lg:col-span-3">
        <CardHeader>
          <CardTitle>Compatibility profile</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-3">
          {[
            ["build_x_mm", "Build X mm"],
            ["build_y_mm", "Build Y mm"],
            ["build_z_mm", "Build Z mm"],
            ["usable_x_mm", "Usable X mm"],
            ["usable_y_mm", "Usable Y mm"],
            ["usable_z_mm", "Usable Z mm"],
            ["supported_materials", "Materials (comma)"],
            ["max_nozzle_temp_c", "Max nozzle °C"],
            ["max_bed_temp_c", "Max bed °C"],
            ["build_plate_type", "Build plate"],
            ["slicer_profile", "Slicer profile"],
            ["firmware", "Firmware"],
            ["avg_power_watts", "Avg watts"],
            ["machine_rate_per_hour", "Machine $/h"],
          ].map(([key, label]) => (
            <div key={key} className="space-y-1">
              <Label>{label}</Label>
              <Input
                value={(profile as Record<string, string>)[key]}
                onChange={(e) => setProfile({ ...profile, [key]: e.target.value })}
              />
            </div>
          ))}
          <div className="md:col-span-3">
            <NozzleFields
              diameter={profile.nozzle_diameter_mm}
              material={profile.nozzle_material}
              onDiameter={(nozzle_diameter_mm) => setProfile({ ...profile, nozzle_diameter_mm })}
              onMaterial={(nozzle_material) => setProfile({ ...profile, nozzle_material })}
            />
          </div>
          <div className="space-y-1">
            <Label>Unattended mode</Label>
            <select
              className="h-8 w-full rounded-lg border border-input bg-transparent px-2 text-sm"
              value={profile.unattended_mode}
              onChange={(e) => setProfile({ ...profile, unattended_mode: e.target.value })}
            >
              <option value="allowed">Allowed unattended</option>
              <option value="supervision">Supervision required</option>
              <option value="disabled_overnight">Disabled overnight</option>
            </select>
          </div>
          <div className="space-y-1">
            <Label>Camera snapshot URL</Label>
            <Input
              value={profile.camera_snapshot_url}
              onChange={(e) => setProfile({ ...profile, camera_snapshot_url: e.target.value })}
              placeholder="http://printer/webcam/?action=snapshot"
            />
          </div>
          <div className="space-y-1">
            <Label>Camera stream URL</Label>
            <Input
              value={profile.camera_stream_url}
              onChange={(e) => setProfile({ ...profile, camera_stream_url: e.target.value })}
            />
          </div>
          <div className="space-y-1">
            <Label>Camera auth (stored encrypted)</Label>
            <Input
              type="password"
              value={profile.camera_auth}
              onChange={(e) => setProfile({ ...profile, camera_auth: e.target.value })}
              placeholder="user:password"
            />
          </div>
          <Button
            className="md:col-span-3"
            onClick={async () => {
              try {
                await api(`/api/v1/printers/${printer.id}`, {
                  method: "PATCH",
                  body: JSON.stringify({
                    build_x_mm: profile.build_x_mm ? Number(profile.build_x_mm) : null,
                    build_y_mm: profile.build_y_mm ? Number(profile.build_y_mm) : null,
                    build_z_mm: profile.build_z_mm ? Number(profile.build_z_mm) : null,
                    usable_x_mm: profile.usable_x_mm ? Number(profile.usable_x_mm) : null,
                    usable_y_mm: profile.usable_y_mm ? Number(profile.usable_y_mm) : null,
                    usable_z_mm: profile.usable_z_mm ? Number(profile.usable_z_mm) : null,
                    firmware: profile.firmware,
                    nozzle_diameter_mm: profile.nozzle_diameter_mm ? Number(profile.nozzle_diameter_mm) : null,
                    nozzle_material: profile.nozzle_material,
                    supported_materials: profile.supported_materials
                      .split(",")
                      .map((s) => s.trim())
                      .filter(Boolean),
                    max_nozzle_temp_c: profile.max_nozzle_temp_c ? Number(profile.max_nozzle_temp_c) : null,
                    max_bed_temp_c: profile.max_bed_temp_c ? Number(profile.max_bed_temp_c) : null,
                    build_plate_type: profile.build_plate_type,
                    slicer_profile: profile.slicer_profile,
                    unattended_mode: profile.unattended_mode,
                    avg_power_watts: Number(profile.avg_power_watts || 180),
                    machine_rate_per_hour: Number(profile.machine_rate_per_hour || 0),
                    camera_snapshot_url: profile.camera_snapshot_url || undefined,
                    camera_stream_url: profile.camera_stream_url || undefined,
                    camera_auth: profile.camera_auth || undefined,
                  }),
                });
                toast.success("Printer profile saved");
                load();
              } catch (err) {
                toast.error(err instanceof Error ? err.message : "Save failed");
              }
            }}
          >
            Save compatibility profile
          </Button>
          <div className="md:col-span-3 flex flex-col gap-2 rounded-lg border border-white/8 p-3 sm:flex-row sm:items-end">
            <div className="min-w-0 flex-1 space-y-1">
              <Label>Save as printer template</Label>
              <Input
                value={templateName}
                onChange={(e) => setTemplateName(e.target.value)}
                placeholder="K1 Max 300mm 0.4"
              />
            </div>
            <Button
              type="button"
              variant="outline"
              onClick={async () => {
                try {
                  await api("/api/v1/printers/templates", {
                    method: "POST",
                    body: JSON.stringify({
                      name: templateName.trim() || printer.name,
                      printer_id: printer.id,
                    }),
                  });
                  toast.success("Template saved. Use it when adding another printer with the same plate and nozzle.");
                } catch (err) {
                  toast.error(err instanceof Error ? err.message : "Could not save template");
                }
              }}
            >
              Save template
            </Button>
          </div>
        </CardContent>
      </Card>
      <Card className="lg:col-span-3">
        <CardHeader>
          <CardTitle>Downtime & redistribution</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {printer.current_downtime_reason && (
            <p className="text-amber-200">Currently down: {printer.current_downtime_reason.replaceAll("_", " ")}</p>
          )}
          <div className="flex flex-wrap gap-2">
            <select
              className="h-8 rounded-lg border border-input bg-transparent px-2"
              value={downtimeReason}
              onChange={(e) => setDowntimeReason(e.target.value)}
            >
              {[
                "planned_maintenance",
                "repair",
                "printer_fault",
                "network_issue",
                "filament_change",
                "waiting_for_bed_clear",
                "operator_disabled",
                "unknown",
              ].map((r) => (
                <option key={r} value={r}>
                  {r.replaceAll("_", " ")}
                </option>
              ))}
            </select>
            <Button
              variant="outline"
              onClick={async () => {
                await api(`/api/v1/printers/${printer.id}/downtime`, {
                  method: "POST",
                  body: JSON.stringify({ reason: downtimeReason }),
                });
                toast.success("Downtime recorded");
                load();
              }}
            >
              Start downtime
            </Button>
            <Button
              variant="outline"
              onClick={async () => {
                await api(`/api/v1/printers/${printer.id}/downtime/end`, { method: "POST" });
                toast.success("Printer back in service");
                load();
              }}
            >
              End downtime
            </Button>
            <Button
              onClick={async () => {
                try {
                  const res = await api<{ moved: unknown[]; skipped: unknown[] }>(
                    `/api/v1/printers/${printer.id}/redistribute`,
                    { method: "POST" },
                  );
                  toast.success(`Moved ${res.moved.length} queued jobs. ${res.skipped.length} skipped (including any active print).`);
                } catch (err) {
                  toast.error(err instanceof Error ? err.message : "Redistribute failed");
                }
              }}
            >
              Redistribute queued jobs
            </Button>
          </div>
          <p className="text-xs text-zinc-500">
            Redistribute never moves an actively printing job. Alternatives are chosen by compatibility and estimated finish.
          </p>
        </CardContent>
      </Card>
      <Dialog open={cameraOpen} onOpenChange={setCameraOpen}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>{printer.name} camera</DialogTitle>
          </DialogHeader>
          {printer.camera_configured ? (
            <PrinterCamera printerId={printer.id} className="h-[60vh] w-full" refreshMs={2000} />
          ) : (
            <p className="text-sm text-zinc-500">No camera configured.</p>
          )}
        </DialogContent>
      </Dialog>
      <Dialog open={!!pending} onOpenChange={(open) => !open && setPending(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              {pending === "delete" ? `Delete ${printer.name}?` : `Retire ${printer.name}?`}
            </DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            {pending === "delete"
              ? "This removes the printer from the farm. Print history stays. Add the machine again if it comes back."
              : "It will not be assigned new jobs. Restore it later if the machine returns."}
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setPending(null)} disabled={acting}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={acting}
              onClick={async () => {
                if (!pending) return;
                setActing(true);
                try {
                  if (pending === "retire") {
                    await api(`/api/v1/printers/${printer.id}/retire`, { method: "POST" });
                    toast.success("Printer retired.");
                    setPending(null);
                    load();
                  } else {
                    await api(`/api/v1/printers/${printer.id}`, { method: "DELETE" });
                    toast.success("Printer deleted.");
                    router.push("/printers");
                  }
                } catch (err) {
                  toast.error(err instanceof Error ? err.message : "Could not update printer");
                } finally {
                  setActing(false);
                }
              }}
            >
              {acting ? "Working…" : pending === "delete" ? "Delete printer" : "Retire printer"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
