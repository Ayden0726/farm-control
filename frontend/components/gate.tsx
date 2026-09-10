"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, getToken } from "@/lib/api";
import { AppShell } from "@/components/app-shell";

const PUBLIC = new Set(["/login", "/setup"]);

export function Gate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
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
          const next = pathname.startsWith("/scan") ? pathname : "/";
          router.replace(next === "/" ? "/login" : `/login?next=${encodeURIComponent(pathname)}`);
          setReady(true);
          return;
        }
        if (getToken() && (pathname === "/login" || pathname === "/setup")) {
          router.replace("/");
        }
        setReady(true);
      } catch {
        setReady(true);
      }
    }
    boot();
    return () => {
      cancelled = true;
    };
  }, [pathname, router]);

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background text-zinc-400">
        Loading FarmOS…
      </div>
    );
  }

  if (PUBLIC.has(pathname)) return <>{children}</>;
  return <AppShell>{children}</AppShell>;
}
