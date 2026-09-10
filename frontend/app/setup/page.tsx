"use client";

import { FormEvent, useState } from "react";
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
  const [company, setCompany] = useState("RackKit");
  const [demo, setDemo] = useState(true);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
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
      });
      setToken(res.access_token);
      toast.success(demo ? "FarmOS is ready with demo farm data." : "FarmOS is ready.");
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
        <h1 className="text-2xl font-semibold">Stand up RackKit FarmOS</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Create the admin account. Optionally load a simulated Flex Rack 5 farm so you can exercise
          the queue, bed-clear workflow, and dashboard before connecting OctoPrint or Moonraker.
        </p>
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
            <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div className="space-y-1.5">
            <Label>Password (min 8 characters)</Label>
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={8} required />
          </div>
          <label className="flex items-start gap-2 rounded-lg border border-white/10 bg-white/5 p-3 text-sm">
            <Checkbox checked={demo} onCheckedChange={(v) => setDemo(Boolean(v))} />
            <span>
              Load demo data — simulated CR-6 Max, K1 Max, K2 Pro, Voron, Flex Rack 5 BOM, queue, and orders.
            </span>
          </label>
          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? "Creating farm…" : "Complete setup"}
          </Button>
        </div>
      </form>
    </div>
  );
}
