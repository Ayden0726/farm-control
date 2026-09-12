export function formatPcs(n: number | null | undefined): string {
  const value = Number(n || 0);
  if (!Number.isFinite(value)) return "0 pcs";
  if (Math.abs(value - Math.round(value)) < 1e-9) return `${Math.round(value)} pcs`;
  return `${value} pcs`;
}
