"use client";

import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

export const DRYING_OPTIONS = [
  {
    value: "needs_drying",
    title: "Needs drying",
    hint: "Received sealed — dry before the first print.",
  },
  {
    value: "drying",
    title: "Put in dryer now",
    hint: "Start drying and place the rolls on a dryer.",
  },
  {
    value: "dry",
    title: "Already dry",
    hint: "Ready to print. Records last dried as now.",
  },
  {
    value: "unknown",
    title: "Keep sealed",
    hint: "No drying recorded — leave in sealed storage.",
  },
] as const;

export type DryingStatusValue = (typeof DRYING_OPTIONS)[number]["value"];

export function dryingLabel(status: string | null | undefined) {
  const opt = DRYING_OPTIONS.find((o) => o.value === status);
  if (opt) return opt.title;
  return (status || "unknown").replaceAll("_", " ");
}

export function DryingChoice({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: DryingStatusValue) => void;
}) {
  return (
    <div className="space-y-2">
      <Label>Drying</Label>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {DRYING_OPTIONS.map((opt) => {
          const selected = value === opt.value;
          return (
            <button
              key={opt.value}
              type="button"
              onClick={() => onChange(opt.value)}
              className={cn(
                "min-h-16 rounded-xl border px-3 py-3 text-left transition-colors",
                selected
                  ? "border-amber-500/60 bg-amber-500/15 text-amber-100"
                  : "border-white/10 text-zinc-300 hover:bg-white/5",
              )}
            >
              <div className="text-sm font-medium">{opt.title}</div>
              <div className="mt-0.5 text-xs text-zinc-500">{opt.hint}</div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
