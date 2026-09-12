"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type CalendarRun = {
  id: string;
  name: string;
  batch_code: string | null;
  status: string;
  needed_by: string;
  queued_jobs: number;
  printing_jobs: number;
  estimated_seconds: number;
  item_count: number;
};

export type CalendarOrder = {
  id: string;
  reference: string;
  customer_name: string;
  status: string;
  due_at: string;
};

export type CalendarDay = {
  date: string;
  runs: CalendarRun[];
  orders: CalendarOrder[];
  queued_jobs: number;
  printing_jobs: number;
  estimated_seconds: number;
  plan_lines: number;
  printer_seconds: number;
  over_capacity: boolean;
};

export type CalendarPayload = {
  year: number;
  month: number;
  start: string;
  end: string;
  printer_count: number;
  printer_seconds_per_day: number;
  undated_queued_jobs: number;
  days: CalendarDay[];
};

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export function toIsoDate(value: Date | string | null | undefined): string {
  if (!value) return "";
  if (typeof value === "string") return value.slice(0, 10);
  const y = value.getFullYear();
  const m = String(value.getMonth() + 1).padStart(2, "0");
  const d = String(value.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function parseIsoDate(value: string): Date {
  const [y, m, d] = value.split("-").map(Number);
  return new Date(y, (m || 1) - 1, d || 1);
}

export function formatLongDate(iso: string): string {
  return parseIsoDate(iso).toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}

export function hoursLabel(seconds: number): string {
  if (!seconds) return "0 h";
  const h = seconds / 3600;
  return h < 10 ? `${h.toFixed(1)} h` : `${Math.round(h)} h`;
}

function emptyDay(iso: string): CalendarDay {
  return {
    date: iso,
    runs: [],
    orders: [],
    queued_jobs: 0,
    printing_jobs: 0,
    estimated_seconds: 0,
    plan_lines: 0,
    printer_seconds: 0,
    over_capacity: false,
  };
}

function addMonths(year: number, month: number, delta: number): { year: number; month: number } {
  const d = new Date(year, month - 1 + delta, 1);
  return { year: d.getFullYear(), month: d.getMonth() + 1 };
}

export function PlannerCalendar({
  calendar,
  selected,
  view,
  loading,
  error,
  onSelect,
  onMonthChange,
  onViewChange,
  onRetry,
}: {
  calendar: CalendarPayload | null;
  selected: string;
  view: "month" | "week";
  loading: boolean;
  error: string | null;
  onSelect: (iso: string) => void;
  onMonthChange: (year: number, month: number) => void;
  onViewChange: (view: "month" | "week") => void;
  onRetry: () => void;
}) {
  const year = calendar?.year ?? parseIsoDate(selected).getFullYear();
  const month = calendar?.month ?? parseIsoDate(selected).getMonth() + 1;
  const byDate = new Map((calendar?.days || []).map((d) => [d.date, d]));
  const title = new Date(year, month - 1, 1).toLocaleDateString(undefined, { month: "long", year: "numeric" });
  const today = toIsoDate(new Date());

  let grid = calendar?.days || [];
  if (view === "week") {
    const selectedDate = parseIsoDate(selected);
    const start = new Date(selectedDate);
    start.setDate(selectedDate.getDate() - selectedDate.getDay());
    grid = Array.from({ length: 7 }, (_, i) => {
      const d = new Date(start);
      d.setDate(start.getDate() + i);
      const iso = toIsoDate(d);
      return byDate.get(iso) || emptyDay(iso);
    });
  }

  function shift(delta: number) {
    if (view === "week") {
      const next = parseIsoDate(selected);
      next.setDate(next.getDate() + delta * 7);
      const iso = toIsoDate(next);
      onSelect(iso);
      if (next.getMonth() + 1 !== month || next.getFullYear() !== year) {
        onMonthChange(next.getFullYear(), next.getMonth() + 1);
      }
      return;
    }
    const next = addMonths(year, month, delta);
    onMonthChange(next.year, next.month);
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          <Button type="button" variant="outline" size="icon-sm" onClick={() => shift(-1)} aria-label="Previous">
            <ChevronLeft />
          </Button>
          <div className="min-w-[10rem] text-center text-sm font-medium">{view === "week" ? `Week of ${formatLongDate(grid[0]?.date || selected)}` : title}</div>
          <Button type="button" variant="outline" size="icon-sm" onClick={() => shift(1)} aria-label="Next">
            <ChevronRight />
          </Button>
        </div>
        <div className="flex items-center gap-1">
          <Button type="button" size="sm" variant={view === "month" ? "default" : "outline"} onClick={() => onViewChange("month")}>
            Month
          </Button>
          <Button type="button" size="sm" variant={view === "week" ? "default" : "outline"} onClick={() => onViewChange("week")}>
            Week
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => {
              onSelect(today);
              const now = new Date();
              onMonthChange(now.getFullYear(), now.getMonth() + 1);
            }}
          >
            Today
          </Button>
        </div>
      </div>
      {error && (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-100">
          {error}{" "}
          <button type="button" className="underline" onClick={onRetry}>
            Retry
          </button>
        </div>
      )}
      {loading && !calendar && <p className="text-sm text-zinc-500">Loading calendar…</p>}
      <div className="grid grid-cols-7 gap-1 text-center text-[11px] uppercase tracking-wide text-zinc-500">
        {WEEKDAYS.map((d) => (
          <div key={d}>{d}</div>
        ))}
      </div>
      <div className={cn("grid grid-cols-7 gap-1", view === "week" ? "auto-rows-[7.5rem] md:auto-rows-[9rem]" : "auto-rows-[4.25rem] md:auto-rows-[5.25rem]")}>
        {grid.map((day) => {
          const inMonth = parseIsoDate(day.date).getMonth() + 1 === month;
          const isSelected = day.date === selected;
          const isToday = day.date === today;
          const work = day.runs.length + day.orders.length + day.plan_lines;
          return (
            <button
              key={day.date}
              type="button"
              onClick={() => onSelect(day.date)}
              className={cn(
                "flex h-full flex-col rounded-md border px-1 py-1 text-left transition-colors",
                inMonth ? "border-white/8 bg-zinc-950/40" : "border-transparent bg-transparent text-zinc-600",
                isSelected && "border-amber-400 bg-amber-500/15 ring-1 ring-amber-400",
                day.over_capacity && "border-amber-500/50",
                !isSelected && work > 0 && "hover:border-amber-300/40",
              )}
            >
              <div className="flex items-center justify-between">
                <span className={cn("text-xs font-medium", isToday && "text-amber-200")}>{parseIsoDate(day.date).getDate()}</span>
                {work > 0 && (
                  <span className="rounded-full bg-amber-500/20 px-1.5 text-[10px] text-amber-100">{work}</span>
                )}
              </div>
              {view === "week" ? (
                <div className="mt-1 space-y-0.5 overflow-hidden text-[10px] leading-tight text-zinc-400">
                  {day.runs.slice(0, 3).map((run) => (
                    <div key={run.id} className="truncate text-amber-100/90">
                      {run.batch_code || run.name}
                    </div>
                  ))}
                  {day.orders.slice(0, 2).map((order) => (
                    <div key={order.id} className="truncate">
                      Order {order.reference}
                    </div>
                  ))}
                  {day.plan_lines > 0 && <div>{day.plan_lines} draft plan line{day.plan_lines === 1 ? "" : "s"}</div>}
                  {day.estimated_seconds > 0 && <div>{hoursLabel(day.estimated_seconds)} queued</div>}
                </div>
              ) : (
                <div className="mt-auto flex gap-0.5">
                  {day.runs.length > 0 && <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />}
                  {day.orders.length > 0 && <span className="h-1.5 w-1.5 rounded-full bg-zinc-400" />}
                  {day.plan_lines > 0 && <span className="h-1.5 w-1.5 rounded-full bg-amber-200/60" />}
                </div>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
