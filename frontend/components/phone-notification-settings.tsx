"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";

type Pref = { event_type: string; label: string; enabled: boolean };

type PrinterEvent = {
  event_type: string;
  label: string;
  global_enabled: boolean;
  override: boolean | null;
  effective: boolean;
};

type PrinterPrefs = {
  printer_id: string;
  printer_name: string;
  events: PrinterEvent[];
};

type PublicField = { name: string; label: string; value: string };
type SecretField = { name: string; label: string; set: boolean };

type Provider = {
  name: string;
  label: string;
  description: string;
  enabled: boolean;
  configured: boolean;
  public_config: Record<string, string>;
  public_fields: PublicField[];
  secret_fields: SecretField[];
};

type ProvidersResponse = {
  public_app_url: string;
  providers: Provider[];
};

function modeOf(event: PrinterEvent): "inherit" | "on" | "off" {
  if (event.override === null) return "inherit";
  return event.override ? "on" : "off";
}

export function PhoneNotificationSettings() {
  const [prefs, setPrefs] = useState<Pref[]>([]);
  const [printers, setPrinters] = useState<PrinterPrefs[]>([]);
  const [selectedPrinter, setSelectedPrinter] = useState<string>("");
  const [providers, setProviders] = useState<Provider[]>([]);
  const [appUrl, setAppUrl] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [savingPrefs, setSavingPrefs] = useState(false);
  const [savingUrl, setSavingUrl] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [secretDraft, setSecretDraft] = useState<Record<string, Record<string, string>>>({});
  const [publicDraft, setPublicDraft] = useState<Record<string, Record<string, string>>>({});

  async function load() {
    setError(null);
    try {
      const [p, pr, prov] = await Promise.all([
        api<Pref[]>("/api/v1/notifications/preferences"),
        api<PrinterPrefs[]>("/api/v1/notifications/preferences/printers"),
        api<ProvidersResponse>("/api/v1/notifications/providers"),
      ]);
      setPrefs(p);
      setPrinters(pr);
      setProviders(prov.providers);
      setAppUrl(prov.public_app_url);
      setPublicDraft(
        Object.fromEntries(
          prov.providers.map((item) => [
            item.name,
            Object.fromEntries(item.public_fields.map((f) => [f.name, f.value])),
          ]),
        ),
      );
      if (!selectedPrinter && pr[0]) setSelectedPrinter(pr[0].printer_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load notification settings.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const currentPrinter = useMemo(
    () => printers.find((p) => p.printer_id === selectedPrinter) || printers[0],
    [printers, selectedPrinter],
  );

  async function savePrefs() {
    setSavingPrefs(true);
    try {
      const next = await api<Pref[]>("/api/v1/notifications/preferences", {
        method: "PUT",
        body: JSON.stringify(prefs.map((p) => ({ event_type: p.event_type, enabled: p.enabled }))),
      });
      setPrefs(next);
      const refreshed = await api<PrinterPrefs[]>("/api/v1/notifications/preferences/printers");
      setPrinters(refreshed);
      toast.success("Event preferences saved.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save preferences.");
    } finally {
      setSavingPrefs(false);
    }
  }

  async function savePrinterEvents() {
    if (!currentPrinter) return;
    try {
      await api(`/api/v1/notifications/preferences/printers/${currentPrinter.printer_id}`, {
        method: "PUT",
        body: JSON.stringify(
          currentPrinter.events.map((ev) => ({
            event_type: ev.event_type,
            enabled: ev.override,
          })),
        ),
      });
      const refreshed = await api<PrinterPrefs[]>("/api/v1/notifications/preferences/printers");
      setPrinters(refreshed);
      toast.success(`${currentPrinter.printer_name} notification overrides saved.`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save printer preferences.");
    }
  }

  async function saveAppUrl(e: FormEvent) {
    e.preventDefault();
    setSavingUrl(true);
    try {
      const res = await api<{ public_app_url: string }>("/api/v1/notifications/app-url", {
        method: "PUT",
        body: JSON.stringify({ public_app_url: appUrl }),
      });
      setAppUrl(res.public_app_url);
      toast.success(
        res.public_app_url
          ? `Phone links and printed QR codes will open ${res.public_app_url}`
          : "Public FarmOS URL cleared.",
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save URL.");
    } finally {
      setSavingUrl(false);
    }
  }

  async function saveProvider(provider: Provider) {
    try {
      const secrets = secretDraft[provider.name] || {};
      const public_config = publicDraft[provider.name] || provider.public_config;
      const updated = await api<Provider>(`/api/v1/notifications/providers/${provider.name}`, {
        method: "PUT",
        body: JSON.stringify({
          enabled: provider.enabled,
          public_config,
          secrets,
        }),
      });
      setProviders((rows) => rows.map((row) => (row.name === updated.name ? updated : row)));
      setSecretDraft((draft) => ({ ...draft, [provider.name]: {} }));
      setPublicDraft((draft) => ({
        ...draft,
        [provider.name]: Object.fromEntries(updated.public_fields.map((f) => [f.name, f.value])),
      }));
      toast.success(`${updated.label} saved. Secrets are stored encrypted and never shown again.`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save provider.");
    }
  }

  async function testProvider(name: string) {
    setTesting(name);
    try {
      const res = await api<{
        deliveries: { provider: string; status: string; error_message: string | null }[];
      }>(`/api/v1/notifications/providers/${name}/test`, { method: "POST" });
      const mine = res.deliveries.find((d) => d.provider === name) || res.deliveries[0];
      if (mine?.status === "sent") {
        toast.success(`Test sent via ${name}. Check your phone.`);
      } else if (mine?.status === "failed") {
        toast.error(mine.error_message || `${name} failed to send.`);
      } else {
        toast.warning(mine?.error_message || `${name} did not send. Configure the provider first.`);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Test failed.");
    } finally {
      setTesting(null);
    }
  }

  if (loading) {
    return <div className="text-zinc-500">Loading phone notification settings…</div>;
  }
  if (error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Phone notifications</CardTitle>
          <CardDescription>{error}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="outline" onClick={() => { setLoading(true); load(); }}>
            Retry
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <div id="phone-notifications" className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-zinc-100">Phone notifications</h2>
        <p className="mt-1 text-sm text-zinc-400">
          FarmOS pushes to your phone through pluggable providers. Start with ntfy (self-hosted or ntfy.sh).
          Tokens and webhook URLs are stored encrypted — they are never shown after save.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>FarmOS URL in notification buttons</CardTitle>
          <CardDescription>
            Print-complete notifications include an Open button. This is the same host as Settings → Public domain.
            Enter example.com to use https://farm.example.com, or a LAN IP / localhost with no farm. prefix. Leave
            blank on a local PC.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={saveAppUrl} className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="min-w-0 flex-1 space-y-1">
              <Label htmlFor="public-app-url">Public FarmOS URL</Label>
              <Input
                id="public-app-url"
                value={appUrl}
                onChange={(e) => setAppUrl(e.target.value)}
                placeholder="example.com or https://farm.example.com"
              />
            </div>
            <Button type="submit" disabled={savingUrl}>
              {savingUrl ? "Saving…" : "Save URL"}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Which events notify</CardTitle>
          <CardDescription>
            Farm-wide defaults. Mute an event here and no printer sends it unless that printer overrides.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-2 sm:grid-cols-2">
            {prefs.map((pref) => (
              <label
                key={pref.event_type}
                className="flex items-center justify-between gap-3 rounded-lg border border-white/8 bg-white/3 px-3 py-2.5"
              >
                <span className="text-sm text-zinc-200">{pref.label}</span>
                <Switch
                  checked={pref.enabled}
                  onCheckedChange={(checked) =>
                    setPrefs((rows) =>
                      rows.map((row) => (row.event_type === pref.event_type ? { ...row, enabled: checked } : row)),
                    )
                  }
                />
              </label>
            ))}
          </div>
          {prefs.length === 0 && <p className="text-sm text-zinc-500">No event types loaded.</p>}
          <Button onClick={savePrefs} disabled={savingPrefs}>
            {savingPrefs ? "Saving…" : "Save event preferences"}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Per-printer overrides</CardTitle>
          <CardDescription>
            Quiet a noisy machine or keep overnight alerts on the K1s only. Inherit uses the farm default above.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {printers.length === 0 ? (
            <p className="text-sm text-zinc-500">Add printers first — then you can mute them individually.</p>
          ) : (
            <>
              <div className="space-y-1">
                <Label htmlFor="notify-printer">Printer</Label>
                <select
                  id="notify-printer"
                  className="h-9 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm dark:bg-input/30"
                  value={currentPrinter?.printer_id || ""}
                  onChange={(e) => setSelectedPrinter(e.target.value)}
                >
                  {printers.map((p) => (
                    <option key={p.printer_id} value={p.printer_id}>
                      {p.printer_name}
                    </option>
                  ))}
                </select>
              </div>
              {currentPrinter && (
                <div className="space-y-2">
                  {currentPrinter.events.map((ev) => (
                    <div
                      key={ev.event_type}
                      className="flex flex-col gap-2 rounded-lg border border-white/8 px-3 py-2 sm:flex-row sm:items-center sm:justify-between"
                    >
                      <div>
                        <div className="text-sm text-zinc-200">{ev.label}</div>
                        <div className="text-[11px] text-zinc-500">
                          Farm default: {ev.global_enabled ? "on" : "off"} · this printer:{" "}
                          {ev.effective ? "will notify" : "muted"}
                        </div>
                      </div>
                      <select
                        className="h-8 rounded-md border border-input bg-transparent px-2 text-xs dark:bg-input/30"
                        value={modeOf(ev)}
                        onChange={(e) => {
                          const mode = e.target.value as "inherit" | "on" | "off";
                          const override = mode === "inherit" ? null : mode === "on";
                          setPrinters((rows) =>
                            rows.map((p) =>
                              p.printer_id !== currentPrinter.printer_id
                                ? p
                                : {
                                    ...p,
                                    events: p.events.map((item) =>
                                      item.event_type === ev.event_type
                                        ? {
                                            ...item,
                                            override,
                                            effective: override === null ? item.global_enabled : override,
                                          }
                                        : item,
                                    ),
                                  },
                            ),
                          );
                        }}
                      >
                        <option value="inherit">Use farm default</option>
                        <option value="on">Notify</option>
                        <option value="off">Mute</option>
                      </select>
                    </div>
                  ))}
                  <Button variant="outline" onClick={savePrinterEvents}>
                    Save {currentPrinter.printer_name} overrides
                  </Button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        {providers.map((provider) => (
          <Card key={provider.name} className={provider.name === "ntfy" ? "lg:col-span-2" : undefined}>
            <CardHeader className="flex flex-row items-start justify-between gap-3">
              <div>
                <CardTitle className="flex items-center gap-2">
                  {provider.label}
                  {provider.name === "ntfy" && (
                    <Badge variant="secondary">Recommended</Badge>
                  )}
                </CardTitle>
                <CardDescription>{provider.description}</CardDescription>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-[11px] uppercase tracking-wide text-zinc-500">
                  {provider.enabled ? "On" : "Off"}
                </span>
                <Switch
                  checked={provider.enabled}
                  onCheckedChange={(checked) =>
                    setProviders((rows) =>
                      rows.map((row) => (row.name === provider.name ? { ...row, enabled: checked } : row)),
                    )
                  }
                />
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              {provider.name === "ntfy" && (
                <p className="rounded-md bg-amber-500/10 px-3 py-2 text-sm text-amber-100/90">
                  Install the ntfy app, create a hard-to-guess topic, subscribe on your phone, then paste the
                  topic here. Use https://ntfy.sh or your own ntfy server. Leave the token blank unless the
                  topic requires auth.
                </p>
              )}
              {provider.public_fields.map((field) => (
                <div key={field.name} className="space-y-1">
                  <Label htmlFor={`${provider.name}-${field.name}`}>{field.label}</Label>
                  <Input
                    id={`${provider.name}-${field.name}`}
                    value={publicDraft[provider.name]?.[field.name] ?? field.value}
                    onChange={(e) =>
                      setPublicDraft((draft) => ({
                        ...draft,
                        [provider.name]: { ...(draft[provider.name] || {}), [field.name]: e.target.value },
                      }))
                    }
                    placeholder={field.name === "server" ? "https://ntfy.sh" : undefined}
                  />
                </div>
              ))}
              {provider.secret_fields.map((field) => (
                <div key={field.name} className="space-y-1">
                  <Label htmlFor={`${provider.name}-${field.name}`}>
                    {field.label}
                    {field.set ? " (saved)" : ""}
                  </Label>
                  <Input
                    id={`${provider.name}-${field.name}`}
                    type="password"
                    autoComplete="off"
                    value={secretDraft[provider.name]?.[field.name] || ""}
                    onChange={(e) =>
                      setSecretDraft((draft) => ({
                        ...draft,
                        [provider.name]: { ...(draft[provider.name] || {}), [field.name]: e.target.value },
                      }))
                    }
                    placeholder={field.set ? "••••••••  leave blank to keep" : "Not stored in git or the browser"}
                  />
                </div>
              ))}
              <div className="flex flex-wrap gap-2">
                <Button onClick={() => saveProvider(provider)}>Save {provider.label}</Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={testing === provider.name}
                  onClick={() => testProvider(provider.name)}
                >
                  {testing === provider.name ? "Sending test…" : "Send test"}
                </Button>
                <Badge variant={provider.configured ? "secondary" : "outline"}>
                  {provider.configured ? "Configured" : "Needs setup"}
                </Badge>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
