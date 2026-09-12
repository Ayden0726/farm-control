"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, apiBlob } from "@/lib/api";
import { buttonVariants } from "@/components/ui/button";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

type Address = {
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

type ShipmentRow = {
  id: string;
  provider: string;
  carrier: string;
  service: string;
  tracking_number: string;
  consignment_id: string;
  status: string;
  has_pdf: boolean;
  created_at: string | null;
};

type ShipOrder = {
  id: string;
  reference: string;
  public_code?: string | null;
  customer_name: string;
  customer_email: string;
  source: string;
  status: string;
  packing_status: string;
  shipping_status: string;
  carrier: string;
  tracking_number: string;
  ready_to_ship: boolean;
  has_address: boolean;
  shipping_address: Address;
  from_address: Address;
  items: string[];
  contents: string;
  suggested_weight_g: number;
  package: { weight_g: number; length_cm: number; width_cm: number; height_cm: number };
  default_service: string;
  shipments: ShipmentRow[];
};

type Catalog = {
  orders: ShipOrder[];
  auspost_configured: boolean;
  sandbox: boolean;
  from_address: Address;
  products: { id: string; name: string; group?: string }[];
  default_service: string;
  last_package: { weight_g: number; length_cm: number; width_cm: number; height_cm: number };
};

const STATES = ["NSW", "VIC", "QLD", "SA", "WA", "TAS", "NT", "ACT"];

function formatAddress(addr?: Address) {
  if (!addr) return "No address on file";
  const lines = [
    addr.name,
    addr.business_name && addr.business_name !== addr.name ? addr.business_name : "",
    ...(addr.lines || []),
    [addr.suburb, addr.state, addr.postcode].filter(Boolean).join(" "),
  ].filter(Boolean);
  return lines.join(", ") || "No address on file";
}

function openHtml(html: string) {
  const w = window.open("", "_blank", "noopener,noreferrer");
  if (!w) {
    toast.error("The browser blocked the print window. Allow pop-ups for Print FarmOS, then try again.");
    return;
  }
  w.document.open();
  w.document.write(html);
  w.document.close();
}

export default function ShippingPage() {
  const [data, setData] = useState<Catalog | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const [service, setService] = useState("AUS_PARCEL_REGULAR");
  const [weight, setWeight] = useState("500");
  const [length, setLength] = useState("20");
  const [width, setWidth] = useState("15");
  const [height, setHeight] = useState("10");
  const [reference, setReference] = useState("");
  const [contents, setContents] = useState("");
  const [page, setPage] = useState<"a6" | "a4">("a6");
  const [toAddr, setToAddr] = useState<Address>({});

  async function load(keepId?: string | null) {
    setLoadError(null);
    try {
      const row = await api<Catalog>("/api/v1/shipping/orders");
      setData(row);
      const id = keepId && row.orders.some((o) => o.id === keepId) ? keepId : row.orders[0]?.id || null;
      setSelectedId(id);
      return row;
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Could not load shippable orders");
      return null;
    }
  }

  useEffect(() => {
    load();
  }, []);

  const selected = useMemo(
    () => data?.orders.find((o) => o.id === selectedId) || null,
    [data, selectedId],
  );

  useEffect(() => {
    if (!selected) return;
    setService(selected.default_service || data?.default_service || "AUS_PARCEL_REGULAR");
    const pkg = selected.package || data?.last_package;
    setWeight(String(Math.round(selected.suggested_weight_g || pkg?.weight_g || 500)));
    setLength(String(pkg?.length_cm ?? 20));
    setWidth(String(pkg?.width_cm ?? 15));
    setHeight(String(pkg?.height_cm ?? 10));
    setReference(selected.reference);
    setContents(selected.contents);
    setToAddr({
      name: selected.shipping_address?.name || selected.customer_name,
      business_name: selected.shipping_address?.business_name || "",
      lines: selected.shipping_address?.lines?.length ? selected.shipping_address.lines : [""],
      suburb: selected.shipping_address?.suburb || "",
      state: selected.shipping_address?.state || "",
      postcode: selected.shipping_address?.postcode || "",
      phone: selected.shipping_address?.phone || "",
      email: selected.shipping_address?.email || selected.customer_email,
      country: "AU",
    });
  }, [selected?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  function payload() {
    if (!selected) return null;
    return {
      order_id: selected.id,
      service,
      weight_g: Number(weight || 500),
      length_cm: Number(length || 20),
      width_cm: Number(width || 15),
      height_cm: Number(height || 10),
      contents,
      reference,
      page,
      to_address: {
        ...toAddr,
        lines: (toAddr.lines || []).filter((line) => line && line.trim()),
        country: "AU",
      },
    };
  }

  async function preview() {
    const body = payload();
    if (!body) return;
    setBusy("preview");
    try {
      const res = await api<{ html: string }>("/api/v1/shipping/preview-label", {
        method: "POST",
        body: JSON.stringify(body),
      });
      openHtml(res.html);
      toast.success("Print FarmOS label ready. Use the browser print dialog, or save as PDF.");
      await load(selected?.id);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not build the FarmOS label");
    } finally {
      setBusy(null);
    }
  }

  async function createAusPost() {
    const body = payload();
    if (!body) return;
    setBusy("auspost");
    try {
      const res = await api<{ message: string; shipment?: ShipmentRow; has_pdf?: boolean }>(
        "/api/v1/shipping/auspost/shipments",
        { method: "POST", body: JSON.stringify(body) },
      );
      toast.success(res.message || "Australia Post label created");
      const catalog = await load(selected?.id);
      if (res.shipment?.id && res.has_pdf) {
        await downloadPdf(res.shipment.id);
      } else if (catalog) {
        /* list refreshed */
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Australia Post could not create the label");
    } finally {
      setBusy(null);
    }
  }

  async function downloadPdf(id: string) {
    try {
      const blob = await apiBlob(`/api/v1/shipping/auspost/labels/${id}`);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `auspost-${id}.pdf`;
      a.click();
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not download the Australia Post PDF");
    }
  }

  if (loadError) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Shipping</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-red-300">{loadError}</p>
          <Button onClick={() => load()}>Try again</Button>
        </CardContent>
      </Card>
    );
  }
  if (!data) {
    return <div className="text-sm text-zinc-500">Loading orders that can ship…</div>;
  }

  const fromMissing = !data.from_address?.suburb || !data.from_address?.postcode;
  const ready = data.orders.filter((o) => o.ready_to_ship);
  const later = data.orders.filter((o) => !o.ready_to_ship);

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-sm text-zinc-400">
            Addresses come from synced WooCommerce and Shopify orders. Print a FarmOS label any time. Official Australia
            Post labels need API credentials in Settings.
          </p>
        </div>
        <Link href="/settings" className={cn(buttonVariants({ variant: "outline" }), "h-11 md:h-8")}>
          Shipping settings
        </Link>
      </div>
      {!data.auspost_configured && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-100">
          Australia Post is not connected. You can still print FarmOS labels from store addresses. Add an API key,
          password, and account number in Settings when you want official consignment labels.
        </div>
      )}
      {data.auspost_configured && fromMissing && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-100">
          Ship-from suburb and postcode are missing. FarmOS labels still print; Australia Post will reject the shipment
          until you save a complete Australian sender address in Settings.
        </div>
      )}
      {data.orders.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>No orders ready to ship</CardTitle>
            <CardDescription>
              Packed and ready-to-ship orders appear here, along with open store orders that still have a delivery
              address. Pack an order on the Packing tab, or sync WooCommerce / Shopify from Orders.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            <Link href="/packing" className={buttonVariants()}>
              Open packing
            </Link>
            <Link href="/orders" className={buttonVariants({ variant: "outline" })}>
              Orders
            </Link>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,20rem)_1fr]">
          <Card>
            <CardHeader>
              <CardTitle>Orders</CardTitle>
              <CardDescription>
                {ready.length} ready to ship
                {later.length ? ` · ${later.length} still in production` : ""}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {data.orders.map((order) => {
                const active = order.id === selectedId;
                return (
                  <button
                    key={order.id}
                    type="button"
                    onClick={() => setSelectedId(order.id)}
                    className={cn(
                      "w-full rounded-md border px-3 py-3 text-left text-sm transition-colors",
                      active
                        ? "border-amber-500/40 bg-amber-500/10"
                        : "border-white/8 hover:bg-white/5",
                    )}
                  >
                    <div className="font-medium">Order {order.reference}</div>
                    <div className="text-xs text-zinc-500">
                      {order.customer_name || "No customer name"} · {order.source}
                    </div>
                    <div className="mt-1 text-xs text-zinc-400">{formatAddress(order.shipping_address)}</div>
                    <div className="mt-1 text-[11px] uppercase tracking-wide text-zinc-500">
                      {order.ready_to_ship ? "Ready to ship" : order.status.replaceAll("_", " ")}
                      {order.tracking_number ? ` · ${order.tracking_number}` : ""}
                    </div>
                  </button>
                );
              })}
            </CardContent>
          </Card>
          {selected ? (
            <Card>
              <CardHeader>
                <CardTitle>Shipment · {selected.reference}</CardTitle>
                <CardDescription>
                  To-address is the store shipping address. Weight defaults from printed-part grams when FarmOS has
                  them; otherwise 500 g. Change the carton size before you create a label.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {!selected.has_address && (
                  <p className="rounded-md bg-amber-500/10 p-2 text-sm text-amber-100">
                    This order has no suburb, state, or postcode from WooCommerce/Shopify. Fill them in below before
                    creating an Australia Post label. The FarmOS label will still print with whatever is here.
                  </p>
                )}
                <div className="grid gap-3 md:grid-cols-2">
                  <div className="space-y-1">
                    <Label>Recipient</Label>
                    <Input value={toAddr.name || ""} onChange={(e) => setToAddr({ ...toAddr, name: e.target.value })} />
                  </div>
                  <div className="space-y-1">
                    <Label>Company</Label>
                    <Input
                      value={toAddr.business_name || ""}
                      onChange={(e) => setToAddr({ ...toAddr, business_name: e.target.value })}
                    />
                  </div>
                  <div className="space-y-1 md:col-span-2">
                    <Label>Street</Label>
                    <Input
                      value={(toAddr.lines || [])[0] || ""}
                      onChange={(e) =>
                        setToAddr({ ...toAddr, lines: [e.target.value, (toAddr.lines || [])[1] || ""] })
                      }
                    />
                  </div>
                  <div className="space-y-1">
                    <Label>Suburb</Label>
                    <Input value={toAddr.suburb || ""} onChange={(e) => setToAddr({ ...toAddr, suburb: e.target.value })} />
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div className="space-y-1">
                      <Label>State</Label>
                      <select
                        className="h-8 w-full rounded-lg border border-input bg-transparent px-2 text-sm"
                        value={toAddr.state || ""}
                        onChange={(e) => setToAddr({ ...toAddr, state: e.target.value })}
                      >
                        <option value="">State</option>
                        {STATES.map((st) => (
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
                        value={toAddr.postcode || ""}
                        onChange={(e) => setToAddr({ ...toAddr, postcode: e.target.value })}
                      />
                    </div>
                  </div>
                  <div className="space-y-1">
                    <Label>Phone</Label>
                    <Input value={toAddr.phone || ""} onChange={(e) => setToAddr({ ...toAddr, phone: e.target.value })} />
                  </div>
                  <div className="space-y-1">
                    <Label>Email</Label>
                    <Input value={toAddr.email || ""} onChange={(e) => setToAddr({ ...toAddr, email: e.target.value })} />
                  </div>
                </div>
                <div className="rounded-md border border-white/8 p-3 text-xs text-zinc-400">
                  <div className="mb-1 font-medium text-zinc-300">Ship from</div>
                  {formatAddress(data.from_address)} ·{" "}
                  <Link href="/settings" className="text-amber-200 hover:underline">
                    Edit in Settings
                  </Link>
                </div>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <div className="space-y-1 sm:col-span-2">
                    <Label>Service</Label>
                    <select
                      className="h-8 w-full rounded-lg border border-input bg-transparent px-2 text-sm"
                      value={service}
                      onChange={(e) => setService(e.target.value)}
                    >
                      {(data.products || []).map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="space-y-1">
                    <Label>Order reference</Label>
                    <Input value={reference} onChange={(e) => setReference(e.target.value)} />
                  </div>
                  <div className="space-y-1">
                    <Label>Weight (g)</Label>
                    <Input inputMode="decimal" value={weight} onChange={(e) => setWeight(e.target.value)} />
                  </div>
                  <div className="space-y-1">
                    <Label>Length (cm)</Label>
                    <Input inputMode="decimal" value={length} onChange={(e) => setLength(e.target.value)} />
                  </div>
                  <div className="space-y-1">
                    <Label>Width (cm)</Label>
                    <Input inputMode="decimal" value={width} onChange={(e) => setWidth(e.target.value)} />
                  </div>
                  <div className="space-y-1">
                    <Label>Height (cm)</Label>
                    <Input inputMode="decimal" value={height} onChange={(e) => setHeight(e.target.value)} />
                  </div>
                </div>
                <div className="space-y-1">
                  <Label>Contents</Label>
                  <Textarea value={contents} onChange={(e) => setContents(e.target.value)} rows={2} />
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant={page === "a6" ? "default" : "outline"}
                    onClick={() => setPage("a6")}
                  >
                    A6 label
                  </Button>
                  <Button
                    type="button"
                    variant={page === "a4" ? "default" : "outline"}
                    onClick={() => setPage("a4")}
                  >
                    A4 page
                  </Button>
                </div>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <Button className="h-12 flex-1" onClick={preview} disabled={busy !== null}>
                    {busy === "preview" ? "Preparing label…" : "Preview / print FarmOS label"}
                  </Button>
                  <Button
                    className="h-12 flex-1"
                    variant="outline"
                    onClick={createAusPost}
                    disabled={busy !== null || !data.auspost_configured}
                    title={
                      data.auspost_configured
                        ? "Create an official Australia Post consignment and label PDF"
                        : "Add Australia Post credentials in Settings first"
                    }
                  >
                    {busy === "auspost"
                      ? "Creating Australia Post label…"
                      : data.auspost_configured
                        ? "Create Australia Post label"
                        : "Australia Post not configured"}
                  </Button>
                </div>
                {selected.items.length > 0 && (
                  <ul className="list-disc pl-5 text-sm text-zinc-400">
                    {selected.items.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                )}
                {selected.shipments.length > 0 && (
                  <div className="space-y-2">
                    <div className="text-sm font-medium">Labels created</div>
                    {selected.shipments.map((ship) => (
                      <div
                        key={ship.id}
                        className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-white/8 p-3 text-sm"
                      >
                        <div>
                          <div>
                            {ship.carrier || ship.provider} · {ship.status.replaceAll("_", " ")}
                          </div>
                          <div className="text-xs text-zinc-500">
                            {ship.tracking_number
                              ? `Tracking ${ship.tracking_number}`
                              : ship.provider === "farmos_print"
                                ? "FarmOS print label — no carrier tracking"
                                : "No tracking yet"}
                            {ship.created_at ? ` · ${new Date(ship.created_at).toLocaleString()}` : ""}
                          </div>
                        </div>
                        {ship.has_pdf && (
                          <Button size="sm" variant="outline" onClick={() => downloadPdf(ship.id)}>
                            Download PDF
                          </Button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          ) : null}
        </div>
      )}
    </div>
  );
}
