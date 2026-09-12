import { cn } from "@/lib/utils";
import { prettyStatus } from "@/lib/format";

const STYLES: Record<string, string> = {
  printing: "bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30",
  idle: "bg-zinc-500/15 text-zinc-300 ring-1 ring-zinc-500/30",
  offline: "bg-zinc-800 text-zinc-500 ring-1 ring-zinc-700",
  error: "bg-red-500/15 text-red-300 ring-1 ring-red-500/40",
  paused: "bg-sky-500/15 text-sky-300 ring-1 ring-sky-500/30",
  waiting_for_bed_clear: "bg-amber-500/15 text-amber-300 ring-1 ring-amber-400/40",
  retired: "bg-zinc-800 text-zinc-400 ring-1 ring-zinc-600/50",
  queued: "bg-sky-500/15 text-sky-200 ring-1 ring-sky-500/30",
  held: "bg-orange-500/15 text-orange-300 ring-1 ring-orange-500/30",
  completed: "bg-emerald-500/15 text-emerald-200 ring-1 ring-emerald-500/20",
  failed: "bg-red-500/15 text-red-300 ring-1 ring-red-500/40",
  cancelled: "bg-zinc-700/40 text-zinc-400 ring-1 ring-zinc-600/40",
  in_progress: "bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30",
  draft: "bg-zinc-500/15 text-zinc-300 ring-1 ring-zinc-600/30",
  ready_to_ship: "bg-emerald-500/15 text-emerald-200 ring-1 ring-emerald-500/30",
  awaiting_production: "bg-amber-500/15 text-amber-200 ring-1 ring-amber-400/30",
  awaiting_qc: "bg-violet-500/15 text-violet-200 ring-1 ring-violet-500/30",
  shipped: "bg-zinc-500/15 text-zinc-300 ring-1 ring-zinc-600/30",
  new: "bg-sky-500/15 text-sky-200 ring-1 ring-sky-500/30",
  dry: "bg-emerald-500/15 text-emerald-200 ring-1 ring-emerald-500/20",
  drying: "bg-sky-500/15 text-sky-200 ring-1 ring-sky-500/30",
  needs_drying: "bg-amber-500/15 text-amber-200 ring-1 ring-amber-400/30",
};

export function StatusPill({ status, className }: { status: string; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-medium capitalize tracking-wide",
        STYLES[status] || "bg-zinc-700 text-zinc-200",
        className,
      )}
    >
      {status === "printing" && (
        <span className="size-1.5 animate-pulse rounded-full bg-emerald-400" />
      )}
      {status === "waiting_for_bed_clear" && (
        <span className="size-1.5 animate-pulse rounded-full bg-amber-400" />
      )}
      {status === "retired" && <span className="size-1.5 rounded-full bg-zinc-500" />}
      {prettyStatus(status)}
    </span>
  );
}
