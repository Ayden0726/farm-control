"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { LABEL_PRESETS, LabelLayout } from "@/lib/labels";

function PrintInner() {
  const params = useSearchParams();
  const kind = params.get("kind") || "spool";
  const allIds = useMemo(() => (params.get("ids") || "").split(",").filter(Boolean), [params]);
  const [layout, setLayout] = useState<LabelLayout>((params.get("layout") as LabelLayout) || "sheet");
  const [width, setWidth] = useState(params.get("w") || String(LABEL_PRESETS.sheet.w));
  const [height, setHeight] = useState(params.get("h") || String(LABEL_PRESETS.sheet.h));
  const [columns, setColumns] = useState(params.get("cols") || String(LABEL_PRESETS.sheet.cols));
  const [picked, setPicked] = useState<Record<string, boolean>>(() => Object.fromEntries(allIds.map((id) => [id, true])));
  const auto = params.get("auto") === "1";

  async function generate(ids: string[]) {
    if (!ids.length) {
      toast.error("Select at least one label.");
      return;
    }
    try {
      const res = await api<{ html: string }>("/api/v1/labels/sheet", {
        method: "POST",
        body: JSON.stringify({
          kind,
          items: ids.map((id) => ({ id, copies: 1 })),
          width_mm: Number(width),
          height_mm: Number(height),
          columns: Number(columns),
          layout,
        }),
      });
      document.open();
      document.write(res.html);
      document.close();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Print failed");
    }
  }

  useEffect(() => {
    if (auto && allIds.length) generate(allIds);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auto, allIds.join(",")]);

  if (auto) return <div className="p-6 text-zinc-400">Preparing labels…</div>;

  const selected = allIds.filter((id) => picked[id]);

  return (
    <div className="mx-auto max-w-lg space-y-4 p-4">
      <h1 className="text-xl font-semibold">Print labels</h1>
      <p className="text-sm text-zinc-400">
        Reprinting uses the same spool number and QR. Nothing new is created.
      </p>
      <div className="flex flex-wrap gap-2">
        {(Object.keys(LABEL_PRESETS) as LabelLayout[]).map((key) => (
          <Button
            key={key}
            variant={layout === key ? "default" : "outline"}
            onClick={() => {
              setLayout(key);
              setWidth(String(LABEL_PRESETS[key].w));
              setHeight(String(LABEL_PRESETS[key].h));
              setColumns(String(LABEL_PRESETS[key].cols));
            }}
          >
            {LABEL_PRESETS[key].label}
          </Button>
        ))}
      </div>
      <div className="grid grid-cols-3 gap-3">
        <div className="space-y-1">
          <Label>Width mm</Label>
          <Input value={width} onChange={(e) => setWidth(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label>Height mm</Label>
          <Input value={height} onChange={(e) => setHeight(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label>Columns</Label>
          <Input value={columns} onChange={(e) => setColumns(e.target.value)} />
        </div>
      </div>
      {allIds.length > 1 && (
        <div className="space-y-2">
          {allIds.map((id) => (
            <label key={id} className="flex items-center gap-2 font-mono text-sm">
              <input type="checkbox" checked={!!picked[id]} onChange={(e) => setPicked({ ...picked, [id]: e.target.checked })} />
              {id.slice(0, 8)}…
            </label>
          ))}
        </div>
      )}
      <div className="flex flex-col gap-2 sm:flex-row">
        <Button className="h-12 flex-1" onClick={() => generate(allIds)}>
          Print All Labels
        </Button>
        <Button className="h-12 flex-1" variant="outline" onClick={() => generate(selected)}>
          Print Selected
        </Button>
      </div>
    </div>
  );
}

export default function PrintPage() {
  return (
    <Suspense fallback={<div className="p-6 text-zinc-400">Preparing labels…</div>}>
      <PrintInner />
    </Suspense>
  );
}
