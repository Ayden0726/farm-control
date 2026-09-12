"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "sonner";
import { QrDialog } from "@/components/qr-dialog";

type Kit = {
  id: string;
  public_code: string;
  product_sku: string;
  product_name: string;
  quantity: number;
  status: string;
  lines: { sku: string; name: string; required_qty: number; reserved_qty: number; available_qty: number; kind: string }[];
};

export default function KitDetailPage() {
  const params = useParams<{ id: string }>();
  const [kit, setKit] = useState<Kit | null>(null);

  async function load() {
    setKit(await api<Kit>(`/api/v1/kits/${params.id}`));
  }
  useEffect(() => {
    load().catch((err) => toast.error(err instanceof Error ? err.message : "Kit not found"));
  }, [params.id]);

  if (!kit) return <div className="text-zinc-500">Loading kit…</div>;

  return (
    <div className="space-y-4">
      <Link href="/kits" className="text-xs text-amber-300 hover:underline">
        All kits
      </Link>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>
            {kit.public_code} · {kit.product_sku} × {kit.quantity}
          </CardTitle>
          <QrDialog kind="kit" token={kit.public_code} label={kit.public_code} />
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <div className="text-amber-200">{kit.status === "kit_ready" ? "Kit Ready" : kit.status.replaceAll("_", " ")}</div>
          {kit.lines.map((ln) => (
            <div key={ln.sku + ln.kind} className="flex justify-between">
              <span>
                {ln.kind === "hardware" ? "HW" : "Part"} {ln.sku} {ln.name}
              </span>
              <span>
                {ln.available_qty}/{ln.required_qty} avail · reserved {ln.reserved_qty}
              </span>
            </div>
          ))}
          <div className="flex flex-wrap gap-2 pt-2">
            <Button
              size="sm"
              onClick={async () => {
                try {
                  await api(`/api/v1/kits/${kit.id}/reserve`, { method: "POST" });
                  toast.success("Components reserved");
                  load();
                } catch (err) {
                  toast.error(err instanceof Error ? err.message : "Cannot reserve");
                }
              }}
            >
              Reserve into kit
            </Button>
            <Button size="sm" variant="outline" onClick={async () => { await api(`/api/v1/kits/${kit.id}/status`, { method: "POST", body: JSON.stringify({ status: "assembly" }) }); load(); }}>
              Start assembly
            </Button>
            <Button size="sm" variant="outline" onClick={async () => { await api(`/api/v1/kits/${kit.id}/status`, { method: "POST", body: JSON.stringify({ status: "qc" }) }); load(); }}>
              Kit QC
            </Button>
            <Button size="sm" variant="outline" onClick={async () => { await api(`/api/v1/kits/${kit.id}/status`, { method: "POST", body: JSON.stringify({ status: "ready_to_pack" }) }); load(); }}>
              Ready to pack
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
