export const NOZZLE_PRESETS = ["0.2", "0.25", "0.4", "0.6", "0.8", "1.0"];

export type PrinterTemplate = {
  id: string;
  name: string;
  notes: string;
  source_printer_id: string | null;
  snapshot: Record<string, unknown>;
};

const MODEL_HINTS: { match: string[]; x: number; y: number; z: number; nozzle: number }[] = [
  { match: ["cr-6 max", "cr6 max"], x: 400, y: 400, z: 400, nozzle: 0.4 },
  { match: ["k1 max"], x: 300, y: 300, z: 250, nozzle: 0.4 },
  { match: ["k2 pro"], x: 350, y: 350, z: 350, nozzle: 0.4 },
  { match: ["voron"], x: 350, y: 350, z: 330, nozzle: 0.4 },
  { match: ["cr-6 se", "cr6 se"], x: 235, y: 235, z: 250, nozzle: 0.4 },
];

export function modelPlateHint(model: string): { x: string; y: string; z: string; nozzle: string } | null {
  const key = model.toLowerCase();
  for (const row of MODEL_HINTS) {
    if (row.match.some((m) => key.includes(m))) {
      return { x: String(row.x), y: String(row.y), z: String(row.z), nozzle: String(row.nozzle) };
    }
  }
  return null;
}

export function mmString(value: unknown): string {
  if (value == null || value === "") return "";
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? String(n) : "";
}

export function optionalMm(raw: string): number | null {
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? n : null;
}
