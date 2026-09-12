"use client";

import { FormEvent, Fragment, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { FarmSettings, GCode, Part, Stl } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDuration, formatGrams } from "@/lib/format";
import { toast } from "sonner";
import Link from "next/link";
import { parseQuantityFromFilename } from "@/lib/gcode";

function mm(n: number | null | undefined) {
  if (n == null) return "—";
  return `${n.toFixed(n >= 10 ? 0 : 1)} mm`;
}

function packLabel(row: Stl) {
  if (row.bbox_x_mm == null || row.bbox_y_mm == null) {
    return "Could not measure";
  }
  if (row.copies_per_plate == null) return "—";
  if (row.copies_per_plate <= 0) {
    return "Does not fit this plate";
  }
  const grid =
    row.pack_cols && row.pack_rows ? `${row.pack_cols}×${row.pack_rows}` : null;
  return `${row.copies_per_plate}${grid ? ` (${grid})` : ""}${row.pack_rotated ? " · rotated 90°" : ""}`;
}

export default function LibraryPage() {
  const [files, setFiles] = useState<GCode[]>([]);
  const [stls, setStls] = useState<Stl[]>([]);
  const [parts, setParts] = useState<Part[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [qty, setQty] = useState(1);
  const [partId, setPartId] = useState("");
  const [material, setMaterial] = useState("PETG");
  const [stl, setStl] = useState<File | null>(null);
  const [pack, setPack] = useState({ x: 220, y: 220, gap: 8 });
  const [printers, setPrinters] = useState<{ id: string; name: string }[]>([]);
  const [edit, setEdit] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<GCode | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  async function load() {
    const [gcode, models, partRows, settings, printerRows] = await Promise.all([
      api<GCode[]>("/api/v1/gcode?include_archived=true"),
      api<Stl[]>("/api/v1/stl"),
      api<Part[]>("/api/v1/parts"),
      api<FarmSettings>("/api/v1/settings"),
      api<{ id: string; name: string }[]>("/api/v1/printers"),
    ]);
    setFiles(gcode);
    setStls(models);
    setParts(partRows);
    setPack({ x: settings.pack_bed_x_mm, y: settings.pack_bed_y_mm, gap: settings.pack_gap_mm });
    setPrinters(printerRows);
  }
  useEffect(() => {
    load().catch((err) => toast.error(err instanceof Error ? err.message : "Failed to load library"));
  }, []);

  async function uploadGcode(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    if (partId) body.append("part_id", partId);
    body.append("material", material);
    body.append("quantity_per_file", String(Math.max(1, qty)));
    try {
      const row = await api<GCode>("/api/v1/gcode/upload", { method: "POST", body });
      const n = row.quantity_per_file;
      toast.success(
        n > 1
          ? `${row.filename} stored — quantity ${n} (${n} of this part on each plate).`
          : `${row.filename} stored — quantity 1 (one part per plate).`,
      );
      setFile(null);
      setQty(1);
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Upload failed");
    }
  }

  async function uploadStl(e: FormEvent) {
    e.preventDefault();
    if (!stl) return;
    const body = new FormData();
    body.append("file", stl);
    if (partId) body.append("part_id", partId);
    try {
      const row = await api<Stl>("/api/v1/stl/upload", { method: "POST", body });
      if (row.copies_per_plate && row.copies_per_plate > 0) {
        toast.success(
          `About ${row.copies_per_plate} copies fit on a ${row.pack_bed_x_mm}×${row.pack_bed_y_mm} mm plate. Slice that layout in Orca/PrusaSlicer, then upload the G-code.`,
        );
      } else {
        toast.success("STL stored. Print FarmOS cannot generate G-code — slice it yourself and upload the result.");
      }
      setStl(null);
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Upload failed");
    }
  }

  async function archive(id: string, archived: boolean) {
    try {
      await api(`/api/v1/gcode/${id}`, { method: "PATCH", body: JSON.stringify({ is_archived: archived }) });
      toast.success(archived ? "Archived. Historical jobs keep this file; it will not be queued." : "Restored to the library.");
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not update G-code");
    }
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await api(`/api/v1/gcode/${pendingDelete.id}`, { method: "DELETE" });
      toast.success(`Deleted ${pendingDelete.filename}`);
      setPendingDelete(null);
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not delete G-code");
    } finally {
      setDeleting(false);
    }
  }

  async function saveGcode(g: GCode, patch: Partial<GCode>) {
    await api(`/api/v1/gcode/${g.id}`, { method: "PATCH", body: JSON.stringify(patch) });
    toast.success("G-code version updated. Historical jobs keep the file they originally used.");
    load();
  }

  return (
    <div className="space-y-8">
      <div className="grid gap-4 md:grid-cols-2">
        <form onSubmit={uploadGcode} className="space-y-3 rounded-xl border border-white/8 p-4">
          <h2 className="font-medium">Upload G-code</h2>
          <p className="text-xs text-zinc-500">
            Production uses G-code. Pack as many copies as you want in your slicer, then upload that file. If the name
            has <span className="font-mono">x4</span>, <span className="font-mono">x8</span>, or any{" "}
            <span className="font-mono">x</span>
            +number, quantity is set to that many of this part on the plate.
          </p>
          <Input
            type="file"
            accept=".gcode,.gco,.g"
            onChange={(e) => {
              const next = e.target.files?.[0] || null;
              setFile(next);
              if (next) setQty(parseQuantityFromFilename(next.name));
            }}
          />
          {file && (
            <p className="text-sm text-amber-200">
              {file.name}
              {qty > 1 ? ` — this plate makes ${qty} of this part` : " — one part per plate (no x-number in the name)"}
            </p>
          )}
          <div className="grid grid-cols-2 gap-2">
            <div>
              <Label>Part</Label>
              <select
                className="h-8 w-full rounded-lg border border-input bg-transparent px-2 text-sm"
                value={partId}
                onChange={(e) => setPartId(e.target.value)}
              >
                <option value="">Unassigned</option>
                {parts.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.sku}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <Label>Quantity (parts on this plate)</Label>
              <Input
                className="h-12 text-lg md:h-8 md:text-sm"
                type="number"
                min={1}
                max={999}
                value={qty}
                onChange={(e) => setQty(Math.max(1, Number(e.target.value) || 1))}
              />
            </div>
          </div>
          <div>
            <Label>Material</Label>
            <Input value={material} onChange={(e) => setMaterial(e.target.value)} />
          </div>
          <Button type="submit" disabled={!file}>
            Add to library
          </Button>
        </form>
        <form onSubmit={uploadStl} className="space-y-3 rounded-xl border border-white/8 p-4">
          <h2 className="font-medium">Upload STL</h2>
          <p className="text-xs text-zinc-500">
            Print FarmOS is not a slicer — it cannot write G-code or nest parts on a plate. After upload it measures
            the model and estimates how many copies fit in a regular grid on the plate size in{" "}
            <Link href="/settings" className="underline underline-offset-2">
              Settings
            </Link>{" "}
            (currently {pack.x}×{pack.y} mm, {pack.gap} mm gap).
          </p>
          <Input type="file" accept=".stl" onChange={(e) => setStl(e.target.files?.[0] || null)} />
          <Button type="submit" variant="outline" disabled={!stl}>
            Measure STL
          </Button>
        </form>
      </div>

      <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-medium text-zinc-300">G-code (queue)</h2>
          <p className="text-xs text-zinc-500">
            Time and filament come from slicer comments at the start and end of the file (Cura, Prusa, Orca, Bambu).
            Re-read after an upload if an older file still shows the 1 h / 20 g fallback.
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          disabled={refreshing}
          onClick={async () => {
            setRefreshing(true);
            try {
              const res = await api<{
                updated: number;
                scanned: number;
                missing_file: number;
                queued_jobs_updated: number;
              }>("/api/v1/gcode/refresh-estimates", { method: "POST" });
              toast.success(
                res.updated
                  ? `Updated ${res.updated} of ${res.scanned} files${res.queued_jobs_updated ? `, ${res.queued_jobs_updated} queued jobs` : ""}.`
                  : `Scanned ${res.scanned} files. No slicer estimates changed.`,
              );
              if (res.missing_file) {
                toast.message(`${res.missing_file} file(s) are missing on disk.`);
              }
              load();
            } catch (err) {
              toast.error(err instanceof Error ? err.message : "Could not re-read G-code");
            } finally {
              setRefreshing(false);
            }
          }}
        >
          {refreshing ? "Reading files…" : "Re-read estimates"}
        </Button>
      </div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>File</TableHead>
              <TableHead>Part</TableHead>
              <TableHead>Qty/file</TableHead>
              <TableHead>Material</TableHead>
              <TableHead>Time</TableHead>
              <TableHead>Filament</TableHead>
              <TableHead>Ver</TableHead>
              <TableHead>Approved</TableHead>
              <TableHead></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {files.length === 0 && (
              <TableRow>
                <TableCell colSpan={9} className="text-zinc-500">
                  No G-code yet. Slice a plate in OrcaSlicer or PrusaSlicer and upload it here to queue production.
                </TableCell>
              </TableRow>
            )}
            {files.map((g) => (
              <Fragment key={g.id}>
              <TableRow className={g.is_archived ? "opacity-50" : ""}>
                <TableCell className="font-mono text-xs">{g.filename}</TableCell>
                <TableCell>{g.part_sku || "—"}</TableCell>
                <TableCell>
                  <Input
                    className="h-9 w-20 font-mono"
                    type="number"
                    min={1}
                    max={999}
                    defaultValue={g.quantity_per_file}
                    key={`${g.id}-${g.quantity_per_file}`}
                    onBlur={(e) => {
                      const n = Math.max(1, Number(e.target.value) || 1);
                      if (n !== g.quantity_per_file) saveGcode(g, { quantity_per_file: n });
                    }}
                  />
                </TableCell>
                <TableCell>{g.material}</TableCell>
                <TableCell>{formatDuration(g.estimated_time_seconds)}</TableCell>
                <TableCell>{formatGrams(g.estimated_filament_grams)}</TableCell>
                <TableCell>v{g.version}</TableCell>
                <TableCell>{g.production_approved ? "Production" : g.is_archived ? "retired" : "draft"}</TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1">
                    <Button size="xs" variant="outline" onClick={() => archive(g.id, !g.is_archived)}>
                      {g.is_archived ? "Unarchive" : "Archive"}
                    </Button>
                    <Button size="xs" variant="destructive" onClick={() => setPendingDelete(g)}>
                      Delete
                    </Button>
                    <Button size="xs" variant="outline" onClick={() => setEdit(edit === g.id ? null : g.id)}>
                      Compatibility
                    </Button>
                    {!g.production_approved && (
                      <Button size="xs" onClick={() => saveGcode(g, { production_approved: true })}>
                        Mark production approved
                      </Button>
                    )}
                  </div>
                </TableCell>
              </TableRow>
              {edit === g.id && (
                <TableRow>
                  <TableCell colSpan={9} className="bg-white/3">
                    <div className="grid gap-2 md:grid-cols-4">
                      <Input
                        defaultValue={g.slicer || ""}
                        placeholder="Slicer"
                        onBlur={(e) => saveGcode(g, { slicer: e.target.value })}
                      />
                      <Input
                        defaultValue={g.slicer_profile || ""}
                        placeholder="Slicer profile"
                        onBlur={(e) => saveGcode(g, { slicer_profile: e.target.value })}
                      />
                      <Input
                        defaultValue={g.required_nozzle_mm ?? g.nozzle_mm ?? ""}
                        placeholder="Required nozzle mm"
                        onBlur={(e) => saveGcode(g, { required_nozzle_mm: e.target.value ? Number(e.target.value) : null })}
                      />
                      <Input
                        defaultValue={g.layer_height_mm ?? ""}
                        placeholder="Layer height mm"
                        onBlur={(e) => saveGcode(g, { layer_height_mm: e.target.value ? Number(e.target.value) : null })}
                      />
                      <Input
                        defaultValue={g.min_bed_x_mm ?? ""}
                        placeholder="Min bed X mm"
                        onBlur={(e) => saveGcode(g, { min_bed_x_mm: e.target.value ? Number(e.target.value) : null })}
                      />
                      <Input
                        defaultValue={g.min_bed_y_mm ?? ""}
                        placeholder="Min bed Y mm"
                        onBlur={(e) => saveGcode(g, { min_bed_y_mm: e.target.value ? Number(e.target.value) : null })}
                      />
                      <Input
                        defaultValue={g.notes || ""}
                        placeholder="Notes"
                        onBlur={(e) => saveGcode(g, { notes: e.target.value })}
                      />
                      <label className="flex items-center gap-2 text-xs">
                        <input
                          type="checkbox"
                          checked={g.unattended_approved !== false}
                          onChange={(e) => saveGcode(g, { unattended_approved: e.target.checked })}
                        />
                        Unattended approved
                      </label>
                      <div className="md:col-span-4 text-xs text-zinc-500">
                        Compatible printers (empty = any, then profile checks still apply):
                        <div className="mt-1 flex flex-wrap gap-2">
                          {printers.map((p) => {
                            const on = g.compatible_printer_ids.includes(p.id);
                            return (
                              <label key={p.id} className="flex items-center gap-1">
                                <input
                                  type="checkbox"
                                  checked={on}
                                  onChange={() => {
                                    const next = on
                                      ? g.compatible_printer_ids.filter((id) => id !== p.id)
                                      : [...g.compatible_printer_ids, p.id];
                                    saveGcode(g, { compatible_printer_ids: next });
                                  }}
                                />
                                {p.name}
                              </label>
                            );
                          })}
                        </div>
                      </div>
                    </div>
                  </TableCell>
                </TableRow>
              )}
              </Fragment>
            ))}
          </TableBody>
        </Table>
      </div>

      <div className="space-y-3">
        <h2 className="text-sm font-medium text-zinc-300">STLs (estimate only)</h2>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>File</TableHead>
              <TableHead>Part</TableHead>
              <TableHead>Size (X×Y×Z)</TableHead>
              <TableHead>Copies on plate</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {stls.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="text-zinc-500">
                  No STLs stored. Upload a model to see a grid estimate — then still slice and upload G-code to print.
                </TableCell>
              </TableRow>
            )}
            {stls.map((row) => (
              <TableRow key={row.id}>
                <TableCell className="font-mono text-xs">{row.filename}</TableCell>
                <TableCell>{row.part_sku || "—"}</TableCell>
                <TableCell className="font-mono text-xs">
                  {mm(row.bbox_x_mm)} × {mm(row.bbox_y_mm)} × {mm(row.bbox_z_mm)}
                </TableCell>
                <TableCell>{packLabel(row)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <Dialog open={!!pendingDelete} onOpenChange={(next) => !next && setPendingDelete(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Delete {pendingDelete?.filename}?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            This removes the G-code from the library. Archive keeps it for job history. If any print job or production
            run already used this file, FarmOS will refuse the delete — archive it instead.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setPendingDelete(null)} disabled={deleting}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={confirmDelete} disabled={deleting}>
              {deleting ? "Deleting…" : "Delete G-code"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
