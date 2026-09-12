/** Parts of this one part packed on a plate, from names like Handle-4pcs.gcode. */
export function parseQuantityFromFilename(filename: string): number {
  const stem = filename.replace(/\.[^.]+$/, "");
  const pcs = [
    ...stem.matchAll(
      /(?:^|[\s_\-()]|(?<!\d)\.)(\d+)\s*[-_]?\s*(?:pieces|piece|pcs|pc)(?=$|[\s._\-()])/gi,
    ),
  ];
  if (pcs.length) return capFilenameQty(Number.parseInt(pcs[pcs.length - 1][1], 10));
  const xs = [...stem.matchAll(/(?:^|[\s._-])x(\d+)(?=$|[\s._-])/gi)];
  if (!xs.length) return 1;
  return capFilenameQty(Number.parseInt(xs[xs.length - 1][1], 10));
}

function capFilenameQty(n: number): number {
  if (!Number.isFinite(n) || n < 1) return 1;
  return Math.min(n, 999);
}
