"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getToken } from "@/lib/api";
import { AppShell } from "@/components/app-shell";

const PUBLIC = new Set(["/login", "/setup"]);

type SetupStatus = { needs_setup: boolean; company_name?: string | null };

async function readSetupStatus(): Promise<SetupStatus | null> {
  let lastError: unknown;
  for (let attempt = 0; attempt < 4; attempt += 1) {
    try {
      const response = await fetch("/api/v1/setup/status", {
        cache: "no-store",
        signal: AbortSignal.timeout(4000),
      });
      const data = (await response.json().catch(() => null)) as SetupStatus | { detail?: unknown } | null;
      if (response.ok && data && typeof data === "object" && "needs_setup" in data) {
        return { needs_setup: Boolean((data as SetupStatus).needs_setup) };
      }
      lastError = data;
    } catch (err) {
      lastError = err;
    }
    await new Promise((resolve) => setTimeout(resolve, 300 * (attempt + 1)));
  }
  console.warn("setup status unavailable", lastError);
  return null;
}

export function Gate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const isPublic = PUBLIC.has(pathname);
  const [ready, setReady] = useState(isPublic);

  useEffect(() => {
    let cancelled = false;
    async function boot() {
      try {
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
      } finally {
        if (!cancelled) setReady(true);
      }
    }
    boot();
    return () => {
      cancelled = true;
    };
  }, [pathname, router]);

  if (!ready && !isPublic) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-zinc-500">
        Starting Print FarmOS…
      </div>
    );
  }
  if (isPublic) return <>{children}</>;
  return <AppShell>{children}</AppShell>;
}
