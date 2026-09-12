"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type Lane = {
  printer_name: string;
  status: string;
  blocks: { job_id: string; label: string; start: string; end: string; status: string; current?: boolean }[];
};

export default function TimelinePage() {
  const [lanes, setLanes] = useState<Lane[]>([]);
  const [cap, setCap] = useState<{
    available_printer_hours: number;
    required_printer_hours: number;
    capacity_utilisation_pct: number;
    over_capacity: boolean;
    estimated_completion: string;
    backlog_jobs: number;
  } | null>(null);

  useEffect(() => {
    async function load() {
      const t = await api<{ lanes: Lane[] }>("/api/v1/timeline");
      setLanes(t.lanes);
      setCap(await api("/api/v1/capacity"));
    }
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="space-y-4">
      {cap && (
        <Card>
          <CardHeader>
            <CardTitle>Capacity · next 7 days</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-2 text-sm md:grid-cols-4">
            <div>Available: {cap.available_printer_hours} h</div>
            <div>Required: {cap.required_printer_hours} h</div>
            <div className={cap.over_capacity ? "text-amber-300" : ""}>
              Utilisation {cap.capacity_utilisation_pct}%
              {cap.over_capacity ? " — over capacity" : ""}
            </div>
            <div>Backlog {cap.backlog_jobs} jobs</div>
          </CardContent>
        </Card>
      )}
      {lanes.map((lane) => (
        <Card key={lane.printer_name}>
          <CardHeader>
            <CardTitle>
              {lane.printer_name} · {lane.status}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 text-sm">
            {lane.blocks.length === 0 && <p className="text-zinc-500">Idle</p>}
            {lane.blocks.map((b) => (
              <div key={b.job_id} className="flex justify-between rounded-md bg-white/5 px-3 py-2">
                <span>
                  {b.current ? "Now · " : ""}
                  {b.label}
                </span>
                <span className="font-mono text-xs text-zinc-400">
                  {new Date(b.start).toLocaleTimeString()}–{new Date(b.end).toLocaleTimeString()}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
