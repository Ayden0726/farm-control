"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "sonner";

type Due = {
  printer_id: string;
  name: string;
  print_hours: number;
  interval_hours: number;
  hours_remaining: number;
  last_maintenance_at: string | null;
  notes: string;
};
type Log = {
  id: string;
  printer_name: string | null;
  performed_at: string;
  hours_at_service: number;
  kind: string;
  notes: string;
};

export default function MaintenancePage() {
  const [due, setDue] = useState<Due[]>([]);
  const [logs, setLogs] = useState<Log[]>([]);

  async function load() {
    setDue(await api<Due[]>("/api/v1/maintenance/due"));
    setLogs(await api<Log[]>("/api/v1/maintenance"));
  }
  useEffect(() => {
    load();
  }, []);

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Upcoming / due</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {due.length === 0 && <p className="text-sm text-zinc-500">No printers within 20 hours of their interval.</p>}
          {due.map((d) => (
            <div key={d.printer_id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-white/8 p-3">
              <div>
                <div className="font-medium">{d.name}</div>
                <div className="text-xs text-zinc-500">
                  {d.print_hours.toFixed(1)} h printed · interval {d.interval_hours} h · {d.hours_remaining.toFixed(1)} h remaining
                </div>
              </div>
              <Button
                size="sm"
                onClick={async () => {
                  await api(`/api/v1/maintenance/${d.printer_id}`, {
                    method: "POST",
                    body: JSON.stringify({ notes: "Interval service", kind: "service" }),
                  });
                  toast.success("Service logged");
                  load();
                }}
              >
                Log service
              </Button>
            </div>
          ))}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>History</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          {logs.map((l) => (
            <div key={l.id}>
              <span className="text-zinc-400">{new Date(l.performed_at).toLocaleString()}</span> · {l.printer_name} ·{" "}
              {l.hours_at_service.toFixed(1)} h · {l.notes}
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
