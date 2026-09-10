"use client";

import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { GCode, Part } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDuration, formatGrams } from "@/lib/format";
import { toast } from "sonner";

export default function LibraryPage() {
  const [files, setFiles] = useState<GCode[]>([]);
  const [parts, setParts] = useState<Part[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [partId, setPartId] = useState("");
  const [material, setMaterial] = useState("PETG");
  const [stl, setStl] = useState<File | null>(null);

  async function load() {
    setFiles(await api<GCode[]>("/api/v1/gcode?include_archived=true"));
    setParts(await api<Part[]>("/api/v1/parts"));
  }
  useEffect(() => {
    load();
  }, []);

  async function uploadGcode(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    if (partId) body.append("part_id", partId);
    body.append("material", material);
    try {
      await api("/api/v1/gcode/upload", { method: "POST", body });
      toast.success("G-code stored in the library. Filenames like RK-FR5-Handle-x4.gcode set quantity to 4.");
      setFile(null);
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
      await api("/api/v1/stl/upload", { method: "POST", body });
      toast.success("STL stored. Automated slicing can be added later without changing this library.");
      setStl(null);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Upload failed");
    }
  }

  async function archive(id: string, archived: boolean) {
    await api(`/api/v1/gcode/${id}`, { method: "PATCH", body: JSON.stringify({ is_archived: archived }) });
    load();
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2">
        <form onSubmit={uploadGcode} className="space-y-3 rounded-xl border border-white/8 p-4">
          <h2 className="font-medium">Upload G-code</h2>
          <Input type="file" accept=".gcode,.gco,.g" onChange={(e) => setFile(e.target.files?.[0] || null)} />
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
              <Label>Material</Label>
              <Input value={material} onChange={(e) => setMaterial(e.target.value)} />
            </div>
          </div>
          <Button type="submit" disabled={!file}>
            Add to library
          </Button>
        </form>
        <form onSubmit={uploadStl} className="space-y-3 rounded-xl border border-white/8 p-4">
          <h2 className="font-medium">Upload STL (secondary)</h2>
          <p className="text-xs text-zinc-500">
            Stored against a part for future slicing. Packing multiple STLs onto a plate is not required for FarmOS
            production — use G-code for the queue.
          </p>
          <Input type="file" accept=".stl" onChange={(e) => setStl(e.target.files?.[0] || null)} />
          <Button type="submit" variant="outline" disabled={!stl}>
            Store STL
          </Button>
        </form>
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
            <TableHead></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {files.map((g) => (
            <TableRow key={g.id} className={g.is_archived ? "opacity-50" : ""}>
              <TableCell className="font-mono text-xs">{g.filename}</TableCell>
              <TableCell>{g.part_sku || "—"}</TableCell>
              <TableCell>×{g.quantity_per_file}</TableCell>
              <TableCell>{g.material}</TableCell>
              <TableCell>{formatDuration(g.estimated_time_seconds)}</TableCell>
              <TableCell>{formatGrams(g.estimated_filament_grams)}</TableCell>
              <TableCell>v{g.version}</TableCell>
              <TableCell>
                <Button size="xs" variant="outline" onClick={() => archive(g.id, !g.is_archived)}>
                  {g.is_archived ? "Unarchive" : "Archive"}
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
