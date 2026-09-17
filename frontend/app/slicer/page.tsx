"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ApiError, api } from "@/lib/api";
import type { Part, Printer, Stl } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PlatePreview, type PlateView } from "@/components/plate-preview";
import { formatDuration, formatGramsKnown, formatMoneyKnown } from "@/lib/format";
import { toast } from "sonner";
import { NozzleFields } from "@/components/nozzle-fields";
import { optionalMm } from "@/lib/printer-geometry";

type Profile = {
  id: string;
  name: string;
  version: number;
  material: string;
  nozzle_mm: number;
  density_g_cm3: number;
  layer_height_mm: number;
  first_layer_height_mm: number;
  perimeters: number;
  infill_percent: number;
  nozzle_temp_c: number;
  bed_temp_c: number;
  brim_width_mm: number;
  support_enabled: boolean;
  print_speed_mm_s: number;
  notes: string;
  is_archived: boolean;
};

type PackResponse = {
  plate: PlateView & { quantity: number; spacing_mm: number; max_quantity: number; warnings?: string[] };
  max_quantity: number;
  spacing_mm: number;
  spacing_hint: string;
  recommended_spacing_mm: number;
  geometric_errors: string[];
  pre_slice_estimate: {
    label: string;
    note: string;
    filament_grams: number;
    seconds: number;
    filament_cm3: number;
  };
  bed: { usable_x_mm: number; usable_y_mm: number; keepouts: { x: number; y: number; w: number; h: number }[] };
  compatibility: { issues: string[]; can_use: boolean; reason: string };
  candidates: { label: string; spacing_mm: number; max_per_plate: number; even_plate_count: number }[];
  approved_layouts: { id: string; name: string; quantity: number; spacing_mm: number; success_count: number; fail_count: number }[];
};

type SliceJob = {
  id: string;
  status: string;
  quantity: number;
  spacing_mm: number;
  error_message: string;
  sliced_time_seconds: number | null;
  filament_grams: number | null;
  filament_length_mm: number | null;
  material_cost: number | null;
  gcode_filename?: string | null;
  printer_name?: string | null;
  part_sku?: string | null;
  utilisation?: number | null;
  plate_index: number;
  plate_count: number;
  plate_json: PlateView;
  cost?: {
    filament_cost: number | null;
    electricity_cost: number;
    machine_cost: number;
    labour_cost: number;
    total_cost: number | null;
    cost_per_part: number | null;
  };
  filament_check?: {
    ok: boolean;
    required_g: number;
    available_g: number;
    reasons: string[];
    message?: string;
  };
};

const MODES = [
  { id: "balanced", label: "Balanced" },
  { id: "maximum_parts", label: "Maximum Parts" },
  { id: "fastest_print", label: "Fastest Print" },
  { id: "maximum_reliability", label: "Maximum Reliability" },
  { id: "minimum_bed_clears", label: "Minimum Bed Clears" },
];

export default function SlicerRoute() {
  return (
    <Suspense fallback={<div className="text-zinc-500">Loading production slicer…</div>}>
      <SlicerPage />
    </Suspense>
  );
}

