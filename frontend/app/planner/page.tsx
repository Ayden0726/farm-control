"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import Link from "next/link";
import type { GCode, Printer, Product, ProductionRun } from "@/lib/types";
import {
  PlannerCalendar,
  formatLongDate,
  hoursLabel,
  toIsoDate,
  type CalendarDay,
  type CalendarPayload,
} from "@/components/planner-calendar";

type Line = {
  id: string;
  part_sku: string;
  part_name: string;
  printer_id: string | null;
  printer_name: string | null;
  quantity: number;
  jobs_needed: number;
  estimated_start: string | null;
  estimated_end: string | null;
  required_filament_g: number;
  filament_ok: boolean;
  compatible: boolean;
  incompatibility_reason: string;
  order_refs: string[];
  reason: string;
  included: boolean;
  gcode_filename: string | null;
};

type Plan = {
  id: string;
  status: string;
  lines: Line[];
  production_run_id?: string | null;
  needed_by?: string | null;
};

type AutoPrinter = {
  id: string;
  name: string;
  status: string;
  is_enabled: boolean;
  selected: boolean;
  compatible_file_count: number;
  file_count: number;
  issues: string[];
};

type ScheduleFile = {
  gcode_file_id: string;
  part_id: string;
  filename: string;
  part_sku: string;
  required_qty: number;
};

