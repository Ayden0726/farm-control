"use client";

import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";

type Settings = {
  company_name: string;
  woocommerce_url: string;
  woocommerce_configured: boolean;
  notify_webhook_configured: boolean;
  simulated_time_scale: number;
};

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [company, setCompany] = useState("");
  const [wooUrl, setWooUrl] = useState("");
  const [wooKey, setWooKey] = useState("");
  const [wooSecret, setWooSecret] = useState("");
  const [webhook, setWebhook] = useState("");

  useEffect(() => {
    api<Settings>("/api/v1/settings").then((s) => {
      setSettings(s);
      setCompany(s.company_name);
      setWooUrl(s.woocommerce_url);
    });
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
          notify_webhook_url: webhook || undefined,
        }),
      });
      setSettings(res);
      setWooKey("");
      setWooSecret("");
      toast.success("Settings saved. WooCommerce keys are never displayed after save.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    }
  }

  if (!settings) return <div className="text-zinc-500">Loading settings…</div>;

  return (
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
            Simulated printers run at {settings.simulated_time_scale}× so the queue is usable without overnight waits.
            Change SIMULATED_TIME_SCALE in .env.
          </p>
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
      <Card className="md:col-span-2">
        <CardHeader>
          <CardTitle>Notifications</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Events are stored in FarmOS. Optional webhook provider posts JSON for SMS or chat bridges. SMTP is
            configured via environment variables.
          </p>
          <Label>Webhook URL</Label>
          <Input value={webhook} onChange={(e) => setWebhook(e.target.value)} placeholder="https://hooks.example/farm" />
          <Button type="submit">Save settings</Button>
        </CardContent>
      </Card>
    </form>
  );
}
