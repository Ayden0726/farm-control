"use client";

import { cn } from "@/lib/utils";

export function RangeSlider({
  min,
  max,
  step = 1,
  value,
  onValueChange,
  disabled,
  className,
  "aria-label": ariaLabel,
}: {
  min: number;
  max: number;
  step?: number;
  value: number;
  onValueChange: (value: number) => void;
  disabled?: boolean;
  className?: string;
  "aria-label"?: string;
}) {
  const hi = Math.max(min, max);
  const clamped = Math.min(hi, Math.max(min, value));
  const pct = hi <= min ? 100 : ((clamped - min) / (hi - min)) * 100;
  return (
    <input
      type="range"
      min={min}
      max={hi}
      step={step}
      value={Number.isFinite(clamped) ? clamped : min}
      disabled={disabled}
      aria-label={ariaLabel}
      aria-valuemin={min}
      aria-valuemax={hi}
      aria-valuenow={clamped}
      className={cn("farm-range", className)}
      style={{ ["--range-progress" as string]: `${pct}%` }}
      onChange={(e) => onValueChange(Number(e.target.value))}
    />
  );
}
