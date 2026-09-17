"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";
import { PhoneNotificationSettings } from "@/components/phone-notification-settings";
import { ShippingSettingsCard } from "@/components/shipping-settings";
import type { FarmSettings } from "@/lib/types";
import { normalizePublicHost } from "@/lib/public-host";

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
  const [publicDomain, setPublicDomain] = useState("");
  const [savingDomain, setSavingDomain] = useState(false);
  const [wooUrl, setWooUrl] = useState("");
  const [wooKey, setWooKey] = useState("");
  const [wooSecret, setWooSecret] = useState("");
  const [shopifyShop, setShopifyShop] = useState("");
  const [shopifyToken, setShopifyToken] = useState("");
  const [shopifyWebhookSecret, setShopifyWebhookSecret] = useState("");
  const [shopifyApiVersion, setShopifyApiVersion] = useState("2024-10");
  const [autoEject, setAutoEject] = useState(false);
  const [bedX, setBedX] = useState("220");
  const [bedY, setBedY] = useState("220");
  const [gap, setGap] = useState("8");
  const [savingAutomation, setSavingAutomation] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [update, setUpdate] = useState<UpdateStatus | null>(null);
  const [updating, setUpdating] = useState(false);
  const [turningOffDemo, setTurningOffDemo] = useState(false);
  const [mes, setMes] = useState({
    auto_requeue_failed_qc: true,
    electricity_price_per_kwh: "0.32",
    labour_rate_per_hour: "0",
    enable_electricity_cost: true,
    enable_machine_cost: true,
    enable_labour_cost: false,
    enable_failure_cost: true,
    payment_fee_percent: "0",
    overnight_start_hour: "22",
    overnight_end_hour: "7",
    backup_retention_days: "14",
    backup_include_files: false,
    include_camera_in_notifications: false,
  });
  const [users, setUsers] = useState<{ id: string; email: string; full_name: string; role: string; is_active: boolean }[]>([]);

  useEffect(() => {
    api<Settings>("/api/v1/settings")
      .then((s) => {
        setSettings(s);
        setCompany(s.company_name);
        setPublicDomain(s.public_domain || "");
        setWooUrl(s.woocommerce_url);
        setShopifyShop(s.shopify_shop || "");
        setShopifyApiVersion(s.shopify_api_version || "2024-10");
        setAutoEject(Boolean(s.auto_part_ejection));
        setBedX(String(s.pack_bed_x_mm ?? 220));
        setBedY(String(s.pack_bed_y_mm ?? 220));
        setGap(String(s.pack_gap_mm ?? 8));
        setMes({
          auto_requeue_failed_qc: s.auto_requeue_failed_qc !== false,
          electricity_price_per_kwh: String(s.electricity_price_per_kwh ?? 0.32),
          labour_rate_per_hour: String(s.labour_rate_per_hour ?? 0),
          enable_electricity_cost: s.enable_electricity_cost !== false,
          enable_machine_cost: s.enable_machine_cost !== false,
          enable_labour_cost: Boolean(s.enable_labour_cost),
          enable_failure_cost: s.enable_failure_cost !== false,
          payment_fee_percent: String(s.payment_fee_percent ?? 0),
          overnight_start_hour: String(s.overnight_start_hour ?? 22),
          overnight_end_hour: String(s.overnight_end_hour ?? 7),
          backup_retention_days: String(s.backup_retention_days ?? 14),
          backup_include_files: Boolean(s.backup_include_files),
          include_camera_in_notifications: Boolean(s.include_camera_in_notifications),
        });
      })
      .catch((err) => setLoadError(err instanceof Error ? err.message : "Failed to load settings"));
    api<{ id: string; email: string; full_name: string; role: string; is_active: boolean }[]>("/api/v1/users")
      .then(setUsers)
      .catch(() => setUsers([]));
  }, []);

  const domainPreview = useMemo(() => normalizePublicHost(publicDomain), [publicDomain]);

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
          shopify_shop: shopifyShop,
          shopify_access_token: shopifyToken || undefined,
          shopify_webhook_secret: shopifyWebhookSecret || undefined,
          shopify_api_version: shopifyApiVersion || undefined,
        }),
      });
      setSettings(res);
      setWooKey("");
      setWooSecret("");
      setShopifyToken("");
      setShopifyWebhookSecret("");
      setShopifyShop(res.shopify_shop || shopifyShop);
      setShopifyApiVersion(res.shopify_api_version || shopifyApiVersion);
      toast.success("Farm settings saved. Store secrets are never displayed after save.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    }
  }

  async function savePublicDomain(e: FormEvent) {
    e.preventDefault();
    const preview = normalizePublicHost(publicDomain);
    if (preview.error) {
      toast.error(preview.error);
      return;
    }
    setSavingDomain(true);
    try {
      const res = await api<Settings>("/api/v1/settings", {
        method: "PUT",
        body: JSON.stringify({ public_domain: publicDomain.trim() }),
      });
      setSettings(res);
      setPublicDomain(res.public_domain || "");
      toast.success(
        res.public_farm_url
          ? `FarmOS links and printed QR codes will use ${res.public_farm_url}`
          : "Public domain cleared. QR codes stay local until you set a domain.",
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save domain");
    } finally {
      setSavingDomain(false);
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

  async function turnOffDemo() {
    if (
      !window.confirm(
        "Turn off demo mode? Sample Flex Rack 5 data and simulated printers will be deleted, then FarmOS will restart. Your admin login stays.",
      )
    ) {
      return;
    }
    setTurningOffDemo(true);
    try {
      await api<{ ok: boolean; message: string; demo_mode: boolean; simulated_time_scale: number }>(
        "/api/v1/settings/demo-mode",
        {
          method: "POST",
          body: JSON.stringify({ enabled: false }),
          signal: AbortSignal.timeout(60000),
        },
      );
      toast.success("Demo mode is off. FarmOS is restarting…");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not turn off demo mode";
      if (!/failed to fetch|network|abort|502|503|504/i.test(message) && !message.includes("Demo mode is already off")) {
        setTurningOffDemo(false);
        toast.error(message);
        return;
      }
    }
    const started = Date.now();
    let sawDown = false;
    while (Date.now() - started < 180000) {
      await new Promise((r) => setTimeout(r, 2000));
      try {
        const s = await api<Settings>("/api/v1/settings", { signal: AbortSignal.timeout(5000) });
        if (sawDown && !s.demo_mode) {
          window.location.reload();
          return;
        }
        if (!s.demo_mode && s.simulated_time_scale <= 1.01) {
          window.location.reload();
          return;
        }
      } catch {
        sawDown = true;
      }
    }
    window.location.reload();
  }

  if (loadError) {
    return <div className="text-red-300">{loadError}</div>;
  }
  if (!settings) return <div className="text-zinc-500">Loading settings…</div>;

  const busy = updating || update?.status === "updating";

  return (
    <div className="space-y-8">
      <form onSubmit={savePublicDomain}>
        <Card>
          <CardHeader>
            <CardTitle>Public domain</CardTitle>
            <CardDescription>
              Enter your domain (example.com). FarmOS links and printed QR codes will use farm.example.com. Leave blank
              on a local PC.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="public-domain">Public domain</Label>
              <Input
                id="public-domain"
                value={publicDomain}
                onChange={(e) => setPublicDomain(e.target.value)}
                placeholder="example.com"
                autoComplete="off"
                spellCheck={false}
                aria-invalid={Boolean(domainPreview.error)}
                inputMode="url"
              />
            </div>
            {domainPreview.error ? (
              <p className="text-sm text-red-300">{domainPreview.error}</p>
            ) : domainPreview.origin ? (
              <p className="text-sm text-zinc-300">
                Farm URL:{" "}
                <span className="font-mono break-all text-zinc-100">{domainPreview.origin}</span>
              </p>
            ) : (
              <p className="text-sm text-zinc-500">
                Not set — printed QR codes stay as <span className="font-mono">farmos:kind:token</span> and work on
                this PC without a domain.
              </p>
            )}
            <p className="text-xs text-zinc-500">
              This does not create DNS or a certificate. Point an A or CNAME record for{" "}
              <span className="font-mono">farm.yourdomain</span> at this machine or your reverse proxy. Localhost and
              LAN IPs are stored as you typed them, without a farm. prefix. Real domains always use https.
            </p>
            <Button type="submit" disabled={savingDomain || Boolean(domainPreview.error)}>
              {savingDomain ? "Saving…" : "Save public domain"}
            </Button>
          </CardContent>
        </Card>
      </form>
      {settings.demo_mode ? (
        <Card>
          <CardHeader>
            <CardTitle>Demo mode</CardTitle>
            <CardDescription>
              This farm was set up with sample Flex Rack 5 jobs, simulated printers, and sped-up print time.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-zinc-400">
              Turning demo mode off removes that sample farm (simulated printers, the RK-FR5 catalog, demo jobs and
              orders). Your admin account, real printers, and files you uploaded stay. Print time goes back to 1× and
              FarmOS restarts so the change takes effect. The site may be unreachable for about a minute.
            </p>
            <Button type="button" variant="destructive" disabled={turningOffDemo} onClick={turnOffDemo}>
              {turningOffDemo ? "Turning off demo mode and restarting…" : "Turn off demo mode and restart"}
            </Button>
          </CardContent>
        </Card>
      ) : null}
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
              {settings.demo_mode
                ? `Simulated printers run at ${settings.simulated_time_scale}× so the queue is usable without overnight waits. Turn demo mode off above to restart at 1×.`
                : settings.simulated_time_scale > 1
                  ? `Simulated printers run at ${settings.simulated_time_scale}×. Change SIMULATED_TIME_SCALE in .env if you still have simulated machines.`
                  : "Print time runs at wall clock (1×)."}
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
        <Card>
          <CardHeader>
            <CardTitle>Shopify</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-xs text-zinc-500">
              Use Shopify instead of WooCommerce, or run both. Env vars SHOPIFY_SHOP, SHOPIFY_ACCESS_TOKEN, and
              SHOPIFY_WEBHOOK_SECRET win when set. Secrets saved here are encrypted and never shown again.
              {settings.shopify_configured ? " Shopify is configured." : " Not configured yet."}
            </p>
            <Label>Shop</Label>
            <Input
              value={shopifyShop}
              onChange={(e) => setShopifyShop(e.target.value)}
              placeholder="your-store or your-store.myshopify.com"
            />
            <Label>Admin API access token</Label>
            <Input
              type="password"
              value={shopifyToken}
              onChange={(e) => setShopifyToken(e.target.value)}
              placeholder={settings.shopify_configured ? "Saved — leave blank to keep" : "shpat_…"}
            />
            <Label>Webhook signing secret</Label>
            <Input
              type="password"
              value={shopifyWebhookSecret}
              onChange={(e) => setShopifyWebhookSecret(e.target.value)}
              placeholder="Optional, but recommended"
            />
            <Label>API version</Label>
            <Input value={shopifyApiVersion} onChange={(e) => setShopifyApiVersion(e.target.value)} placeholder="2024-10" />
            <p className="text-xs text-zinc-500">
              Custom app scopes: <span className="font-mono">read_orders</span>,{" "}
              <span className="font-mono">write_orders</span>, <span className="font-mono">write_fulfillments</span>.
              Webhook URL:{" "}
              <span className="font-mono break-all">
                {(settings.public_farm_url ||
                  (typeof window !== "undefined" ? window.location.origin : "")) + "/api/v1/shopify/webhook"}
              </span>
              . Topics: <span className="font-mono">orders/create</span>, <span className="font-mono">orders/paid</span>.
              Line items match SKU first, then the Shopify product ID on the product record.
            </p>
            <Button type="submit">Save farm settings</Button>
          </CardContent>
        </Card>
      </form>
      <ShippingSettingsCard />
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
      <Card>
        <CardHeader>
          <CardTitle>Manufacturing</CardTitle>
          <CardDescription>
            Production planner, overnight scheduling metadata, costing, QC reprints, and backups. Overnight rules never
            bypass printer safety systems.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <label className="flex items-start justify-between gap-4 rounded-lg border border-white/8 px-3 py-3">
            <div>
              <div className="text-sm font-medium">Automatically requeue failed QC parts</div>
              <p className="text-xs text-zinc-500">Only the failed quantity is reprinted, not the whole plate.</p>
            </div>
            <Switch
              checked={mes.auto_requeue_failed_qc}
              onCheckedChange={(v) => setMes({ ...mes, auto_requeue_failed_qc: v })}
            />
          </label>
          <label className="flex items-start justify-between gap-4 rounded-lg border border-white/8 px-3 py-3">
            <div>
              <div className="text-sm font-medium">Include camera snapshot in print notifications</div>
              <p className="text-xs text-zinc-500">Fetched server-side. Camera credentials are never sent to the browser.</p>
            </div>
            <Switch
              checked={mes.include_camera_in_notifications}
              onCheckedChange={(v) => setMes({ ...mes, include_camera_in_notifications: v })}
            />
          </label>
          <div className="grid gap-2 md:grid-cols-4">
            <div>
              <Label>Electricity $/kWh</Label>
              <Input
                value={mes.electricity_price_per_kwh}
                onChange={(e) => setMes({ ...mes, electricity_price_per_kwh: e.target.value })}
              />
            </div>
            <div>
              <Label>Labour $/h (optional)</Label>
              <Input value={mes.labour_rate_per_hour} onChange={(e) => setMes({ ...mes, labour_rate_per_hour: e.target.value })} />
            </div>
            <div>
              <Label>Payment fee %</Label>
              <Input value={mes.payment_fee_percent} onChange={(e) => setMes({ ...mes, payment_fee_percent: e.target.value })} />
            </div>
            <div>
              <Label>Backup retention days</Label>
              <Input
                value={mes.backup_retention_days}
                onChange={(e) => setMes({ ...mes, backup_retention_days: e.target.value })}
              />
            </div>
            <div>
              <Label>Overnight start hour</Label>
              <Input value={mes.overnight_start_hour} onChange={(e) => setMes({ ...mes, overnight_start_hour: e.target.value })} />
            </div>
            <div>
              <Label>Overnight end hour</Label>
              <Input value={mes.overnight_end_hour} onChange={(e) => setMes({ ...mes, overnight_end_hour: e.target.value })} />
            </div>
          </div>
          <div className="flex flex-wrap gap-4 text-sm">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={mes.enable_electricity_cost}
                onChange={(e) => setMes({ ...mes, enable_electricity_cost: e.target.checked })}
              />
              Electricity cost
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={mes.enable_machine_cost}
                onChange={(e) => setMes({ ...mes, enable_machine_cost: e.target.checked })}
              />
              Machine time
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={mes.enable_labour_cost}
                onChange={(e) => setMes({ ...mes, enable_labour_cost: e.target.checked })}
              />
              Labour
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={mes.enable_failure_cost}
                onChange={(e) => setMes({ ...mes, enable_failure_cost: e.target.checked })}
              />
              Failure allowance
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={mes.backup_include_files}
                onChange={(e) => setMes({ ...mes, backup_include_files: e.target.checked })}
              />
              Include G-code files in backup
            </label>
          </div>
          <Button
            type="button"
            onClick={async () => {
              try {
                const res = await api<Settings>("/api/v1/settings", {
                  method: "PUT",
                  body: JSON.stringify({
                    auto_requeue_failed_qc: mes.auto_requeue_failed_qc,
                    electricity_price_per_kwh: Number(mes.electricity_price_per_kwh),
                    labour_rate_per_hour: Number(mes.labour_rate_per_hour),
                    enable_electricity_cost: mes.enable_electricity_cost,
                    enable_machine_cost: mes.enable_machine_cost,
                    enable_labour_cost: mes.enable_labour_cost,
                    enable_failure_cost: mes.enable_failure_cost,
                    payment_fee_percent: Number(mes.payment_fee_percent),
                    overnight_start_hour: Number(mes.overnight_start_hour),
                    overnight_end_hour: Number(mes.overnight_end_hour),
                    backup_retention_days: Number(mes.backup_retention_days),
                    backup_include_files: mes.backup_include_files,
                    include_camera_in_notifications: mes.include_camera_in_notifications,
                  }),
                });
                setSettings(res);
                toast.success("Manufacturing settings saved");
              } catch (err) {
                toast.error(err instanceof Error ? err.message : "Failed");
              }
            }}
          >
            Save manufacturing settings
          </Button>
        </CardContent>
      </Card>
      {users.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Operator roles</CardTitle>
            <CardDescription>Permissions are enforced on the API, not only by hiding buttons.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {users.map((u) => (
              <div key={u.id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <span>
                  {u.full_name || u.email} <span className="text-zinc-500">{u.email}</span>
                </span>
                <select
                  className="h-8 rounded-lg border border-input bg-transparent px-2"
                  value={u.role}
                  onChange={async (e) => {
                    await api(`/api/v1/users/${u.id}`, { method: "PATCH", body: JSON.stringify({ role: e.target.value }) });
                    toast.success("Role updated");
                    setUsers((cur) => cur.map((x) => (x.id === u.id ? { ...x, role: e.target.value } : x)));
                  }}
                >
                  {["admin", "operator", "packing", "inventory", "viewer"].map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
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
          <Button onClick={runUpdate} disabled={updating}>
            {updating ? "Updating… this can take several minutes" : "Update Print FarmOS"}
          </Button>
          {update?.status === "unavailable" && !updating && (
            <p className="text-xs text-zinc-500">
              The updater starts with the FarmOS stack. If a click fails, run{" "}
              <span className="font-mono">./update.sh</span> on the server (Windows:{" "}
              <span className="font-mono">.\update.ps1</span>).
            </p>
          )}
          {update?.log_tail && (updating || update.status === "error" || update.status === "ok") && (
            <pre className="max-h-48 overflow-auto rounded-lg border border-white/10 bg-black/40 p-3 font-mono text-[11px] text-zinc-400">
              {update.log_tail}
            </pre>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
