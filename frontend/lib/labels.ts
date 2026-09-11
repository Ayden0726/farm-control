export type LabelLayout = "sheet" | "one" | "label";

export const LABEL_PRESETS: Record<
  LabelLayout,
  { layout: LabelLayout; w: number; h: number; cols: number; label: string; hint: string }
> = {
  one: { layout: "one", w: 100, h: 140, cols: 1, label: "One per page", hint: "A4, one spool label per sheet" },
  sheet: { layout: "sheet", w: 54, h: 70, cols: 3, label: "Adhesive sheet", hint: "Grid of labels on a sheet" },
  label: { layout: "label", w: 54, h: 70, cols: 1, label: "Label printer", hint: "One label, printer-sized page" },
};

export function labelsPrintHref(
  kind: "spool" | "product",
  ids: string[],
  opts?: { layout?: LabelLayout; w?: number; h?: number; cols?: number; auto?: boolean },
) {
  const preset = LABEL_PRESETS[opts?.layout || "sheet"];
  const q = new URLSearchParams({
    kind,
    ids: ids.join(","),
    layout: opts?.layout || preset.layout,
    w: String(opts?.w ?? preset.w),
    h: String(opts?.h ?? preset.h),
    cols: String(opts?.cols ?? preset.cols),
  });
  if (opts?.auto) q.set("auto", "1");
  return `/labels/print?${q.toString()}`;
}
