"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { StatusPill } from "@/components/status-pill";

type Note = {
  id: string;
  type: string;
  title: string;
  body: string;
  severity: string;
  is_read: boolean;
  created_at: string;
};

export default function NotificationsPage() {
  const [rows, setRows] = useState<Note[]>([]);
  async function load() {
    setRows(await api<Note[]>("/api/v1/notifications"));
  }
  useEffect(() => {
    load();
  }, []);

  return (
    <div className="space-y-3">
      <Button
        variant="outline"
        onClick={async () => {
          await api("/api/v1/notifications/read-all", { method: "POST" });
          load();
        }}
      >
        Mark all read
      </Button>
      {rows.map((n) => (
        <div
          key={n.id}
          className={`rounded-xl border border-white/8 p-4 ${n.is_read ? "opacity-60" : "bg-white/3"}`}
        >
          <div className="flex items-center justify-between gap-2">
            <div className="font-medium">{n.title}</div>
            <StatusPill status={n.severity === "error" ? "failed" : n.severity === "warning" ? "waiting_for_bed_clear" : "queued"} />
          </div>
          <p className="mt-1 text-sm text-zinc-400">{n.body}</p>
          <div className="mt-2 text-xs text-zinc-500">{new Date(n.created_at).toLocaleString()}</div>
        </div>
      ))}
    </div>
  );
}
