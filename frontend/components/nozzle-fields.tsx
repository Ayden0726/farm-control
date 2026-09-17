"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NOZZLE_PRESETS } from "@/lib/printer-geometry";

export function NozzleFields({
  diameter,
  material,
  onDiameter,
  onMaterial,
}: {
  diameter: string;
  material: string;
  onDiameter: (value: string) => void;
  onMaterial: (value: string) => void;
}) {
  const preset = NOZZLE_PRESETS.includes(diameter) ? diameter : diameter ? "custom" : "";
  return (
    <div className="grid grid-cols-2 gap-2">
      <div className="space-y-1">
        <Label>Nozzle size</Label>
        <select
          className="h-8 w-full rounded-lg border border-input bg-transparent px-2 text-sm"
          value={preset}
          onChange={(e) => {
            if (e.target.value === "custom") {
              onDiameter(diameter && !NOZZLE_PRESETS.includes(diameter) ? diameter : "");
              return;
            }
            onDiameter(e.target.value);
          }}
        >
          <option value="">Select</option>
          {NOZZLE_PRESETS.map((n) => (
            <option key={n} value={n}>
              {n} mm
            </option>
          ))}
          <option value="custom">Custom</option>
        </select>
        {preset === "custom" && (
          <Input
            className="mt-1"
            inputMode="decimal"
            placeholder="0.4"
            value={diameter}
            onChange={(e) => onDiameter(e.target.value)}
          />
        )}
      </div>
      <div className="space-y-1">
        <Label>Nozzle material</Label>
        <Input
          placeholder="Brass"
          value={material}
          onChange={(e) => onMaterial(e.target.value)}
        />
      </div>
    </div>
  );
}
