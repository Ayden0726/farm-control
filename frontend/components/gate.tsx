"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { getToken } from "@/lib/api";
import { AppShell } from "@/components/app-shell";

const PUBLIC = new Set(["/login", "/setup"]);

type SetupStatus = { needs_setup: boolean };

async function readSetupStatus(): Promise<SetupStatus | null> {
  try {
    const response = await fetch("/api/v1/setup/status", {
      cache: "no-store",
      signal: AbortSignal.timeout(8000),
    });
    const data = (await response.json().catch(() => null)) as SetupStatus | null;
    if (response.ok && data && typeof data === "object" && "needs_setup" in data) {
      return { needs_setup: Boolean(data.needs_setup) };
    }
  } catch (err) {
    console.warn("setup status unavailable", err);
  }
  return null;
}

export function Gate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const isPublic = PUBLIC.has(pathname);

  useEffect(() => {
    let cancelled = false;
    async function boot() {
      const status = await readSetupStatus();
      if (cancelled) return;
      const needsSetup = status ? status.needs_setup : !getToken();
      if (needsSetup) {
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
    }
    boot();
    return () => {
      cancelled = true;
    };
  }, [pathname, router]);

  if (isPublic) return <>{children}</>;
  return <AppShell>{children}</AppShell>;
}
