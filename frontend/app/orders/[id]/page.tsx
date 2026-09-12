"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import type { Order } from "@/lib/types";
import { StatusPill } from "@/components/status-pill";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "sonner";
import Link from "next/link";
import { formatMoney } from "@/lib/format";
import { QrDialog } from "@/components/qr-dialog";

export default function OrderDetailPage() {
  const params = useParams<{ id: string }>();
  const [order, setOrder] = useState<Order | null>(null);
  const [profit, setProfit] = useState<{
    revenue: number;
    estimated_total_cost: number;
    gross_profit: number;
    gross_margin_pct: number;
  } | null>(null);

  async function load() {
    setOrder(await api<Order>(`/api/v1/orders/${params.id}`));
    try {
      setProfit(await api(`/api/v1/costing/orders/${params.id}`));
    } catch {
      setProfit(null);
    }
  }
  useEffect(() => {
    load();
  }, [params.id]);

  if (!order) return <div className="text-zinc-500">Loading order…</div>;

  async function fulfill(ship: boolean) {
    const id = params.id;
    try {
      await api(`/api/v1/orders/${id}/fulfill?ship=${ship}`, { method: "POST" });
      toast.success(ship ? "Marked shipped" : "Marked fulfilled");
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-xl font-semibold">{order.reference}</h2>
          <p className="text-sm text-muted-foreground">
            {order.customer_name} · {order.customer_email} · {order.source}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <StatusPill status={order.status} />
          <Button variant="outline" onClick={() => fulfill(false)}>
            Mark fulfilled
          </Button>
          <Button onClick={() => fulfill(true)}>Mark shipped</Button>
          <Link href={`/packing/${order.id}`}>
            <Button variant="outline">Packing station</Button>
          </Link>
          {order.status !== "shipped" && order.status !== "cancelled" && (
            <Button
              variant="destructive"
              onClick={async () => {
                try {
                  await api(`/api/v1/orders/${params.id}/cancel`, { method: "POST" });
                  toast.success("Order cancelled. Reservations released.");
                  load();
                } catch (err) {
                  toast.error(err instanceof Error ? err.message : "Cancel failed");
                }
              }}
            >
              Cancel order
            </Button>
          )}
          {order.public_code && <QrDialog kind="order" token={order.public_code} label={order.reference} />}
        </div>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Products</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {order.lines.map((l) => (
              <div key={l.product_id}>
                {l.quantity} × {l.product_sku} {l.product_name}
              </div>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Required printed parts</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {order.part_needs.map((n) => (
              <div key={n.part_id} className="flex justify-between">
                <span>{n.part_sku}</span>
                <span className="font-mono">
                  need {n.required_qty} · reserved {n.reserved_qty} · produce {n.to_produce}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
      {profit && (
        <Card>
          <CardHeader>
            <CardTitle>Profitability</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-2 text-sm md:grid-cols-4">
            <div>Revenue {formatMoney(profit.revenue)}</div>
            <div>Est. cost {formatMoney(profit.estimated_total_cost)}</div>
            <div>Gross profit {formatMoney(profit.gross_profit)}</div>
            <div>Margin {profit.gross_margin_pct}%</div>
          </CardContent>
        </Card>
      )}
      {order.notes && <p className="text-sm text-zinc-400">{order.notes}</p>}
    </div>
  );
}
