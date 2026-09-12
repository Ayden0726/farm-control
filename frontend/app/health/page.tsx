"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "sonner";

type Check = { name: string; status: string; detail: string };
type Health = { status: string; generated_at: string; checks: Check[] };
type BackupList = {
  last_successful: string | null;
  backups: { id: string; filename: string; status: string; created_at: string; size_bytes: number; error_message: string }[];
};

export default function HealthPage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [backups, setBackups] = useState<BackupList | null>(null);
  const [audit, setAudit] = useState<{ created_at: string; action: string; actor: string; entity_type: string; entity_id: string }[]>([]);

  async function load() {
    setHealth(await api<Health>("/api/v1/health"));
    try {
      setBackups(await api<BackupList>("/api/v1/backups"));
    } catch {
      setBackups(null);
    }
    try {
      setAudit(await api("/api/v1/audit"));
    } catch {
      setAudit([]);
    }
  }
  useEffect(() => {
    load().catch((err) => toast.error(err instanceof Error ? err.message : "Failed"));
  }, []);

  const color = (s: string) =>
    s === "healthy" ? "text-emerald-300" : s === "warning" ? "text-amber-300" : "text-red-300";

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>System health</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className={`text-lg font-semibold ${color(health?.status || "")}`}>
            {health?.status || "…"}
          </div>
          {health?.checks.map((c) => (
            <div key={c.name} className="flex justify-between gap-4 rounded-md border border-white/8 p-2 text-sm">
              <span>
                {c.name} · <span className={color(c.status)}>{c.status}</span>
              </span>
              <span className="text-zinc-500">{c.detail}</span>
            </div>
          ))}
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Backups</CardTitle>
          <Button
            onClick={async () => {
              try {
                const row = await api<{ status: string; filename: string }>("/api/v1/backups", { method: "POST" });
                toast.success(row.status === "ok" ? `Wrote ${row.filename}` : "Backup finished with warnings");
                load();
              } catch (err) {
                toast.error(err instanceof Error ? err.message : "Backup failed");
              }
            }}
          >
            Run backup now
          </Button>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p className="text-zinc-400">Last successful: {backups?.last_successful ? new Date(backups.last_successful).toLocaleString() : "none yet"}</p>
          {(backups?.backups || []).map((b) => (
            <div key={b.id} className="flex items-center justify-between">
              <span>
                {b.filename} · {b.status} · {(b.size_bytes / 1024).toFixed(0)} KB
              </span>
              <Button
                size="sm"
                variant="outline"
                onClick={async () => {
                  const { getToken } = await import("@/lib/api");
                  const headers = new Headers();
                  const t = getToken();
                  if (t) headers.set("Authorization", `Bearer ${t}`);
                  const res = await fetch(`/api/v1/backups/${b.id}/download`, { headers });
                  if (!res.ok) {
                    toast.error("Download failed");
                    return;
                  }
                  const blob = await res.blob();
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = b.filename;
                  a.click();
                  URL.revokeObjectURL(url);
                }}
              >
                Download
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={async () => {
                  try {
                    await api(`/api/v1/backups/${b.id}/restore`, { method: "POST" });
                    toast.success("Restore started from backup");
                  } catch (err) {
                    toast.error(err instanceof Error ? err.message : "Restore failed");
                  }
                }}
              >
                Restore
              </Button>
            </div>
          ))}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Audit log</CardTitle>
        </CardHeader>
        <CardContent className="space-y-1 text-xs">
          {audit.slice(0, 40).map((a, i) => (
            <div key={i} className="flex gap-2 text-zinc-400">
              <span className="font-mono">{a.created_at ? new Date(a.created_at).toLocaleString() : ""}</span>
              <span className="text-zinc-200">{a.action}</span>
              <span>
                {a.entity_type} {a.entity_id.slice(0, 8)}
              </span>
              <span>{a.actor}</span>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
