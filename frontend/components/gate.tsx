"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { getToken } from "@/lib/api";
import { AppShell } from "@/components/app-shell";

const PUBLIC = new Set(["/login", "/setup"]);

export function Gate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const isPublic = PUBLIC.has(pathname);

  useEffect(() => {
    let cancelled = false;
    async function boot() {
      try {
        const status = await fetch("/api/v1/setup/status", { cache: "no-store" }).then((r) => r.json());
        if (cancelled) return;
        if (status.needs_setup) {
          if (pathname !== "/setup") router.replace("/setup");
          return;
        }
        if (pathname === "/setup") {
          router.replace(getToken() ? "/" : "/login");
          return;
        }
        if (!getToken() && !PUBLIC.has(pathname)) {
          const next = pathname.startsWith("/scan") ? pathname : "";
          router.replace(next ? `/login?next=${encodeURIComponent(next)}` : "/login");
        }
      } catch {
        if (!cancelled && !getToken() && !PUBLIC.has(pathname)) {
          router.replace("/login");
        }
      }
    }
    boot();
    return () => {
      cancelled = true;
    };
  }, [pathname, router]);

  if (isPublic) return <>{children}</>;
  return <AppShell>{children}</AppShell>;
}