function SlicerPage() {
  const params = useSearchParams();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [stls, setStls] = useState<Stl[]>([]);
  const [parts, setParts] = useState<Part[]>([]);
  const [printers, setPrinters] = useState<Printer[]>([]);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [advanced, setAdvanced] = useState(false);
  const [stlId, setStlId] = useState(params.get("stl_id") || "");
  const [partId, setPartId] = useState(params.get("part_id") || "");
  const [printerId, setPrinterId] = useState("");
  const [profileId, setProfileId] = useState("");
  const [qty, setQty] = useState(1);
  const [spacing, setSpacing] = useState(6);
  const [fillPlate, setFillPlate] = useState(true);
  const [fillUntil, setFillUntil] = useState(false);
  const [needed, setNeeded] = useState(Number(params.get("needed") || 0));
  const [mode, setMode] = useState("balanced");
  const [pack, setPack] = useState<PackResponse | null>(null);
  const [packing, setPacking] = useState(false);
  const [jobs, setJobs] = useState<SliceJob[]>([]);
  const [slicing, setSlicing] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const [uploading, setUploading] = useState(false);
  const [recommendation, setRecommendation] = useState<string | null>(null);
  const [compat, setCompat] = useState<{ title: string; reason: string; alternatives: { printer_name: string; printer_id: string }[] } | null>(
    null,
  );
  const [override, setOverride] = useState(false);
  const [runId] = useState(params.get("run_id") || "");
  const [bedX, setBedX] = useState("");
  const [bedY, setBedY] = useState("");
  const [bedZ, setBedZ] = useState("");
  const [nozzleMm, setNozzleMm] = useState("");
  const [nozzleMaterial, setNozzleMaterial] = useState("");
  const [savingPrinter, setSavingPrinter] = useState(false);

  const stl = stls.find((s) => s.id === stlId) || null;
  const profile = profiles.find((p) => p.id === profileId) || null;
  const printer = printers.find((p) => p.id === printerId) || null;
  const maxQty = pack?.max_quantity ?? 0;

  const load = useCallback(async () => {
    setError(null);
    try {
      const [models, partRows, printerRows, profileRows] = await Promise.all([
        api<Stl[]>("/api/v1/stl"),
        api<Part[]>("/api/v1/parts"),
        api<Printer[]>("/api/v1/printers"),
        api<Profile[]>("/api/v1/slicer/profiles"),
      ]);
      setStls(models);
      setParts(partRows);
      setPrinters(printerRows);
      setProfiles(profileRows);
      const partFromQuery = params.get("part_id");
      if (partFromQuery && !stlId) {
        const match = models.find((m) => m.part_id === partFromQuery);
        if (match) setStlId(match.id);
        setPartId(partFromQuery);
      }
      if (!profileId && profileRows[0]) setProfileId(profileRows[0].id);
      if (runId) {
        try {
          const suggest = await api<{ items: { part_id: string; shortage_qty: number; stl_id: string | null }[] }>(
            `/api/v1/slicer/production-suggest?run_id=${runId}`,
          );
          const first = suggest.items.find((i) => i.shortage_qty > 0) || suggest.items[0];
          if (first) {
            if (first.stl_id) setStlId(first.stl_id);
            setPartId(first.part_id);
            setNeeded(first.shortage_qty);
            setFillUntil(first.shortage_qty > 0);
          }
        } catch {
          /* production suggest is optional */
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the slicer.");
    } finally {
      setLoading(false);
    }
  }, [params, profileId, runId, stlId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!printer) {
      setBedX("");
      setBedY("");
      setBedZ("");
      setNozzleMm("");
      setNozzleMaterial("");
      return;
    }
    setBedX(String(printer.usable_x_mm || printer.build_x_mm || ""));
    setBedY(String(printer.usable_y_mm || printer.build_y_mm || ""));
    setBedZ(String(printer.usable_z_mm || printer.build_z_mm || ""));
    setNozzleMm(printer.nozzle_diameter_mm != null ? String(printer.nozzle_diameter_mm) : "0.4");
    setNozzleMaterial(printer.nozzle_material || "");
  }, [printerId, printer]);

  async function refreshPack(next?: Partial<{ qty: number; spacing: number; fill: boolean; printer: string; stl: string; profile: string }>) {
    const sid = next?.stl ?? stlId;
    const pid = next?.printer ?? printerId;
    const prof = next?.profile ?? profileId;
    if (!sid || !pid) {
      setPack(null);
      return;
    }
    setPacking(true);
    try {
      const body = {
        stl_id: sid,
        printer_id: pid,
        profile_id: prof || null,
        quantity: next?.fill ?? fillPlate ? null : next?.qty ?? qty,
        spacing_mm: next?.spacing ?? spacing,
        fill_plate: next?.fill ?? fillPlate,
        optimisation_mode: mode,
      };
      const res = await api<PackResponse>("/api/v1/slicer/pack", { method: "POST", body: JSON.stringify(body) });
      setPack(res);
      setSpacing(res.spacing_mm);
      if (next?.fill ?? fillPlate) setQty(res.plate.quantity);
      else setQty(Math.min(next?.qty ?? qty, res.max_quantity || 1));
      if (res.compatibility.issues.length) {
        try {
          const c = await api<{ title: string; reason: string; alternatives: { printer_name: string; printer_id: string }[] }>(
            "/api/v1/slicer/compatibility",
            { method: "POST", body: JSON.stringify(body) },
          );
          setCompat(c);
        } catch {
          setCompat({ title: "Cannot Use This Printer", reason: res.compatibility.reason, alternatives: [] });
        }
      } else {
        setCompat(null);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not pack this plate");
    } finally {
      setPacking(false);
    }
  }

  useEffect(() => {
    if (stlId && printerId) refreshPack();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stlId, printerId, profileId, mode]);

  async function autoSelect() {
    if (!stlId) {
      toast.error("Choose an STL first.");
      return;
    }
    try {
      const res = await api<{ printer: { printer_id: string; printer_name: string } | null; reason: string }>(
        "/api/v1/slicer/auto-select-printer",
        {
          method: "POST",
          body: JSON.stringify({
            stl_id: stlId,
            printer_id: printerId || null,
            profile_id: profileId || null,
            spacing_mm: spacing,
          }),
        },
      );
      if (res.printer) {
        setPrinterId(res.printer.printer_id);
        setRecommendation(`Recommended: ${res.printer.printer_name}. ${res.reason}`);
        toast.success(`Using ${res.printer.printer_name}`);
      } else {
        setRecommendation(res.reason);
        toast.error(res.reason);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not auto-select a printer");
    }
  }

  async function uploadStls(files: FileList | null) {
    if (!files?.length) return;
    setUploading(true);
    try {
      for (const file of Array.from(files)) {
        const body = new FormData();
        body.append("file", file);
        if (partId) body.append("part_id", partId);
        const row = await api<Stl>("/api/v1/stl/upload", { method: "POST", body });
        setStlId(row.id);
        if (row.bed_warnings?.length) {
          toast.message("STL stored with bed-size warnings", { description: row.bed_warnings[0] });
        } else {
          toast.success(`${row.filename} stored (v${row.version})`);
        }
      }
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "STL upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function sliceNow() {
    if (!stlId || !printerId || !profileId) {
      toast.error("Choose a part / STL, printer, and profile first.");
      return;
    }
    setSlicing(true);
    try {
      const created = await api<{ jobs: SliceJob[]; count: number }>("/api/v1/slicer/jobs", {
        method: "POST",
        body: JSON.stringify({
          stl_id: stlId,
          printer_id: printerId,
          profile_id: profileId,
          quantity: qty,
          spacing_mm: spacing,
          fill_plate: fillPlate,
          fill_until_complete: fillUntil,
          needed_qty: fillUntil ? needed || qty : qty,
          optimisation_mode: mode,
          production_run_id: runId || null,
          admin_override: override,
          placements: pack?.plate.placed,
        }),
      });
      toast.success(
        created.count > 1
          ? `Queued ${created.jobs.length} plates for PrusaSlicer.`
          : "Slice job queued. The web UI stays responsive while the worker runs PrusaSlicer.",
      );
      pollJobs(created.jobs.map((j) => j.id));
    } catch (err) {
      const detail = err instanceof ApiError ? err.detail : err instanceof Error ? err.message : "Slice failed";
      toast.error(typeof detail === "string" ? detail : "Slice failed");
      setSlicing(false);
    }
  }

  function pollJobs(ids: string[]) {
    let cancelled = false;
    async function tick() {
      const rows: SliceJob[] = [];
      for (const id of ids) {
        try {
          rows.push(await api<SliceJob>(`/api/v1/slicer/jobs/${id}`));
        } catch {
          /* keep polling */
        }
      }
      if (!cancelled && rows.length) setJobs(rows);
      const busy = rows.some((j) => j.status === "waiting" || j.status === "slicing");
      if (!cancelled && busy) setTimeout(tick, 1500);
      else setSlicing(false);
    }
    tick();
  }

  async function approve(job: SliceJob, filamentOverride = false) {
    try {
      const res = await api<{ ok: boolean; filename: string }>(`/api/v1/slicer/jobs/${job.id}/approve-queue`, {
        method: "POST",
        body: JSON.stringify({ override_filament: filamentOverride }),
      });
      toast.success(`${res.filename} is on the print queue.`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        toast.error("Insufficient Filament. Change spool, choose another printer, or override.");
        return;
      }
      toast.error(err instanceof Error ? err.message : "Could not queue");
    }
  }

  const plateView: PlateView | null = pack
    ? { ...pack.plate, keepouts: pack.bed.keepouts }
    : jobs[0]?.plate_json || null;

  if (loading) {
    return <div className="text-zinc-500">Loading production slicer…</div>;
  }
  if (error) {
    return (
      <div className="space-y-3">
        <p className="text-red-300">{error}</p>
        <Button onClick={() => load()}>Retry</Button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Production slicer</h1>
          <p className="mt-1 text-sm text-zinc-400">
            Choose a part, pick a printer, fill the plate, then slice with PrusaSlicer. The queue still runs G-code —
            FarmOS packs the plate and the slicer-worker writes the file.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant={advanced ? "outline" : "default"} onClick={() => setAdvanced(false)}>
            Simple
          </Button>
          <Button variant={advanced ? "default" : "outline"} onClick={() => setAdvanced(true)}>
            Advanced
          </Button>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,22rem)_1fr]">
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>1. Model library</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div
                className="rounded-lg border border-dashed border-white/20 p-4 text-sm text-zinc-400"
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  uploadStls(e.dataTransfer.files);
                }}
              >
                Drag STL files here or
                <label className="ml-1 cursor-pointer underline">
                  browse
                  <input
                    type="file"
                    accept=".stl"
                    multiple
                    className="hidden"
                    onChange={(e) => uploadStls(e.target.files)}
                  />
                </label>
                {uploading ? " — uploading…" : ""}
              </div>
              <div>
                <Label>Part</Label>
                <select
                  className="h-10 w-full rounded-lg border border-input bg-transparent px-2 text-sm"
                  value={partId}
                  onChange={(e) => {
                    setPartId(e.target.value);
                    const match = stls.find((s) => s.part_id === e.target.value);
                    if (match) setStlId(match.id);
                  }}
                >
                  <option value="">Unassigned</option>
                  {parts.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.sku} — {p.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <Label>STL version</Label>
                {stls.length === 0 ? (
                  <p className="text-sm text-zinc-500">No models yet. Drop an STL to start.</p>
                ) : (
                  <select
                    className="h-10 w-full rounded-lg border border-input bg-transparent px-2 text-sm"
                    value={stlId}
                    onChange={(e) => setStlId(e.target.value)}
                  >
                    <option value="">Select an STL</option>
                    {stls.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.filename} {s.part_sku ? `(${s.part_sku})` : ""} v{s.version}
                        {s.production_approved ? " · approved" : ""}
                      </option>
                    ))}
                  </select>
                )}
              </div>
              {stl && (
                <p className="text-xs text-zinc-500">
                  {stl.bbox_x_mm?.toFixed(1)}×{stl.bbox_y_mm?.toFixed(1)}×{stl.bbox_z_mm?.toFixed(1)} mm
                  {stl.triangle_count ? ` · ${stl.triangle_count} triangles` : ""}
                  {stl.bed_warnings?.length ? ` · ${stl.bed_warnings[0]}` : ""}
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>2. Printer & profile</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div>
                <Label>Printer</Label>
                <select
                  className="h-10 w-full rounded-lg border border-input bg-transparent px-2 text-sm"
                  value={printerId}
                  onChange={(e) => setPrinterId(e.target.value)}
                >
                  <option value="">Select printer</option>
                  {printers.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} {p.nozzle_diameter_mm ? `· ${p.nozzle_diameter_mm} mm` : ""} {p.status}
                    </option>
                  ))}
                  </select>
                </div>
              {printer && (
                <div className="space-y-2 rounded-lg border border-white/8 p-3">
                  <div className="text-sm font-medium">Build plate & nozzle</div>
                  <p className="text-xs text-zinc-500">
                    Packing uses this printer’s usable plate. Saving writes it on the printer record.
                  </p>
                  <div className="grid grid-cols-3 gap-2">
                    <div className="space-y-1">
                      <Label>X mm</Label>
                      <Input inputMode="decimal" value={bedX} onChange={(e) => setBedX(e.target.value)} />
                    </div>
                    <div className="space-y-1">
                      <Label>Y mm</Label>
                      <Input inputMode="decimal" value={bedY} onChange={(e) => setBedY(e.target.value)} />
                    </div>
                    <div className="space-y-1">
                      <Label>Z mm</Label>
                      <Input inputMode="decimal" value={bedZ} onChange={(e) => setBedZ(e.target.value)} />
                    </div>
                  </div>
                  <NozzleFields
                    diameter={nozzleMm}
                    material={nozzleMaterial}
                    onDiameter={setNozzleMm}
                    onMaterial={setNozzleMaterial}
                  />
                  <Button
                    type="button"
                    variant="outline"
                    className="w-full"
                    disabled={savingPrinter}
                    onClick={async () => {
                      setSavingPrinter(true);
                      try {
                        await api(`/api/v1/printers/${printer.id}`, {
                          method: "PATCH",
                          body: JSON.stringify({
                            build_x_mm: optionalMm(bedX),
                            build_y_mm: optionalMm(bedY),
                            build_z_mm: optionalMm(bedZ),
                            usable_x_mm: optionalMm(bedX),
                            usable_y_mm: optionalMm(bedY),
                            usable_z_mm: optionalMm(bedZ),
                            nozzle_diameter_mm: optionalMm(nozzleMm),
                            nozzle_material: nozzleMaterial,
                          }),
                        });
                        toast.success("Printer plate and nozzle saved");
                        await load();
                        await refreshPack();
                      } catch (err) {
                        toast.error(err instanceof Error ? err.message : "Could not save printer");
                      } finally {
                        setSavingPrinter(false);
                      }
                    }}
                  >
                    {savingPrinter ? "Saving…" : "Save plate & nozzle to printer"}
                  </Button>
                </div>
              )}
              <Button type="button" variant="outline" className="w-full" onClick={autoSelect} disabled={!stlId}>
                Auto-select printer
              </Button>
              {recommendation && <p className="text-xs text-amber-200">{recommendation}</p>}
              <div>
                <Label>Slicer profile</Label>
                <select
                  className="h-10 w-full rounded-lg border border-input bg-transparent px-2 text-sm"
                  value={profileId}
                  onChange={(e) => setProfileId(e.target.value)}
                >
                  <option value="">Select profile</option>
                  {profiles.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} v{p.version} · {p.material} · {p.nozzle_mm} mm
                    </option>
                  ))}
                </select>
              </div>
              {compat && (
                <div className="rounded-lg border border-red-500/40 bg-red-950/40 p-3 text-sm">
                  <div className="font-medium text-red-200">{compat.title}</div>
                  <p className="mt-1 text-red-100/80">{compat.reason}</p>
                  {compat.alternatives.length > 0 && (
                    <div className="mt-2 space-y-1">
                      {compat.alternatives.map((a) => (
                        <button
                          key={a.printer_id}
                          type="button"
                          className="block text-amber-200 underline"
                          onClick={() => setPrinterId(a.printer_id)}
                        >
                          Use {a.printer_name}
                        </button>
                      ))}
                    </div>
                  )}
                  <label className="mt-2 flex items-center gap-2 text-xs text-zinc-400">
                    <input type="checkbox" checked={override} onChange={(e) => setOverride(e.target.checked)} />
                    Admin override (non-geometric warnings only)
                  </label>
                </div>
              )}
              {advanced && profile && (
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <label>
                    Layer mm
                    <Input
                      value={profile.layer_height_mm}
                      onBlur={async (e) => {
                        await api(`/api/v1/slicer/profiles/${profile.id}`, {
                          method: "PATCH",
                          body: JSON.stringify({ layer_height_mm: Number(e.target.value) }),
                        });
                        load();
                      }}
                      onChange={() => undefined}
                    />
                  </label>
                  <label>
                    Density g/cm³
                    <Input defaultValue={profile.density_g_cm3} readOnly />
                  </label>
                  <label>
                    Infill %
                    <Input defaultValue={profile.infill_percent} readOnly />
                  </label>
                  <label>
                    Brim mm
                    <Input defaultValue={profile.brim_width_mm} readOnly />
                  </label>
                  <p className="col-span-2 text-zinc-500">
                    Duplicate a profile from Advanced if you need a lasting change. Historical jobs keep the version they used.
                  </p>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={async () => {
                      const copy = await api<Profile>(`/api/v1/slicer/profiles/${profile.id}/duplicate`, { method: "POST" });
                      setProfileId(copy.id);
                      load();
                    }}
                  >
                    Duplicate profile
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>3. Fill Plate</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap gap-2">
                <Button type="button" onClick={() => { setFillPlate(true); refreshPack({ fill: true }); }} disabled={!stlId || !printerId}>
                  Fill Plate
                </Button>
                <select
                  className="h-10 rounded-lg border border-input bg-transparent px-2 text-sm"
                  value={mode}
                  onChange={(e) => setMode(e.target.value)}
                >
                  {MODES.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <Label>
                  Parts on plate {pack ? `(max ${maxQty} at ${spacing} mm)` : ""}
                </Label>
                <div className="flex items-center gap-3">
                  <input
                    type="range"
                    min={1}
                    max={Math.max(1, maxQty)}
                    value={qty}
                    className="flex-1"
                    onChange={(e) => {
                      const n = Number(e.target.value);
                      setFillPlate(false);
                      setQty(n);
                      refreshPack({ qty: n, fill: false });
                    }}
                  />
                  <Input
                    className="w-20"
                    type="number"
                    min={1}
                    max={Math.max(1, maxQty)}
                    value={qty}
                    onChange={(e) => {
                      const n = Math.max(1, Number(e.target.value) || 1);
                      setFillPlate(false);
                      setQty(n);
                      refreshPack({ qty: n, fill: false });
                    }}
                  />
                </div>
              </div>
              <div>
                <Label>
                  Part spacing {spacing} mm · {pack?.spacing_hint || "Recommended"}
                </Label>
                <input
                  type="range"
                  min={2}
                  max={30}
                  step={0.5}
                  value={spacing}
                  className="w-full"
                  onChange={(e) => {
                    const n = Number(e.target.value);
                    setSpacing(n);
                    refreshPack({ spacing: n });
                  }}
                />
                <p className="text-xs text-zinc-500">Tight / Recommended / Conservative. Changing spacing re-packs and updates the parts maximum.</p>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={fillUntil} onChange={(e) => setFillUntil(e.target.checked)} />
                Fill plates until quantity complete
              </label>
              {fillUntil && (
                <div>
                  <Label>Quantity needed</Label>
                  <Input type="number" min={1} value={needed || qty} onChange={(e) => setNeeded(Number(e.target.value) || 0)} />
                </div>
              )}
              {packing && <p className="text-sm text-zinc-500">Re-packing…</p>}
              {pack && (
                <p className="text-sm text-zinc-300">
                  {pack.plate.quantity} parts · {pack.spacing_mm} mm spacing · {((pack.plate.utilisation ?? 0) * 100).toFixed(0)}% bed used ·{" "}
                  <span className="text-amber-200">Pre-Slice Estimate</span> {formatDuration(pack.pre_slice_estimate.seconds)} ·{" "}
                  {formatGramsKnown(pack.pre_slice_estimate.filament_grams)}
                </p>
              )}
              {pack?.geometric_errors?.length ? (
                <p className="text-sm text-red-300">{pack.geometric_errors.join(" ")}</p>
              ) : null}
              {pack?.approved_layouts?.length ? (
                <p className="text-xs text-zinc-500">
                  Approved layout available: {pack.approved_layouts[0].name} (stats are informational — FarmOS will not auto-switch).
                </p>
              ) : null}
              {advanced && pack?.candidates?.length ? (
                <div className="rounded-lg border border-white/10 p-3 text-xs text-zinc-400 space-y-1">
                  <div className="font-medium text-zinc-300">Layout candidates</div>
                  {pack.candidates.map((c) => (
                    <div key={c.label}>
                      {c.label}: max {c.max_per_plate} copies at {c.spacing_mm} mm · {c.even_plate_count} plates if split evenly
                    </div>
                  ))}
                </div>
              ) : null}
              <PlatePreview
                plate={plateView}
                selected={selected}
                onSelect={setSelected}
                interactive={typeof window !== "undefined" && window.matchMedia("(pointer:fine)").matches}
                onMove={(index, x, y) => {
                  if (!pack) return;
                  const placed = pack.plate.placed.map((p) => (p.index === index ? { ...p, x, y } : p));
                  setPack({ ...pack, plate: { ...pack.plate, placed } });
                }}
              />
              {selected != null && pack && (
                <div className="hidden gap-2 md:flex">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => {
                      const placed = pack.plate.placed.map((p) =>
                        p.index === selected ? { ...p, rotation_z: (p.rotation_z + 90) % 360, w: p.h, h: p.w } : p,
                      );
                      setPack({ ...pack, plate: { ...pack.plate, placed } });
                    }}
                  >
                    Rotate
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => {
                      setPack({ ...pack, plate: { ...pack.plate, placed: pack.plate.placed.filter((p) => p.index !== selected) } });
                      setSelected(null);
                    }}
                  >
                    Delete
                  </Button>
                  <Button type="button" variant="outline" onClick={() => refreshPack()}>
                    Reset pack
                  </Button>
                </div>
              )}
              <Button className="w-full" onClick={sliceNow} disabled={slicing || !stlId || !printerId || !profileId}>
                {slicing ? "Slicing with PrusaSlicer…" : "Slice"}
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>4. Sliced result</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {jobs.length === 0 && (
                <p className="text-sm text-zinc-500">
                  After Slice, this card shows printer, part, quantity, spacing, <strong>Sliced Print Time</strong>, filament, cost, and
                  utilisation. Pre-slice numbers above are estimates only.
                </p>
              )}
              {jobs.map((job) => (
                <div key={job.id} className="rounded-lg border border-white/10 p-3 space-y-2">
                  <div className="flex flex-wrap justify-between gap-2 text-sm">
                    <span>
                      Plate {job.plate_index}/{job.plate_count} · {job.status}
                    </span>
                    <span>{job.gcode_filename || "Waiting for G-code…"}</span>
                  </div>
                  {job.status === "failed" && <p className="text-sm text-red-300">{job.error_message}</p>}
                  {job.status === "completed" && (
                    <>
                      <p className="text-sm">
                        {job.printer_name} · {job.part_sku} · ×{job.quantity} · {job.spacing_mm} mm
                      </p>
                      <p className="text-sm text-amber-100">
                        Sliced Print Time {formatDuration(job.sliced_time_seconds)} · filament{" "}
                        {job.filament_length_mm ? `${(job.filament_length_mm / 1000).toFixed(2)} m` : "—"} /{" "}
                        {formatGramsKnown(job.filament_grams)} · {formatMoneyKnown(job.cost?.filament_cost ?? job.material_cost)} material
                        {job.cost?.cost_per_part != null ? ` · ${formatMoneyKnown(job.cost.cost_per_part)} / part` : ""}
                      </p>
                      {job.filament_check && !job.filament_check.ok && (
                        <div className="rounded border border-amber-500/40 p-2 text-sm text-amber-100">
                          Insufficient Filament — {job.filament_check.reasons.join(" ")}
                          <div className="mt-2 flex flex-wrap gap-2">
                            <Link href="/filament" className="underline">
                              Change spool
                            </Link>
                            <button type="button" className="underline" onClick={autoSelect}>
                              Choose printer
                            </button>
                            <Button size="sm" onClick={() => approve(job, true)}>
                              Override
                            </Button>
                          </div>
                        </div>
                      )}
                      <div className="flex flex-wrap gap-2">
                        <Button onClick={() => approve(job)}>Approve & Queue</Button>
                        <Button variant="outline" onClick={() => toast.message("Edit the plate above, then Slice again.")}>
                          Edit Plate
                        </Button>
                        <Button
                          variant="outline"
                          onClick={async () => {
                            const next = await api<SliceJob>(`/api/v1/slicer/jobs/${job.id}/reslice`, { method: "POST" });
                            pollJobs([next.id]);
                          }}
                        >
                          Reslice
                        </Button>
                        <Button
                          variant="outline"
                          onClick={async () => {
                            const res = await api<{ filename: string }>(`/api/v1/slicer/jobs/${job.id}/save-gcode`, { method: "POST" });
                            toast.success(`${res.filename} is in the G-code library.`);
                          }}
                        >
                          Save G-code Only
                        </Button>
                      </div>
                    </>
                  )}
                </div>
              ))}
              <p className="text-xs text-zinc-500">
                Need to keep using uploaded plates? The{" "}
                <Link href="/library" className="underline">
                  G-code library
                </Link>{" "}
                still accepts files from Orca/PrusaSlicer on a workstation.
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
