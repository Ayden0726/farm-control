export function formatDuration(totalSeconds: number | null | undefined): string {
  const seconds = Math.max(0, Math.round(totalSeconds || 0));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s.toString().padStart(2, "0")}s`;
  return `${s}s`;
}

export function formatEta(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function formatMoney(value: number | null | undefined): string {
  return new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(value || 0);
}

/** Currency that stays blank when costing has no real number (never pretend $0.00). */
export function formatMoneyKnown(value: number | null | undefined): string {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(value);
}

export function formatFilamentRate(costPerG: number | null | undefined): string {
  if (costPerG == null || !(costPerG > 0)) return "—";
  const perKg = new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(costPerG * 1000);
  const cents = costPerG * 100;
  return `${perKg}/kg · ${cents.toFixed(2)} ¢/g`;
}

export function formatGramsKnown(value: number | null | undefined): string {
  if (value == null || !(value > 0)) return "—";
  if (value >= 1000) return `${(value / 1000).toFixed(2)} kg`;
  const rounded = Math.round(value * 10) / 10;
  return Number.isInteger(rounded) ? `${rounded} g` : `${rounded.toFixed(1)} g`;
}

export function formatGrams(value: number | null | undefined): string {
  const n = value || 0;
  if (n >= 1000) return `${(n / 1000).toFixed(2)} kg`;
  return `${Math.round(n)} g`;
}

export function formatHours(seconds: number): string {
  return `${(seconds / 3600).toFixed(1)} h`;
}

export function prettyStatus(status: string): string {
  return status.replaceAll("_", " ");
}
