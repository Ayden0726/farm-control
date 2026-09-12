/** Parts of this one part packed on a plate, from names like Handle-x4.gcode. */
export function parseQuantityFromFilename(filename: string): number {
  const stem = filename.replace(/\.[^.]+$/, "");
  const matches = [...stem.matchAll(/(?:^|[\s._-])x(\d+)(?=$|[\s._-])/gi)];
  if (!matches.length) return 1;
  const n = Number.parseInt(matches[matches.length - 1][1], 10);
  if (!Number.isFinite(n) || n < 1) return 1;
  return Math.min(n, 999);
}
