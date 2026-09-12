"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Job, Printer } from "@/lib/types";
import { StatusPill } from "@/components/status-pill";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDuration } from "@/lib/format";
import { toast } from "sonner";

export default function QueuePage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [history, setHistory] = useState(false);
  const [printers, setPrinters] = useState<Printer[]>([]);

  async function load() {
    const path = history ? "/api/v1/queue?history=true" : "/api/v1/queue";
    setJobs(await api<Job[]>(path));
    setPrinters(await api<Printer[]>("/api/v1/printers"));
  }
  useEffect(() => {
    load();
    const id = setInterval(load, 2500);
    return () => clearInterval(id);
  }, [history]);

  async function act(id: string, action: string, body?: unknown) {
    try {
      await api(`/api/v1/queue/${id}/${action}`, {
        method: "POST",
        body: body ? JSON.stringify(body) : undefined,
      });
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Action failed");
    }
  }

  function JobActions({ job }: { job: Job }) {
    return (
      <div className="flex flex-wrap gap-1">
        {(job.status === "queued" || job.status === "printing") && (
          <Button size="xs" variant="outline" className="min-h-9 px-3 md:min-h-6 md:px-2" onClick={() => act(job.id, "pause")}>
            Pause
          </Button>
        )}
        {(job.status === "held" || job.status === "paused") && (
          <Button size="xs" variant="outline" className="min-h-9 px-3 md:min-h-6 md:px-2" onClick={() => act(job.id, "resume")}>
            Resume
          </Button>
        )}
        {(job.status === "queued" || job.status === "held") && (
          <>
            <Button size="xs" variant="outline" className="min-h-9 px-3 md:min-h-6 md:px-2" onClick={() => act(job.id, "move-up")}>
              Up
            </Button>
            <Button size="xs" variant="outline" className="min-h-9 px-3 md:min-h-6 md:px-2" onClick={() => act(job.id, "move-down")}>
              Down
            </Button>
          </>
        )}
        {["queued", "held", "printing", "paused"].includes(job.status) && (
          <Button size="xs" variant="destructive" className="min-h-9 px-3 md:min-h-6 md:px-2" onClick={() => act(job.id, "cancel")}>
            Cancel
          </Button>
        )}
        {["queued", "held", "printing", "paused"].includes(job.status) && (
          <select
            className="h-9 rounded-md border border-input bg-transparent px-2 text-sm md:h-6 md:px-1 md:text-[11px]"
            defaultValue=""
            onChange={(e) => {
              if (e.target.value) act(job.id, "move", { printer_id: e.target.value });
            }}
          >
            <option value="">Move to…</option>
            {printers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        )}
        {job.hold_reason === "insufficient_filament" && (
          <>
            <Button size="xs" variant="outline" className="min-h-9 px-3 md:min-h-6 md:px-2" onClick={() => act(job.id, "override-filament")}>
              Override
            </Button>
            <Link href="/scan" className="inline-flex h-9 items-center rounded-md border border-input px-3 text-sm md:h-6 md:px-2 md:text-[11px]">
              Change spool
            </Link>
          </>
        )}
        {job.incompatibility_reason && !job.compatibility_override && ["queued", "held"].includes(job.status) && (
          <Button size="xs" variant="outline" className="min-h-9 px-3 md:min-h-6 md:px-2" onClick={() => act(job.id, "override-compatibility")}>
            Override compatibility
          </Button>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          The scheduler assigns queued jobs to compatible idle printers that are not waiting for bed clearance.
        </p>
        <Button variant="outline" onClick={() => setHistory((h) => !h)}>
          {history ? "Show active queue" : "Show permanent history"}
        </Button>
      </div>
      <div className="space-y-3 md:hidden">
        {jobs.map((job) => (
          <div key={job.id} className="rounded-xl border border-white/8 bg-[#141a21] p-3 space-y-2">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate font-medium">{job.gcode_filename}</div>
                <div className="text-xs text-zinc-500">
                  #{job.queue_position} · ×{job.quantity_produced} · {job.part_sku}
                </div>
              </div>
              <StatusPill status={job.status} />
            </div>
            <div className="text-xs text-zinc-400">
              {job.actual_printer_name || job.assigned_printer_name || "Any allowed"}
              {job.production_run_name ? ` · ${job.production_run_name}` : ""}
              {` · ${job.progress_percent.toFixed(0)}%`}
            </div>
            {job.hold_reason === "insufficient_filament" && (
              <div className="text-[11px] text-amber-200">
                Insufficient filament
                {job.filament_required_g ? `: need ${Math.round(job.filament_required_g)} g, have ${Math.round(job.filament_available_g || 0)} g` : ""}
              </div>
            )}
            {job.incompatibility_reason && !job.compatibility_override && (
              <div className="text-[11px] text-amber-200">
                Job incompatible{job.assigned_printer_name ? ` with ${job.assigned_printer_name}` : ""}. Reason:{" "}
                {job.incompatibility_reason}
              </div>
            )}
            <JobActions job={job} />
          </div>
        ))}
      </div>
      <div className="hidden md:block">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>#</TableHead>
            <TableHead>File / part</TableHead>
            <TableHead>Qty</TableHead>
            <TableHead>Run</TableHead>
            <TableHead>Printer</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Progress</TableHead>
            <TableHead></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {jobs.map((job) => (
            <TableRow key={job.id}>
              <TableCell className="font-mono text-xs">{job.queue_position}</TableCell>
              <TableCell>
                <div className="font-medium">{job.gcode_filename}</div>
                <div className="text-xs text-zinc-500">{job.part_sku}</div>
              </TableCell>
              <TableCell>×{job.quantity_produced}</TableCell>
              <TableCell className="text-xs">{job.production_run_name || "—"}</TableCell>
              <TableCell className="text-xs">
                {job.actual_printer_name || job.assigned_printer_name || "Any allowed"}
              </TableCell>
              <TableCell>
                <StatusPill status={job.status} />
                  {job.hold_reason === "insufficient_filament" && (
                    <div className="mt-1 max-w-[220px] text-[11px] text-amber-200">
                      Insufficient filament
                      {job.filament_required_g ? `: need ${Math.round(job.filament_required_g)} g, have ${Math.round(job.filament_available_g || 0)} g` : ""}
                    </div>
                  )}
                  {job.incompatibility_reason && !job.compatibility_override && (
                    <div className="mt-1 max-w-[260px] text-[11px] text-amber-200">
                      Job incompatible{job.assigned_printer_name ? ` with ${job.assigned_printer_name}` : ""}. Reason:{" "}
                      {job.incompatibility_reason}
                    </div>
                  )}
              </TableCell>
              <TableCell className="font-mono text-xs">
                {job.progress_percent.toFixed(0)}%
                {job.status === "printing" && (
                  <div className="text-zinc-500">{formatDuration(job.estimated_time_seconds)}</div>
                )}
              </TableCell>
              <TableCell>
                <JobActions job={job} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      </div>
      {jobs.length === 0 && <p className="text-sm text-zinc-500">No jobs in this view.</p>}
    </div>
  );
}
