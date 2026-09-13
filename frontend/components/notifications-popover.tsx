"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Bell } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover";
import { api, getToken } from "@/lib/api";
import {
  farmNotificationPath,
  relativeNotificationTime,
  type FarmNotification,
} from "@/lib/notifications";
import { cn } from "@/lib/utils";

const PREVIEW_LIMIT = 20;

function severityClass(severity: string) {
  if (severity === "error") return "bg-red-500/15 text-red-200";
  if (severity === "warning") return "bg-amber-500/15 text-amber-200";
  return "bg-white/10 text-zinc-300";
}

export function NotificationsPopover() {
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const [rows, setRows] = useState<FarmNotification[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [markingAll, setMarkingAll] = useState(false);

  useEffect(() => {
    if (!getToken()) return;
    let cancel = false;
    const loadUnread = async () => {
      try {
        const notes = await api<FarmNotification[]>("/api/v1/notifications?unread_only=true");
        if (!cancel) setUnread(notes.length);
      } catch {
        /* badge stays at last known count */
      }
    };
    loadUnread();
    const id = setInterval(loadUnread, 8000);
    return () => {
      cancel = true;
      clearInterval(id);
    };
  }, [pathname]);

  const loadInbox = useCallback(async () => {
    if (!getToken()) return;
    setLoading(true);
    setError(null);
    try {
      const notes = await api<FarmNotification[]>("/api/v1/notifications");
      setRows(notes);
      setUnread(notes.filter((n) => !n.is_read).length);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load notifications.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    void loadInbox();
  }, [open, loadInbox]);

  async function markRead(id: string) {
    await api(`/api/v1/notifications/${id}/read`, { method: "POST" });
    setRows((current) => current?.map((n) => (n.id === id ? { ...n, is_read: true } : n)) ?? null);
    setUnread((count) => Math.max(0, count - 1));
  }

  async function onSelect(note: FarmNotification) {
    if (!note.is_read) {
      try {
        await markRead(note.id);
      } catch {
        /* still follow the deep-link if there is one */
      }
    }
    const href = farmNotificationPath(note);
    setOpen(false);
    if (href) router.push(href);
  }

  async function markAllRead() {
    setMarkingAll(true);
    try {
      await api("/api/v1/notifications/read-all", { method: "POST" });
      setRows((current) => current?.map((n) => ({ ...n, is_read: true })) ?? null);
      setUnread(0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not mark notifications as read.");
    } finally {
      setMarkingAll(false);
    }
  }

  const preview = rows?.slice(0, PREVIEW_LIMIT) ?? [];

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <Button
            variant="ghost"
            size="icon"
            className="relative size-11 overflow-visible lg:size-8"
            aria-label={unread > 0 ? `Notifications, ${unread} unread` : "Notifications"}
          />
        }
      >
        <Bell className="size-5 lg:size-4" />
        {unread > 0 && (
          <span className="absolute right-1 top-1 flex size-4 items-center justify-center rounded-full bg-amber-500 text-[10px] font-bold text-zinc-950 lg:-right-0.5 lg:-top-0.5">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </PopoverTrigger>
      <PopoverContent
        align="end"
        side="bottom"
        collisionPadding={12}
        className="w-[min(22rem,calc(100vw-1.25rem))] gap-0 overflow-hidden p-0"
      >
        <PopoverHeader className="flex flex-row items-start justify-between gap-2 border-b border-white/8 px-3 py-2.5">
          <div className="min-w-0">
            <PopoverTitle className="text-sm text-zinc-100">Notifications</PopoverTitle>
            <PopoverDescription className="text-xs">
              {unread > 0 ? `${unread} unread` : "Farm events stay here so you can keep working."}
            </PopoverDescription>
          </div>
          {unread > 0 && rows && rows.some((n) => !n.is_read) && (
            <Button
              variant="ghost"
              size="xs"
              className="shrink-0 text-amber-200"
              disabled={markingAll}
              onClick={markAllRead}
            >
              {markingAll ? "Marking…" : "Mark all read"}
            </Button>
          )}
        </PopoverHeader>
        <div className="max-h-[min(24rem,calc(100dvh-8rem))] overflow-y-auto">
          {loading && !rows && !error && (
            <p className="px-3 py-8 text-center text-sm text-zinc-500">Loading notifications…</p>
          )}
          {error && (
            <div className="space-y-2 px-3 py-6 text-center">
              <p className="text-sm text-red-200">{error}</p>
              <Button variant="outline" size="sm" onClick={() => void loadInbox()}>
                Try again
              </Button>
            </div>
          )}
          {!error && rows && rows.length === 0 && (
            <p className="px-3 py-8 text-center text-sm text-zinc-500">
              No farm events yet. When a print finishes or a printer drops offline, it lands here.
            </p>
          )}
          {!error &&
            preview.map((note) => {
              const href = farmNotificationPath(note);
              const when = relativeNotificationTime(note.created_at);
              return (
                <button
                  key={note.id}
                  type="button"
                  onClick={() => onSelect(note)}
                  className={cn(
                    "flex w-full flex-col gap-1 border-b border-l-2 border-white/6 px-3 py-2.5 text-left last:border-b-0",
                    note.is_read ? "border-l-transparent opacity-60" : "border-l-amber-400 bg-white/[0.03]",
                    "hover:bg-white/6",
                  )}
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className={cn("text-sm", note.is_read ? "font-normal text-zinc-300" : "font-medium text-zinc-100")}>
                      {note.title}
                    </span>
                    <span className={cn("shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium capitalize", severityClass(note.severity))}>
                      {note.severity || "info"}
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center gap-x-2 text-[11px] text-zinc-500">
                    {when && <span>{when}</span>}
                    {note.printer_name && <span>{note.printer_name}</span>}
                    {href && <span className="text-amber-300/80">Open</span>}
                  </div>
                </button>
              );
            })}
        </div>
        <div className="border-t border-white/8 px-3 py-2">
          <Link
            href="/notifications"
            onClick={() => setOpen(false)}
            className="block text-center text-xs font-medium text-amber-300 hover:underline"
          >
            View all notifications
          </Link>
        </div>
      </PopoverContent>
    </Popover>
  );
}
