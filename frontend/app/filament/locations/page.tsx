"use client";

import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { FilamentNav } from "@/components/filament-nav";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";

type Loc = { id: string; name: string; kind: string; notes: string; spool_count: number };

export default function LocationsPage() {
  const [rows, setRows] = useState<Loc[]>([]);
  const [name, setName] = useState("");
  const [kind, setKind] = useState("shelf");

  async function load() {
    setRows(await api<Loc[]>("/api/v1/filament/locations"));
  }
  useEffect(() => {
    load();
  }, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/api/v1/filament/locations", { method: "POST", body: JSON.stringify({ name, kind }) });
      setName("");
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not create location");
    }
  }

  return (
    <div className="space-y-4">
      <FilamentNav />
      <p className="text-sm text-muted-foreground">
        A physical spool always has a current location. Scanning, moving, or assigning a spool updates it.
      </p>
      <form onSubmit={create} className="flex flex-wrap gap-2">
        <Input className="max-w-xs" placeholder="Location name" value={name} onChange={(e) => setName(e.target.value)} required />
        <select className="h-8 rounded-lg border border-input bg-transparent px-2 text-sm" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="shelf">Shelf</option>
          <option value="sealed">Sealed stock</option>
          <option value="open">Open stock</option>
          <option value="dryer">Dryer</option>
          <option value="printer">Printer</option>
        </select>
        <Button type="submit">Add location</Button>
      </form>
      <div className="grid gap-2 md:grid-cols-2">
        {rows.map((l) => (
          <div key={l.id} className="flex items-center justify-between rounded-lg border border-white/8 px-3 py-2">
            <div>
              <div className="font-medium">{l.name}</div>
              <div className="text-xs text-zinc-500">{l.kind}</div>
            </div>
            <div className="font-mono text-sm">{l.spool_count} rolls</div>
          </div>
        ))}
      </div>
    </div>
  );
}
