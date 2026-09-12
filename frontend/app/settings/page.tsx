"use client";

import { FormEvent, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { PhoneNotificationSettings } from "@/components/phone-notification-settings";

type Settings = {
  company_name: string;
  woocommerce_url: string;
  woocommerce_configured: boolean;
  notify_webhook_configured: boolean;
  simulated_time_scale: number;
  app_version: string;
  update_command: string;
};

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
  const [loadError, setLoadError] = useState<string | null>(null);
  const [update, setUpdate] = useState<UpdateStatus | null>(null);
  const [updating, setUpdating] = useState(false);

  useEffect(() => {
    api<Settings>("/api/v1/settings")
      .then((s) => {
        setSettings(s);
        setCompany(s.company_name);
        setWooUrl(s.woocommerce_url);
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
