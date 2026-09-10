"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, getToken } from "@/lib/api";
import { AppShell } from "@/components/app-shell";

const PUBLIC = new Set(["/login", "/setup"]);

export function Gate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const isPublic = PUBLIC.has(pathname);
  const [ready, setReady] = useState(isPublic);

  useEffect(() => {
    let cancelled = false;
    const timeout = window.setTimeout(() => {
      if (!cancelled) setReady(true);
    }, 4000);

    async function boot() {
      try {
        const status = await api<{ needs_setup: boolean }>("/api/v1/setup/status");
        if (cancelled) return;
        if (status.needs_setup) {
          if (pathname !== "/setup") router.replace("/setup");
          setReady(true);
          return;
        }
        if (!getToken() && !PUBLIC.has(pathname)) {
          router.replace(pathname.startsWith("/scan") ? `/login?next=${encodeURIComponent(pathname)}` : "/login");
          setReady(true);
          return;
        }
        if (getToken() && (pathname === "/login" || pathname === "/setup")) {
          router.replace("/");
        }
        setReady(true);
      } catch {
        if (!cancelled) setReady(true);
      } finally {
        window.clearTimeout(timeout);
      }
    }
    boot();
    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, [pathname, router]);

  if (isPublic) return <>{children}</>;
  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background text-zinc-400">
        Loading FarmOS…
      </div>
    );
  }
  return <AppShell>{children}</AppShell>;
}