export default function PlannerPage() {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [printers, setPrinters] = useState<Printer[]>([]);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState(toIsoDate(new Date()));
  const [view, setView] = useState<"month" | "week">("month");
  const [month, setMonth] = useState(() => {
    const d = new Date();
    return { year: d.getFullYear(), month: d.getMonth() + 1 };
  });
  const [calendar, setCalendar] = useState<CalendarPayload | null>(null);
  const [calLoading, setCalLoading] = useState(true);
  const [calError, setCalError] = useState<string | null>(null);
  const [gcode, setGcode] = useState<GCode[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [files, setFiles] = useState<ScheduleFile[]>([]);
  const [filePick, setFilePick] = useState("");
  const [productId, setProductId] = useState("");
  const [productQty, setProductQty] = useState("1");
  const [includeOptional, setIncludeOptional] = useState(false);
  const [autoPrinters, setAutoPrinters] = useState<AutoPrinter[]>([]);
  const [selectedPrinters, setSelectedPrinters] = useState<string[]>([]);
  const [printersLoading, setPrintersLoading] = useState(false);
  const [scheduleName, setScheduleName] = useState("");

  const dayMap = useMemo(() => new Map((calendar?.days || []).map((d) => [d.date, d])), [calendar]);
  const selectedDay: CalendarDay | undefined = dayMap.get(selected);

  const loadCalendar = useCallback(async (year: number, monthNum: number) => {
    setCalLoading(true);
    setCalError(null);
    try {
      const row = await api<CalendarPayload>(`/api/v1/planner/calendar?year=${year}&month=${monthNum}`);
      setCalendar(row);
    } catch (err) {
      setCalError(err instanceof Error ? err.message : "Could not load the production calendar");
    } finally {
      setCalLoading(false);
    }
  }, []);

  useEffect(() => {
    loadCalendar(month.year, month.month);
  }, [month.year, month.month, loadCalendar]);

  useEffect(() => {
    api<Printer[]>("/api/v1/printers").then(setPrinters).catch(() => undefined);
    api<GCode[]>("/api/v1/gcode")
      .then((rows) => setGcode(rows.filter((g) => !g.is_archived)))
      .catch(() => undefined);
    api<Product[]>("/api/v1/products").then(setProducts).catch(() => undefined);
  }, []);

  const fileKey = files.map((f) => f.gcode_file_id).join(",");

  useEffect(() => {
    if (!fileKey && !productId) {
      setAutoPrinters([]);
      setSelectedPrinters([]);
      return;
    }
    let cancelled = false;
    setPrintersLoading(true);
    api<{ printers: AutoPrinter[] }>("/api/v1/planner/auto-printers", {
      method: "POST",
      body: JSON.stringify({
        gcode_file_ids: fileKey ? fileKey.split(",") : [],
        product_id: productId || null,
        product_qty: Math.max(1, Number(productQty) || 1),
        include_optional: includeOptional,
      }),
    })
      .then((res) => {
        if (cancelled) return;
        setAutoPrinters(res.printers);
        setSelectedPrinters(res.printers.filter((p) => p.selected).map((p) => p.id));
      })
      .catch((err) => {
        if (!cancelled) toast.error(err instanceof Error ? err.message : "Could not auto-select printers");
      })
      .finally(() => {
        if (!cancelled) setPrintersLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [fileKey, productId, productQty, includeOptional]);

  useEffect(() => {
    if (!plan || plan.status !== "draft") return;
    if (toIsoDate(plan.needed_by) === selected) return;
    api<Plan>(`/api/v1/planner/${plan.id}`, {
      method: "PATCH",
      body: JSON.stringify({ needed_by: selected }),
    })
      .then(setPlan)
      .catch(() => undefined);
  }, [selected, plan?.id, plan?.needed_by, plan?.status]);

  async function generate() {
    setBusy(true);
    try {
      const row = await api<Plan>("/api/v1/planner/generate", {
        method: "POST",
        body: JSON.stringify({ needed_by: selected }),
      });
      setPlan(row);
      toast.success(
        `Production plan generated for ${formatLongDate(selected)}. Review shortages before committing to the queue.`,
      );
      loadCalendar(month.year, month.month);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not generate plan");
    } finally {
      setBusy(false);
    }
  }

  async function patch(line: Line, patch: Partial<Line>) {
    if (!plan) return;
    const next = await api<Plan>(`/api/v1/planner/${plan.id}/lines/${line.id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    });
    setPlan(next);
  }

  async function commit() {
    if (!plan) return;
    setBusy(true);
    try {
      const res = await api<{ run?: { id: string; batch_code?: string; needed_by?: string | null } }>(
        `/api/v1/planner/${plan.id}/commit`,
        { method: "POST", body: JSON.stringify({ needed_by: selected }) },
      );
      const due = res.run?.needed_by ? ` · needed by ${toIsoDate(res.run.needed_by)}` : "";
      toast.success(
        res.run?.batch_code ? `Committed ${res.run.batch_code}${due}` : "Plan committed to the print queue",
      );
      loadCalendar(month.year, month.month);
      generate();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Commit failed");
    } finally {
      setBusy(false);
    }
  }

  function addFile() {
    const g = gcode.find((row) => row.id === filePick);
    if (!g) {
      toast.error("Pick a G-code file first");
      return;
    }
    if (!g.part_id) {
      toast.error(`${g.filename} is not tagged to a part. Tag it on the Library tab.`);
      return;
    }
    if (files.some((f) => f.gcode_file_id === g.id)) {
      toast.message("That file is already on this schedule");
      return;
    }
    setFiles((cur) => [
      ...cur,
      {
        gcode_file_id: g.id,
        part_id: g.part_id as string,
        filename: g.filename,
        part_sku: g.part_sku || "",
        required_qty: g.quantity_per_file || 1,
      },
    ]);
    setFilePick("");
  }

  async function schedule() {
    if (!files.length && !productId) {
      toast.error("Add G-code files or a catalog product");
      return;
    }
    setBusy(true);
    try {
      const res = await api<{
        run: ProductionRun;
        missing_gcode: string[];
        optional_skipped: string[];
        multi_file_parts: string[];
      }>("/api/v1/planner/schedule", {
        method: "POST",
        body: JSON.stringify({
          needed_by: selected,
          name: scheduleName,
          printer_ids: selectedPrinters,
          auto_select_printers: false,
          items: files.map((f) => ({
            part_id: f.part_id,
            gcode_file_id: f.gcode_file_id,
            required_qty: f.required_qty,
          })),
          product_id: productId || null,
          product_qty: Math.max(1, Number(productQty) || 1),
          include_optional: includeOptional,
          start_immediately: true,
        }),
      });
      const due = res.run.needed_by ? toIsoDate(res.run.needed_by) : selected;
      toast.success(
        `${res.run.batch_code || res.run.name} queued · needed by ${due}. Jobs enqueue now; earlier due dates print first.`,
      );
      if (res.missing_gcode.length) {
        toast.message(`No G-code tagged for ${res.missing_gcode.join(", ")}.`);
      }
      if (res.multi_file_parts.length) {
        toast.message(`${res.multi_file_parts.join(", ")} has more than one tagged file.`);
      }
      setFiles([]);
      setProductId("");
      setScheduleName("");
      loadCalendar(month.year, month.month);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not schedule production");
    } finally {
      setBusy(false);
    }
  }

  const canSchedule = files.length > 0 || Boolean(productId);
  const autoCount = autoPrinters.filter((p) => p.selected).length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-zinc-400">
          Pick the day the work is needed by, auto-select compatible printers, add G-code or a catalog product, then
          schedule it onto the print queue. Generate production plan still calculates true shortages from open orders
          minus available inventory (physical − reserved) minus jobs already in the queue.
        </p>
        <Button onClick={generate} disabled={busy}>
          {busy ? "Working…" : "Generate production plan"}
        </Button>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
        <Card>
          <CardHeader>
            <CardTitle>Production calendar</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <PlannerCalendar
              calendar={calendar}
              selected={selected}
              view={view}
              loading={calLoading}
              error={calError}
              onSelect={setSelected}
              onMonthChange={(year, monthNum) => setMonth({ year, month: monthNum })}
              onViewChange={setView}
              onRetry={() => loadCalendar(month.year, month.month)}
            />
            {calendar && calendar.undated_queued_jobs > 0 && (
              <p className="text-xs text-zinc-500">
                {calendar.undated_queued_jobs} queued job{calendar.undated_queued_jobs === 1 ? "" : "s"} have no
                needed-by date and stay at the back of dated work.
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Schedule for {formatLongDate(selected)}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="rounded-md border border-white/8 bg-zinc-950/50 p-3 text-sm">
              <div className="font-medium text-amber-100">Needed by {toIsoDate(selected)}</div>
              {selectedDay ? (
                <div className="mt-1 text-xs text-zinc-400">
                  {selectedDay.runs.length} batch{selectedDay.runs.length === 1 ? "" : "es"} ·{" "}
                  {selectedDay.orders.length} order{selectedDay.orders.length === 1 ? "" : "s"} due ·{" "}
                  {hoursLabel(selectedDay.estimated_seconds)} booked
                  {calendar ? ` vs ${hoursLabel(calendar.printer_seconds_per_day)} across ${calendar.printer_count} printer${calendar.printer_count === 1 ? "" : "s"}` : ""}
                  {selectedDay.over_capacity ? " · over a full printer-day" : ""}
                </div>
              ) : (
                <div className="mt-1 text-xs text-zinc-500">No dated work on this day yet.</div>
              )}
              {selectedDay && selectedDay.runs.length > 0 && (
                <ul className="mt-2 space-y-1 text-xs">
                  {selectedDay.runs.map((run) => (
                    <li key={run.id}>
                      <Link href={`/production/${run.id}`} className="text-amber-200 hover:underline">
                        {run.batch_code || run.name}
                      </Link>{" "}
                      <span className="text-zinc-500">
                        · {run.status} · {run.queued_jobs} queued
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              {selectedDay && selectedDay.orders.length > 0 && (
                <ul className="mt-2 space-y-1 text-xs text-zinc-400">
                  {selectedDay.orders.map((order) => (
                    <li key={order.id}>
                      Order {order.reference}
                      {order.customer_name ? ` · ${order.customer_name}` : ""}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="space-y-1">
              <Label>Batch name (optional)</Label>
              <Input
                value={scheduleName}
                onChange={(e) => setScheduleName(e.target.value)}
                placeholder={`Due ${selected}`}
              />
            </div>

            <div className="space-y-2 rounded-md border border-white/10 p-3">
              <Label>Add G-code files</Label>
              <div className="flex flex-col gap-2 sm:flex-row">
                <select
                  className="h-8 min-w-0 flex-1 rounded-lg border border-input bg-transparent px-2 text-sm"
                  value={filePick}
                  onChange={(e) => setFilePick(e.target.value)}
                >
                  <option value="">G-code file…</option>
                  {gcode.map((g) => (
                    <option key={g.id} value={g.id}>
                      {g.filename}
                      {g.part_sku ? ` · ${g.part_sku}` : ""}
                    </option>
                  ))}
                </select>
                <Button type="button" variant="outline" onClick={addFile}>
                  Add file
                </Button>
              </div>
              {gcode.length === 0 && (
                <p className="text-xs text-zinc-500">No G-code in the library yet. Upload files on the Library tab.</p>
              )}
              {files.map((file) => (
                <div key={file.gcode_file_id} className="flex items-center gap-2 text-sm">
                  <div className="min-w-0 flex-1 truncate">
                    {file.filename}
                    <span className="text-zinc-500"> · {file.part_sku}</span>
                  </div>
                  <Input
                    className="w-16"
                    type="number"
                    min={1}
                    value={file.required_qty}
                    onChange={(e) =>
                      setFiles((cur) =>
                        cur.map((row) =>
                          row.gcode_file_id === file.gcode_file_id
                            ? { ...row, required_qty: Math.max(1, Number(e.target.value) || 1) }
                            : row,
                        ),
                      )
                    }
                    aria-label={`Quantity for ${file.filename}`}
                  />
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() => setFiles((cur) => cur.filter((row) => row.gcode_file_id !== file.gcode_file_id))}
                  >
                    Remove
                  </Button>
                </div>
              ))}
            </div>

            <div className="space-y-2 rounded-md border border-white/10 p-3">
              <Label>Or explode a catalog product</Label>
              <p className="text-xs text-zinc-500">
                Uses the same BOM + tagged G-code explode as production runs. Hardware lines are skipped.
              </p>
              <div className="grid gap-2 sm:grid-cols-[1fr_70px]">
                <select
                  className="h-8 rounded-lg border border-input bg-transparent px-2 text-sm"
                  value={productId}
                  onChange={(e) => setProductId(e.target.value)}
                >
                  <option value="">Product…</option>
                  {products
                    .filter((p) => p.is_active)
                    .map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.sku} · {p.name}
                      </option>
                    ))}
                </select>
                <Input
                  type="number"
                  min={1}
                  value={productQty}
                  onChange={(e) => setProductQty(e.target.value)}
                  aria-label="Product quantity"
                />
              </div>
              <label className="flex items-center gap-2 text-xs text-zinc-400">
                <input type="checkbox" checked={includeOptional} onChange={(e) => setIncludeOptional(e.target.checked)} />
                Include optional BOM accessories
              </label>
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <Label>Printers</Label>
                <span className="text-xs text-zinc-500">
                  {printersLoading
                    ? "Matching…"
                    : autoCount
                      ? `${autoCount} auto-selected · uncheck to exclude`
                      : canSchedule
                        ? "No compatible enabled printers"
                        : "Add files to auto-select"}
                </span>
              </div>
              {canSchedule && autoPrinters.length === 0 && !printersLoading && (
                <p className="text-xs text-zinc-500">No printers returned. Check that machines are enabled.</p>
              )}
              <div className="grid max-h-48 gap-1 overflow-y-auto">
                {autoPrinters.map((p) => (
                  <label key={p.id} className="flex items-start gap-2 rounded-md border border-white/8 p-2 text-sm">
                    <input
                      type="checkbox"
                      className="mt-0.5"
                      checked={selectedPrinters.includes(p.id)}
                      onChange={(e) =>
                        setSelectedPrinters((cur) =>
                          e.target.checked ? [...cur, p.id] : cur.filter((id) => id !== p.id),
                        )
                      }
                    />
                    <span>
                      <span className="font-medium">{p.name}</span>
                      <span className="text-zinc-500">
                        {" "}
                        · {p.status}
                        {p.selected ? "" : p.is_enabled ? " · not auto-selected" : " · disabled"}
                      </span>
                      <span className="block text-xs text-zinc-500">
                        Compatible with {p.compatible_file_count} of {p.file_count} file{p.file_count === 1 ? "" : "s"}
                      </span>
                      {p.issues.length > 0 && (
                        <span className="block text-xs text-amber-200/80">{p.issues[0]}</span>
                      )}
                    </span>
                  </label>
                ))}
              </div>
            </div>

            <Button className="w-full" disabled={busy || !canSchedule} onClick={schedule}>
              {busy ? "Scheduling…" : `Schedule for ${selected}`}
            </Button>
            <p className="text-xs text-zinc-500">
              Jobs enqueue now with this needed-by date. The scheduler still assigns idle compatible printers; earlier
              due dates sit ahead of later or undated queued work. Overnight rules stay metadata only.
            </p>
          </CardContent>
        </Card>
      </div>

      {!plan && (
        <p className="text-sm text-zinc-500">
          Generate a plan to review shortage-driven printer assignments before queueing, or schedule files for the
          selected day above.
        </p>
      )}
      {plan && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle>Draft plan</CardTitle>
              <p className="text-xs text-zinc-500">
                Needed by {plan.needed_by || selected}. Compatible printers are recommended per part; you can still
                reassign before commit.
              </p>
            </div>
            <Button onClick={commit} disabled={busy || plan.status !== "draft"}>
              Commit to print queue
            </Button>
          </CardHeader>
          <CardContent className="space-y-3">
            {plan.lines.length === 0 && (
              <p className="text-sm text-zinc-500">Nothing to print. Inventory covers open orders.</p>
            )}
            {plan.lines.map((line) => (
              <div key={line.id} className="space-y-2 rounded-md border border-white/8 p-3 text-sm">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={line.included}
                    onChange={(e) => patch(line, { included: e.target.checked } as never)}
                  />
                  <span className="font-medium">
                    {line.part_sku} · {line.quantity} pcs
                  </span>
                </label>
                <div className="grid gap-2 md:grid-cols-4">
                  <div>
                    Printer
                    <select
                      className="mt-1 h-8 w-full rounded-lg border border-input bg-transparent px-2"
                      value={line.printer_id || ""}
                      onChange={(e) => patch(line, { printer_id: e.target.value || null } as never)}
                    >
                      <option value="">Unassigned</option>
                      {printers.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    Quantity
                    <Input
                      className="mt-1"
                      type="number"
                      value={line.quantity}
                      onChange={(e) => patch(line, { quantity: Number(e.target.value) } as never)}
                    />
                  </div>
                  <div>
                    <div className="text-zinc-500">Start → finish</div>
                    <div className="font-mono text-xs">
                      {line.estimated_start ? new Date(line.estimated_start).toLocaleString() : "—"}
                      <br />
                      {line.estimated_end ? new Date(line.estimated_end).toLocaleString() : "—"}
                    </div>
                  </div>
                  <div>
                    <div className="text-zinc-500">Filament</div>
                    <div>
                      {line.required_filament_g.toFixed(0)} g {line.filament_ok ? "" : "· short"}
                    </div>
                    <div className="text-xs text-zinc-500">{line.gcode_filename || "No G-code"}</div>
                  </div>
                </div>
                <div className="text-xs text-zinc-400">
                  {line.reason}
                  {line.order_refs.length ? ` · Orders ${line.order_refs.join(", ")}` : ""}
                </div>
                {!line.compatible && line.incompatibility_reason && (
                  <div className="rounded-md bg-amber-500/10 p-2 text-xs text-amber-200">
                    Job incompatible{line.printer_name ? ` with ${line.printer_name}` : ""}. Reason:{" "}
                    {line.incompatibility_reason}
                  </div>
                )}
              </div>
            ))}
            <Link href="/timeline" className="text-xs text-amber-300 hover:underline">
              Open production timeline
            </Link>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
