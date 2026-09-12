"use client";

import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";

export type ShippingAddress = {
  name?: string;
  business_name?: string;
  lines?: string[];
  suburb?: string;
  state?: string;
  postcode?: string;
  phone?: string;
  email?: string;
  country?: string;
};

export type ShippingSettings = {
  configured: boolean;
  sandbox: boolean;
  base_url: string;
  api_key_set: boolean;
  password_set: boolean;
  account_number_set: boolean;
  account_number_hint: string;
  env_override: boolean;
  from_address: ShippingAddress;
  default_service: string;
  last_package: { weight_g: number; length_cm: number; width_cm: number; height_cm: number };
  products: { id: string; name: string }[];
};

const EMPTY_FROM: ShippingAddress = {
  name: "",
  business_name: "",
  lines: [""],
  suburb: "",
  state: "",
  postcode: "",
  phone: "",
  email: "",
  country: "AU",
};

export function ShippingSettingsCard() {
  const [settings, setSettings] = useState<ShippingSettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [password, setPassword] = useState("");
  const [account, setAccount] = useState("");
  const [sandbox, setSandbox] = useState(true);
  const [service, setService] = useState("AUS_PARCEL_REGULAR");
  const [fromAddr, setFromAddr] = useState<ShippingAddress>(EMPTY_FROM);

  useEffect(() => {
    api<ShippingSettings>("/api/v1/shipping/settings")
      .then((row) => {
        setSettings(row);
        setSandbox(row.sandbox);
        setService(row.default_service || "AUS_PARCEL_REGULAR");
        setFromAddr({
          ...EMPTY_FROM,
          ...row.from_address,
          lines: row.from_address?.lines?.length ? row.from_address.lines : [""],
        });
      })
      .catch((err) => setLoadError(err instanceof Error ? err.message : "Could not load shipping settings"));
  }, []);

  function setFrom<K extends keyof ShippingAddress>(key: K, value: ShippingAddress[K]) {
    setFromAddr((cur) => ({ ...cur, [key]: value }));
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const res = await api<ShippingSettings>("/api/v1/shipping/settings", {
        method: "PATCH",
        body: JSON.stringify({
          auspost_api_key: apiKey || undefined,
          auspost_password: password || undefined,
          auspost_account_number: account,
          sandbox,
          default_service: service,
          from_address: {
            ...fromAddr,
            lines: (fromAddr.lines || []).filter((line) => line && line.trim()),
            country: "AU",
          },
        }),
      });
      setSettings(res);
      setApiKey("");
      setPassword("");
      setAccount("");
      setSandbox(res.sandbox);
      setService(res.default_service || service);
      setFromAddr({
        ...EMPTY_FROM,
        ...res.from_address,
        lines: res.from_address?.lines?.length ? res.from_address.lines : [""],
      });
      toast.success("Shipping settings saved. Australia Post secrets are never shown again.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save shipping settings");
    } finally {
      setSaving(false);
    }
  }

  if (loadError) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Australia Post shipping</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-red-300">{loadError}</CardContent>
      </Card>
    );
  }
  if (!settings) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Australia Post shipping</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-zinc-500">Loading shipping settings…</CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Australia Post shipping</CardTitle>
        <CardDescription>
          Official labels use the Australia Post Shipping and Tracking API. Print FarmOS labels still work without an
          account — the Shipping tab never blocks on missing credentials.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={save} className="space-y-4">
          <p className="text-xs text-zinc-500">
            {settings.configured
              ? `Australia Post is configured${settings.sandbox ? " (sandbox / test API)" : " (live API)"}.`
              : "No Australia Post account yet. Operators can still print FarmOS labels from WooCommerce or Shopify addresses."}
            {settings.env_override ? " Environment variables override values saved here." : ""}
          </p>
          <div className="grid gap-3 md:grid-cols-2">
            <div className="space-y-1">
              <Label>API key</Label>
              <Input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={settings.api_key_set ? "Saved — leave blank to keep" : "From the AusPost developer portal"}
                autoComplete="off"
              />
            </div>
            <div className="space-y-1">
              <Label>API password</Label>
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={settings.password_set ? "Saved — leave blank to keep" : "API password, not your login password"}
                autoComplete="off"
              />
            </div>
            <div className="space-y-1">
              <Label>Account number</Label>
              <Input
                value={account}
                onChange={(e) => setAccount(e.target.value)}
                placeholder={settings.account_number_hint || "Charge account / APCN"}
                autoComplete="off"
              />
            </div>
            <div className="space-y-1">
              <Label>Default service</Label>
              <select
                className="h-8 w-full rounded-lg border border-input bg-transparent px-2 text-sm"
                value={service}
                onChange={(e) => setService(e.target.value)}
              >
                {(settings.products || []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <label className="flex items-start justify-between gap-4 rounded-lg border border-white/8 px-3 py-3">
            <div>
              <div className="text-sm font-medium">Use Australia Post sandbox</div>
              <p className="text-xs text-zinc-500">
                Sandbox: digitalapi.auspost.com.au/test/shipping/v1. Live: /shipping/v1. Auth is Basic (API key :
                password) plus an Account-Number header.
              </p>
            </div>
            <Switch checked={sandbox} onCheckedChange={setSandbox} />
          </label>
          <div>
            <div className="mb-2 text-sm font-medium">Ship-from (Australian address)</div>
            <p className="mb-3 text-xs text-zinc-500">
              Printed on FarmOS labels and sent to Australia Post as the sender. Suburb, state code, and a 4-digit
              postcode are required for official labels.
            </p>
            <div className="grid gap-3 md:grid-cols-2">
              <div className="space-y-1">
                <Label>Name</Label>
                <Input value={fromAddr.name || ""} onChange={(e) => setFrom("name", e.target.value)} />
              </div>
              <div className="space-y-1">
                <Label>Business name</Label>
                <Input value={fromAddr.business_name || ""} onChange={(e) => setFrom("business_name", e.target.value)} />
              </div>
              <div className="space-y-1 md:col-span-2">
                <Label>Street</Label>
                <Input
                  value={(fromAddr.lines || [])[0] || ""}
                  onChange={(e) => setFrom("lines", [e.target.value, (fromAddr.lines || [])[1] || ""].filter((v, i) => i === 0 || v))}
                />
              </div>
              <div className="space-y-1 md:col-span-2">
                <Label>Street line 2 (optional)</Label>
                <Input
                  value={(fromAddr.lines || [])[1] || ""}
                  onChange={(e) => setFrom("lines", [(fromAddr.lines || [])[0] || "", e.target.value])}
                />
              </div>
              <div className="space-y-1">
                <Label>Suburb</Label>
                <Input value={fromAddr.suburb || ""} onChange={(e) => setFrom("suburb", e.target.value)} />
              </div>
              <div className="space-y-1">
                <Label>State</Label>
                <select
                  className="h-8 w-full rounded-lg border border-input bg-transparent px-2 text-sm"
                  value={fromAddr.state || ""}
                  onChange={(e) => setFrom("state", e.target.value)}
                >
                  <option value="">Select state</option>
                  {["NSW", "VIC", "QLD", "SA", "WA", "TAS", "NT", "ACT"].map((st) => (
                    <option key={st} value={st}>
                      {st}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1">
                <Label>Postcode</Label>
                <Input
                  inputMode="numeric"
                  maxLength={4}
                  value={fromAddr.postcode || ""}
                  onChange={(e) => setFrom("postcode", e.target.value)}
                  placeholder="3000"
                />
              </div>
              <div className="space-y-1">
                <Label>Phone</Label>
                <Input value={fromAddr.phone || ""} onChange={(e) => setFrom("phone", e.target.value)} />
              </div>
              <div className="space-y-1 md:col-span-2">
                <Label>Email</Label>
                <Input type="email" value={fromAddr.email || ""} onChange={(e) => setFrom("email", e.target.value)} />
              </div>
            </div>
          </div>
          <Button type="submit" disabled={saving}>
            {saving ? "Saving…" : "Save shipping settings"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
