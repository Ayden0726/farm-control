"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, AuthUser, setToken } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { toast } from "sonner";

export default function SetupPage() {
  const router = useRouter();
  const [email, setEmail] = useState("ops@rackkit.local");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("Farm Admin");
  const [company, setCompany] = useState("Print Farm");
  const [demo, setDemo] = useState(true);
  const [busy, setBusy] = useState(false);
  const [apiDown, setApiDown] = useState(false);
  const [alreadyDone, setAlreadyDone] = useState(false);
  const [waitedMs, setWaitedMs] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function check() {
      try {
        const r = await fetch("/api/v1/setup/status", {
          cache: "no-store",
          signal: AbortSignal.timeout(4000),
        });
        const data = await r.json().catch(() => null);
        if (cancelled) return;
        if (!r.ok) {
          setApiDown(true);
          return;
        }
        setApiDown(false);
        if (data && data.needs_setup === false) setAlreadyDone(true);
      } catch {
        if (!cancelled) setApiDown(true);
      }
    }
    check();
    const poll = setInterval(check, 1500);
    const tick = setInterval(() => setWaitedMs((ms) => ms + 1500), 1500);
    return () => {
      cancelled = true;
      clearInterval(poll);
      clearInterval(tick);
    };
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (password.length < 8) {
      toast.error("Password must be at least 8 characters.");
      return;
    }
    setBusy(true);
    try {
      const res = await api<AuthUser>("/api/v1/setup", {
        method: "POST",
        body: JSON.stringify({
          email,
          password,
          full_name: fullName,
          company_name: company,
          load_demo: demo,
        }),
        signal: AbortSignal.timeout(60000),
      });
      setToken(res.access_token);
      toast.success(demo ? "Print FarmOS is ready with demo farm data." : "Print FarmOS is ready.");
      router.replace("/");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Setup failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="farm-grid flex min-h-screen items-center justify-center p-4">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-lg rounded-2xl border border-white/10 bg-[#121820]/90 p-8 shadow-2xl"
      >
        <div className="mb-2 text-[11px] uppercase tracking-[0.2em] text-amber-400">First-run setup</div>
        <h1 className="text-2xl font-semibold">Stand up Print FarmOS</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Create the admin account. Optionally load a simulated Flex Rack 5 farm so you can exercise
          the queue, bed-clear workflow, and dashboard before connecting OctoPrint or Moonraker.
        </p>
        {apiDown && (
          <p className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-200">
            Waiting for the farm API. The UI can appear first; the API usually comes up within a
            minute after Postgres is healthy. This banner clears by itself — no refresh needed.
            {waitedMs >= 120000
              ? " Still down after two minutes — in WSL run: docker compose logs backend"
              : ""}
          </p>
        )}
        {alreadyDone && (
          <p className="mt-4 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-zinc-300">
            An admin account already exists.{" "}
            <Link href="/login" className="text-amber-300 hover:underline">
              Sign in instead
            </Link>
            . To run the wizard again, reset the database with <code>./install.sh --reset</code>.
          </p>
        )}
        <div className="mt-6 space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Company</Label>
              <Input value={company} onChange={(e) => setCompany(e.target.value)} required />
            </div>
            <div className="space-y-1.5">
              <Label>Your name</Label>
              <Input value={fullName} onChange={(e) => setFullName(e.target.value)} required />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>Admin email</Label>
            <Input
              type="text"
              inputMode="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label>Password (min 8 characters)</Label>
            <Input
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={8}
              required
            />
          </div>
          <label className="flex items-start gap-2 rounded-lg border border-white/10 bg-white/5 p-3 text-sm">
            <Checkbox checked={demo} onCheckedChange={(v) => setDemo(Boolean(v))} />
            <span>
              Load demo data — simulated CR-6 Max, K1 Max, K2 Pro, Voron, Flex Rack 5 BOM, queue, and
              orders.
            </span>
          </label>
          <Button type="submit" className="w-full" disabled={busy || alreadyDone || apiDown}>
            {apiDown ? "Waiting for API…" : busy ? "Creating farm…" : "Complete setup"}
          </Button>
        </div>
      </form>
    </div>
  );
}
