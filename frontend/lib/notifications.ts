export type FarmNotification = {
  id: string;
  type?: string;
  title: string;
  body?: string;
  severity: string;
  is_read: boolean;
  created_at?: string;
  printer_id?: string | null;
  printer_name?: string | null;
  job_id?: string | null;
  job_label?: string | null;
  production_run_id?: string | null;
  production_run_name?: string | null;
  order_id?: string | null;
  order_reference?: string | null;
  deep_link?: string | null;
};

export function farmNotificationPath(
  note: Pick<
    FarmNotification,
    "printer_id" | "order_id" | "production_run_id" | "job_id" | "deep_link"
  >,
): string | null {
  if (note.printer_id) return `/printers/${note.printer_id}`;
  if (note.order_id) return `/orders/${note.order_id}`;
  if (note.production_run_id) return `/production/${note.production_run_id}`;
  if (note.job_id) return "/queue";
  if (note.deep_link) {
    try {
      return new URL(note.deep_link).pathname;
    } catch {
      return note.deep_link;
    }
  }
  return null;
}

export function relativeNotificationTime(iso?: string | null): string | null {
  if (!iso) return null;
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return null;
  const sec = Math.round((Date.now() - then) / 1000);
  if (sec < 45) return "just now";
  if (sec < 90) return "1 min ago";
  if (sec < 3600) return `${Math.floor(sec / 60)} min ago`;
  if (sec < 5400) return "1 hour ago";
  if (sec < 86400) return `${Math.floor(sec / 3600)} hours ago`;
  if (sec < 172800) return "yesterday";
  const days = Math.floor(sec / 86400);
  if (days < 30) return `${days} days ago`;
  return new Date(then).toLocaleDateString();
}
