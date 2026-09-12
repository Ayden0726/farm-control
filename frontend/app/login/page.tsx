"use client";

import { FormEvent, Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api, apiUrl, AuthUser, setToken } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";

const fieldClass =
  "h-8 w-full min-w-0 rounded-lg border border-input bg-transparent px-2.5 py-1 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30";

function LoginForm() {
  const params = useSearchParams();
  const [busy, setBusy] = useState(false);
  const [needsSetup, setNeedsSetup] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch(apiUrl("/api/v1/setup/status"), { cache: "no-store" })
      .then(async (r) => {
        const data = await r.json().catch(() => null);
        if (!cancelled && data?.needs_setup) {
          setNeedsSetup(true);
          window.location.replace("/setup");
        }
      })
      .catch(() => {
        if (!cancelled) setNeedsSetup(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    const email = String(data.get("email") || "").trim();
    const password = String(data.get("password") || "");
    if (!password) {
      toast.error("Enter your password.");
      return;
    }
    setBusy(true);
    try {
      const res = await api<AuthUser>("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setToken(res.access_token);
      window.location.assign(params.get("next") || "/");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Login failed");
      setBusy(false);
    }
  }

  return (
    <div className="farm-grid flex min-h-screen items-center justify-center p-4">
      <form
        method="post"
        action="/login"
        onSubmit={onSubmit}
        className="w-full max-w-md rounded-2xl border border-white/10 bg-[#121820]/90 p-8 shadow-2xl backdrop-blur"
      >
        <div className="mb-6 flex items-center gap-3">
          <div className="flex size-11 items-center justify-center rounded-lg bg-amber-500 text-lg font-bold text-zinc-950">
            PF
          </div>
          <div>
            <h1 className="text-xl font-semibold">Print FarmOS</h1>
            <p className="text-sm text-muted-foreground">Sign in to the print farm</p>
          </div>
        </div>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="email">Email</Label>
            <input
              id="email"
              name="email"
              type="text"
              inputMode="email"
              autoComplete="username"
              defaultValue="ops@rackkit.local"
              required
              className={fieldClass}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password">Password</Label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              className={fieldClass}
            />
          </div>
          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </Button>
          <p className="text-center text-xs text-zinc-500">
            {needsSetup ? "First-time install — " : "No admin account yet? "}
            <Link href="/setup" className="text-amber-300 hover:underline">
              Open the setup wizard
            </Link>
          </p>
        </div>
      </form>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
