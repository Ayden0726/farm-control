"use client";

import { useMemo, useRef, useState } from "react";
import { cn } from "@/lib/utils";

export type PlatePart = {
  index: number;
  x: number;
  y: number;
  w: number;
  h: number;
  rotation_z: number;
};

export type PlateView = {
  bed_w: number;
  bed_h: number;
  placed: PlatePart[];
  keepouts?: { x: number; y: number; w: number; h: number }[];
  utilisation?: number;
};

export function PlatePreview({
  plate,
  selected,
  onSelect,
  onMove,
  interactive,
}: {
  plate: PlateView | null;
  selected: number | null;
  onSelect?: (index: number | null) => void;
  onMove?: (index: number, x: number, y: number) => void;
  interactive?: boolean;
}) {
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const drag = useRef<{ index: number; ox: number; oy: number } | null>(null);

  const vb = useMemo(() => {
    const w = plate?.bed_w || 220;
    const h = plate?.bed_h || 220;
    const pad = 12;
    return `${-pad + pan.x} ${-pad + pan.y} ${(w + pad * 2) / zoom} ${(h + pad * 2) / zoom}`;
  }, [plate, zoom, pan]);

  if (!plate) {
    return (
      <div className="flex min-h-64 items-center justify-center rounded-xl border border-dashed border-white/15 text-sm text-zinc-500">
        Choose an STL and printer to preview the plate.
      </div>
    );
  }

  function clientToBed(event: React.PointerEvent<SVGSVGElement>) {
    const svg = event.currentTarget;
    const rect = svg.getBoundingClientRect();
    const w = plate!.bed_w;
    const h = plate!.bed_h;
    const pad = 12;
    const vw = (w + pad * 2) / zoom;
    const vh = (h + pad * 2) / zoom;
    const x = ((event.clientX - rect.left) / rect.width) * vw + (-pad + pan.x);
    const y = ((event.clientY - rect.top) / rect.height) * vh + (-pad + pan.y);
    return { x, y };
  }

  return (
    <div className="space-y-2">
      <svg
        viewBox={vb}
        className="h-[min(70vw,28rem)] w-full rounded-xl bg-[#10161c] ring-1 ring-white/10 touch-none"
        onWheel={(e) => {
          e.preventDefault();
          setZoom((z) => Math.min(4, Math.max(0.6, z * (e.deltaY > 0 ? 0.9 : 1.1))));
        }}
        onPointerMove={(e) => {
          if (!interactive || !drag.current || !onMove) return;
          const pt = clientToBed(e);
          onMove(drag.current.index, pt.x - drag.current.ox, pt.y - drag.current.oy);
        }}
        onPointerUp={() => {
          drag.current = null;
        }}
      >
        <rect x={0} y={0} width={plate.bed_w} height={plate.bed_h} fill="#1b242e" stroke="#f59e0b55" strokeWidth={1} />
        <text x={4} y={12} fill="#71717a" fontSize={8}>
          Printable {plate.bed_w.toFixed(0)}×{plate.bed_h.toFixed(0)} mm
        </text>
        {(plate.keepouts || []).map((k, i) => (
          <rect key={`k${i}`} x={k.x} y={k.y} width={k.w} height={k.h} fill="#ef44444d" stroke="#ef4444" strokeWidth={0.6} />
        ))}
        {plate.placed.map((p) => (
          <g key={p.index}>
            <rect
              x={p.x}
              y={p.y}
              width={p.w}
              height={p.h}
              fill={selected === p.index ? "#f59e0b99" : "#38bdf866"}
              stroke={selected === p.index ? "#fbbf24" : "#7dd3fc"}
              strokeWidth={0.8}
              className={cn(interactive ? "cursor-grab" : "")}
              onPointerDown={(e) => {
                if (!interactive) return;
                e.stopPropagation();
                onSelect?.(p.index);
                const svg = (e.target as SVGRectElement).ownerSVGElement;
                if (!svg) return;
                const rect = svg.getBoundingClientRect();
                const pad = 12;
                const vw = (plate.bed_w + pad * 2) / zoom;
                const vh = (plate.bed_h + pad * 2) / zoom;
                const x = ((e.clientX - rect.left) / rect.width) * vw + (-pad + pan.x);
                const y = ((e.clientY - rect.top) / rect.height) * vh + (-pad + pan.y);
                drag.current = { index: p.index, ox: x - p.x, oy: y - p.y };
                (e.target as SVGRectElement).setPointerCapture(e.pointerId);
              }}
            />
            <text x={p.x + 1.5} y={p.y + 6} fill="#0b0f14" fontSize={6} fontWeight={600}>
              {p.index + 1}
              {p.rotation_z ? ` ${p.rotation_z}°` : ""}
            </text>
          </g>
        ))}
      </svg>
      <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-500">
        <button type="button" className="rounded border border-white/10 px-2 py-1" onClick={() => setZoom((z) => Math.min(4, z * 1.2))}>
          Zoom in
        </button>
        <button type="button" className="rounded border border-white/10 px-2 py-1" onClick={() => setZoom((z) => Math.max(0.6, z / 1.2))}>
          Zoom out
        </button>
        <button
          type="button"
          className="rounded border border-white/10 px-2 py-1"
          onClick={() => {
            setZoom(1);
            setPan({ x: 0, y: 0 });
          }}
        >
          Reset view
        </button>
        <span>Pan with zoom. {interactive ? "Desktop: drag a part to move it." : ""}</span>
      </div>
    </div>
  );
}
