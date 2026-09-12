"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { QrDialog } from "@/components/qr-dialog";

type Pack = {
  order_id: string;
  reference: string;
  public_code?: string | null;
  status: string;
  packing_status: string;
  packed_at: string | null;
  packing_override: boolean;
  items: { label: string; kind: string; required_qty: number; confirmed: boolean; missing?: boolean; check_id?: string }[];
  checks: { id: string; label: string; confirmed: boolean; required_qty: number }[];
};

export default function PackingOrderPage() {
  const params = useParams<{ id: string }>();
  const [data, setData] = useState<Pack | null>(null);
  const [notes, setNotes] = useState("");
  const [carrier, setCarrier] = useState("");
  const [tracking, setTracking] = useState("");
  const [cost, setCost] = useState("");

  async function load() {
    setData(await api<Pack>(`/api/v1/packing/${params.id}`));
  }
  useEffect(() => {
    load().catch((err) => toast.error(err instanceof Error ? err.message : "Failed"));
  }, [params.id]);

  if (!data) return <div className="text-zinc-500">Loading packing list…</div>;

  async function confirm(id: string) {
    await api(`/api/v1/packing/${params.id}/confirm/${id}`, { method: "POST", body: JSON.stringify({}) });
    load();
  }

  async function complete(override: boolean) {
    try {
      await api(`/api/v1/packing/${params.id}/complete`, {
        method: "POST",
        body: JSON.stringify({ override, notes }),
      });
      toast.success(override ? "Packed with override" : "Order packed — ready to ship");
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Cannot mark packed");
    }
  }

  async function ship() {
    try {
      await api(`/api/v1/orders/${params.id}/ship`, {
        method: "POST",
        body: JSON.stringify({ carrier, tracking_number: tracking, cost: Number(cost || 0) }),
      });
      toast.success("Shipment recorded");
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Ship failed");
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Order {data.reference}</CardTitle>
          {data.public_code && <QrDialog kind="order" token={data.public_code} label={data.reference} />}
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-zinc-400">
            Status {data.status} · packing {data.packing_status}
            {data.packed_at ? ` · packed ${new Date(data.packed_at).toLocaleString()}` : ""}
          </p>
          {data.checks.map((c) => (
            <div key={c.id} className="flex items-center justify-between rounded-md border border-white/8 p-3 text-sm">
              <div>
                {c.confirmed ? "✓" : "○"} {c.label}
                <span className="ml-2 text-xs text-zinc-500">× {c.required_qty}</span>
              </div>
              {!c.confirmed && (
                <Button size="sm" onClick={() => confirm(c.id)}>
                  Confirm
                </Button>
              )}
            </div>
          ))}
          {data.items?.some((i) => i.missing) && (
            <p className="rounded-md bg-amber-500/10 p-2 text-sm text-amber-200">
              Missing items: {data.items.filter((i) => i.missing).map((i) => i.label).join(", ")}. Mark packed is blocked
              unless you override.
            </p>
          )}
          <Input placeholder="Packing notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => complete(false)}>Mark packed</Button>
            <Button variant="outline" onClick={() => complete(true)}>
              Override missing items
            </Button>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Ship</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2 md:grid-cols-3">
          <Input placeholder="Carrier" value={carrier} onChange={(e) => setCarrier(e.target.value)} />
          <Input placeholder="Tracking number" value={tracking} onChange={(e) => setTracking(e.target.value)} />
          <Input placeholder="Shipping cost" value={cost} onChange={(e) => setCost(e.target.value)} />
          <Button className="md:col-span-3" onClick={ship} disabled={!carrier || !tracking}>
            Record shipment
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
