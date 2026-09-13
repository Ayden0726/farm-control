"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { StatusPill } from "@/components/status-pill";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import { farmNotificationPath, type FarmNotification } from "@/lib/notifications";

type Note = FarmNotification;

type Delivery = {
  id: string;
  notification_id: string;
  created_at: string;
  event: string | null;
  event_label: string;
  title: string;
  printer_name: string | null;
  job_label: string | null;
  provider: string;
  status: string;
  error_message: string | null;
  sent_at: string | null;
  deep_link: string | null;
};

export default function NotificationsPage() {
  const [tab, setTab] = useState<"inbox" | "history">("inbox");
  const [rows, setRows] = useState<Note[] | null>(null);
  const [history, setHistory] = useState<Delivery[] | null>(null);
  const [filter, setFilter] = useState<"all" | "sent" | "failed" | "skipped">("all");
  const [error, setError] = useState<string | null>(null);
  const [clearOpen, setClearOpen] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  async function loadInbox() {
    setRows(await api<Note[]>("/api/v1/notifications"));
  }
  async function loadHistory() {
    const q = filter === "all" ? "" : `?status=${filter}`;
    setHistory(await api<Delivery[]>(`/api/v1/notifications/history${q}`));
  }

  async function refresh() {
    setError(null);
    try {
      if (tab === "inbox") await loadInbox();
      else await loadHistory();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load notifications.");
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, filter]);

  const failedCount = useMemo(
    () => (history || []).filter((d) => d.status === "failed").length,
    [history],
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-zinc-400">
          Inbox is what happened on the farm. Delivery history is what actually reached ntfy, Pushover, or another
          provider — including failures.
        </p>
        <Link href="/settings#phone-notifications" className="text-sm text-amber-300 hover:underline">
          Configure providers
        </Link>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button variant={tab === "inbox" ? "default" : "outline"} onClick={() => setTab("inbox")}>
          Inbox
        </Button>
        <Button variant={tab === "history" ? "default" : "outline"} onClick={() => setTab("history")}>
          Delivery history
        </Button>
        {tab === "inbox" && (
          <>
            <Button
              variant="outline"
              onClick={async () => {
                await api("/api/v1/notifications/read-all", { method: "POST" });
                loadInbox();
              }}
            >
              Mark all read
            </Button>
            {rows && rows.length > 0 && (
              <Button variant="destructive" onClick={() => setClearOpen(true)}>
                Clear inbox
              </Button>
            )}
          </>
        )}
      </div>

      {error && <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">{error}</div>}

      {tab === "inbox" && rows === null && !error && <div className="text-zinc-500">Loading inbox…</div>}
      {tab === "inbox" && rows && rows.length === 0 && (
        <div className="rounded-xl border border-dashed border-white/10 px-4 py-10 text-center text-sm text-zinc-500">
          No events yet. When a print finishes or a printer drops offline, it lands here and is pushed to your phone
          if a provider is enabled.
        </div>
      )}
      {tab === "inbox" &&
        rows?.map((n) => {
          const href = farmNotificationPath(n);
          return (
            <div
              key={n.id}
              className={`rounded-xl border border-white/8 p-4 ${n.is_read ? "opacity-60" : "bg-white/3"}`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="font-medium text-zinc-100">{n.title}</div>
                <StatusPill
                  status={n.severity === "error" ? "failed" : n.severity === "warning" ? "waiting_for_bed_clear" : "queued"}
                />
              </div>
              <p className="mt-1 whitespace-pre-wrap text-sm text-zinc-400">{n.body}</p>
              <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-zinc-500">
                <span>{new Date(n.created_at).toLocaleString()}</span>
                {n.printer_name && <span>Printer: {n.printer_name}</span>}
                {n.job_label && <span>Job: {n.job_label}</span>}
                {n.production_run_name && <span>Run: {n.production_run_name}</span>}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {href && (
                  <Link
                    href={href}
                    className="inline-flex h-7 items-center rounded-lg bg-primary px-2.5 text-[0.8rem] font-medium text-primary-foreground hover:bg-primary/80"
                  >
                    Open in FarmOS
                  </Link>
                )}
                {!n.is_read && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={async () => {
                      await api(`/api/v1/notifications/${n.id}/read`, { method: "POST" });
                      loadInbox();
                    }}
                  >
                    Mark read
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={deletingId === n.id}
                  onClick={async () => {
                    setDeletingId(n.id);
                    try {
                      await api(`/api/v1/notifications/${n.id}`, { method: "DELETE" });
                      toast.success("Notification deleted");
                      await loadInbox();
                    } catch (err) {
                      toast.error(err instanceof Error ? err.message : "Could not delete");
                    } finally {
                      setDeletingId(null);
                    }
                  }}
                >
                  {deletingId === n.id ? "Deleting…" : "Delete"}
                </Button>
              </div>
            </div>
          );
        })}

      {tab === "history" && (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {(["all", "sent", "failed", "skipped"] as const).map((key) => (
              <Button key={key} size="sm" variant={filter === key ? "default" : "outline"} onClick={() => setFilter(key)}>
                {key === "all" ? "All" : key[0].toUpperCase() + key.slice(1)}
              </Button>
            ))}
            {failedCount > 0 && filter === "all" && (
              <Badge variant="destructive">{failedCount} failed</Badge>
            )}
          </div>
          {history === null && !error && <div className="text-zinc-500">Loading delivery history…</div>}
          {history && history.length === 0 && (
            <div className="rounded-xl border border-dashed border-white/10 px-4 py-10 text-center text-sm text-zinc-500">
              No deliveries recorded. Send a test from Settings, or wait for a print to finish.
            </div>
          )}
          {history && history.length > 0 && (
            <div className="overflow-x-auto rounded-xl border border-white/8">
              <table className="w-full min-w-[720px] text-left text-sm">
                <thead className="bg-white/4 text-xs uppercase tracking-wide text-zinc-500">
                  <tr>
                    <th className="px-3 py-2 font-medium">Time</th>
                    <th className="px-3 py-2 font-medium">Event</th>
                    <th className="px-3 py-2 font-medium">Printer</th>
                    <th className="px-3 py-2 font-medium">Job</th>
                    <th className="px-3 py-2 font-medium">Provider</th>
                    <th className="px-3 py-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((d) => (
                    <tr key={d.id} className="border-t border-white/6 align-top">
                      <td className="whitespace-nowrap px-3 py-2 text-zinc-400">
                        {new Date(d.created_at).toLocaleString()}
                      </td>
                      <td className="px-3 py-2">
                        <div className="text-zinc-200">{d.event_label || d.event}</div>
                        <div className="text-xs text-zinc-500">{d.title}</div>
                      </td>
                      <td className="px-3 py-2 text-zinc-300">{d.printer_name || "—"}</td>
                      <td className="px-3 py-2 text-zinc-300">{d.job_label || "—"}</td>
                      <td className="px-3 py-2 text-zinc-300">{d.provider}</td>
                      <td className="px-3 py-2">
                        <Badge
                          variant={
                            d.status === "failed" ? "destructive" : d.status === "sent" ? "secondary" : "outline"
                          }
                          className="capitalize"
                        >
                          {d.status}
                        </Badge>
                        {d.error_message && (
                          <div className="mt-1 max-w-xs text-xs text-red-300/90">{d.error_message}</div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      <Dialog open={clearOpen} onOpenChange={setClearOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Clear the inbox?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-zinc-400">
            This removes every farm event from the inbox and the matching phone delivery history. It does not change
            printer, queue, or production data.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setClearOpen(false)} disabled={clearing}>
              Keep them
            </Button>
            <Button
              variant="destructive"
              disabled={clearing}
              onClick={async () => {
                setClearing(true);
                try {
                  const res = await api<{ count: number }>("/api/v1/notifications/clear", { method: "POST" });
                  toast.success(res.count ? `Deleted ${res.count} notification${res.count === 1 ? "" : "s"}` : "Inbox was already empty");
                  setClearOpen(false);
                  await loadInbox();
                  if (tab === "history") await loadHistory();
                } catch (err) {
                  toast.error(err instanceof Error ? err.message : "Could not clear inbox");
                } finally {
                  setClearing(false);
                }
              }}
            >
              {clearing ? "Clearing…" : "Delete all"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
