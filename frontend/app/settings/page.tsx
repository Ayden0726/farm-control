"use client";

import { FormEvent, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";
import { PhoneNotificationSettings } from "@/components/phone-notification-settings";
import type { FarmSettings } from "@/lib/types";

type Settings = FarmSettings;

type UpdateStatus = {
  available: boolean;
  status: string;
  message: string;
  app_version: string;
  log_tail?: string;
};

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [company, setCompany] = useState("");
  const [wooUrl, setWooUrl] = useState("");
  const [wooKey, setWooKey] = useState("");
  const [wooSecret, setWooSecret] = useState("");
  const [autoEject, setAutoEject] = useState(false);
  const [bedX, setBedX] = useState("220");
  const [bedY, setBedY] = useState("220");
  const [gap, setGap] = useState("8");
  const [savingAutomation, setSavingAutomation] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [update, setUpdate] = useState<UpdateStatus | null>(null);
  const [updating, setUpdating] = useState(false);

  useEffect(() => {
    api<Settings>("/api/v1/settings")
      .then((s) => {
        setSettings(s);
        setCompany(s.company_name);
        setWooUrl(s.woocommerce_url);
        setAutoEject(Boolean(s.auto_part_ejection));
        setBedX(String(s.pack_bed_x_mm ?? 220));
        setBedY(String(s.pack_bed_y_mm ?? 220));
        setGap(String(s.pack_gap_mm ?? 8));
      })
      .catch((err) => setLoadError(err instanceof Error ? err.message : "Failed to load settings"));
  }, []);

  useEffect(() => {
    let cancel = false;
    async function refresh() {
      try {
        const row = await api<UpdateStatus>("/api/v1/system/update");
        if (!cancel) {
          setUpdate(row);
          if (row.status !== "updating") setUpdating(false);
        }
      } catch {
        /* viewer role or server restarting */
      }
    }
    refresh();
    const id = setInterval(refresh, 2500);
    return () => {
      cancel = true;
      clearInterval(id);
    };
  }, []);

  async function save(e: FormEvent) {
    e.preventDefault();
    try {
      const res = await api<Settings>("/api/v1/settings", {
        method: "PUT",
        body: JSON.stringify({
          company_name: company,
          woocommerce_url: wooUrl,
          woocommerce_key: wooKey || undefined,
          woocommerce_secret: wooSecret || undefined,
        }),
      });
      setSettings(res);
      setWooKey("");
      setWooSecret("");
      toast.success("Farm settings saved. WooCommerce keys are never displayed after save.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    }
  }

  async function runUpdate() {
    setUpdating(true);
    try {
      const res = await api<UpdateStatus>("/api/v1/system/update", {
        method: "POST",
        signal: AbortSignal.timeout(15000),
      });
      setUpdate(res);
      toast.success(res.message || "Update started. The site may restart for a few minutes.");
    } catch (err) {
      setUpdating(false);
      const message = err instanceof Error ? err.message : "Could not start update";
      toast.error(message);
      if (err instanceof ApiError && err.howToFix.length) {
        toast.message(err.howToFix[0]);
      }
    }
  }

  if (loadError) {
    return <div className="text-red-300">{loadError}</div>;
  }
  if (!settings) return <div className="text-zinc-500">Loading settings…</div>;

  const busy = updating || update?.status === "updating";

  return (
    <div className="space-y-8">
      <form onSubmit={save} className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Farm</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-1">
              <Label>Company name</Label>
              <Input value={company} onChange={(e) => setCompany(e.target.value)} />
            </div>
            <p className="text-xs text-zinc-500">
              Simulated printers run at {settings.simulated_time_scale}× so the queue is usable without overnight
              waits. Change SIMULATED_TIME_SCALE in .env.
            </p>
            <Button type="submit">Save farm settings</Button>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>WooCommerce</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-xs text-zinc-500">
              Prefer environment variables WOOCOMMERCE_URL / KEY / SECRET on the server. Optional overrides below.
              {settings.woocommerce_configured ? " Env credentials are present." : " Not configured yet."}
            </p>
            <Label>Store URL</Label>
            <Input value={wooUrl} onChange={(e) => setWooUrl(e.target.value)} placeholder="https://shop.example.com" />
            <Label>Consumer key</Label>
            <Input type="password" value={wooKey} onChange={(e) => setWooKey(e.target.value)} />
            <Label>Consumer secret</Label>
            <Input type="password" value={wooSecret} onChange={(e) => setWooSecret(e.target.value)} />
          </CardContent>
        </Card>
      </form>
      <Card>
        <CardHeader>
          <CardTitle>Automation</CardTitle>
          <CardDescription>
            Off by default. Print FarmOS does not drive the nozzle to knock a part off — turn this on only when the
            printer already clears the bed (belt, purge-line knock-off, or a macro you run yourself).
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <label className="flex items-start justify-between gap-4 rounded-lg border border-white/8 bg-white/3 px-3 py-3">
            <div className="space-y-1">
              <div className="text-sm font-medium">Assume the printer removes finished parts</div>
              <p className="text-xs text-zinc-500">
                When on, a successful print leaves the machine idle so the next queued job can start immediately. Failed
                prints still wait for an operator to confirm the bed is empty. Cancelled jobs also still wait.
              </p>
            </div>
            <Switch checked={autoEject} onCheckedChange={setAutoEject} />
          </label>
          <div className="space-y-2">
            <div className="text-sm font-medium">Default plate size (STL estimate)</div>
            <p className="text-xs text-zinc-500">
              Used only to guess how many copies of an uploaded STL fit in a regular grid. Changing this does not slice
              or generate G-code.
            </p>
            <div className="grid grid-cols-3 gap-2">
              <div className="space-y-1">
                <Label>Bed X (mm)</Label>
                <Input inputMode="decimal" value={bedX} onChange={(e) => setBedX(e.target.value)} />
              </div>
              <div className="space-y-1">
                <Label>Bed Y (mm)</Label>
                <Input inputMode="decimal" value={bedY} onChange={(e) => setBedY(e.target.value)} />
              </div>
              <div className="space-y-1">
                <Label>Gap (mm)</Label>
                <Input inputMode="decimal" value={gap} onChange={(e) => setGap(e.target.value)} />
              </div>
            </div>
          </div>
          <Button
            type="button"
            disabled={savingAutomation}
            onClick={async () => {
              setSavingAutomation(true);
              try {
                const res = await api<Settings>("/api/v1/settings", {
                  method: "PUT",
                  body: JSON.stringify({
                    auto_part_ejection: autoEject,
                    pack_bed_x_mm: Number(bedX),
                    pack_bed_y_mm: Number(bedY),
                    pack_gap_mm: Number(gap),
                  }),
                });
                setSettings(res);
                setAutoEject(res.auto_part_ejection);
                setBedX(String(res.pack_bed_x_mm));
                setBedY(String(res.pack_bed_y_mm));
                setGap(String(res.pack_gap_mm));
                toast.success(
                  res.auto_part_ejection
                    ? "Automatic part removal assumed. Successful prints will not wait for bed clear."
                    : "Bed-clear confirmation stays required after each print.",
                );
              } catch (err) {
                toast.error(err instanceof Error ? err.message : "Failed to save automation");
              } finally {
                setSavingAutomation(false);
              }
            }}
          >
            {savingAutomation ? "Saving…" : "Save automation"}
          </Button>
        </CardContent>
      </Card>
      <PhoneNotificationSettings />
      <Card>
        <CardHeader>
          <CardTitle>Application update</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p>
            Running version{" "}
            <span className="font-mono">{update?.app_version || settings.app_version || "dev"}</span>
            {update?.status && update.status !== "unavailable" ? (
              <span className="text-zinc-500"> · {update.status}</span>
            ) : null}
          </p>
          <p className="text-muted-foreground">
            {update?.message ||
              "Pull the latest Print FarmOS from GitHub and rebuild. The database and G-code uploads are kept."}
          </p>
          <Button onClick={runUpdate} disabled={busy || update?.available === false}>
            {busy ? "Updating… this can take several minutes" : "Update Print FarmOS"}
          </Button>
          {update?.available === false && (
            <p className="text-xs text-amber-200">
              One-click update starts after you run <span className="font-mono">./update.sh</span> on the
              server once (Windows: <span className="font-mono">.\update.ps1</span>). Then this button works.
            </p>
          )}
          {update?.log_tail && (busy || update.status === "error") && (
            <pre className="max-h-48 overflow-auto rounded-lg border border-white/10 bg-black/40 p-3 font-mono text-[11px] text-zinc-400">
              {update.log_tail}
            </pre>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
