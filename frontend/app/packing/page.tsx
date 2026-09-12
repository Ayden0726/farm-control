"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "sonner";

type Order = { id: string; reference: string; customer_name: string; status: string; packing_status?: string };

export default function PackingListPage() {
  const [orders, setOrders] = useState<Order[]>([]);
  useEffect(() => {
    api<Order[]>("/api/v1/orders")
      .then((rows) =>
        setOrders(rows.filter((o) => !["shipped", "cancelled"].includes(o.status))),
      )
      .catch((err) => toast.error(err instanceof Error ? err.message : "Failed"));
  }, []);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Packing station</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <p className="text-sm text-zinc-400">Scan an ORDER- QR or pick an order. FarmOS checks every BOM line before the order can be marked packed.</p>
        {orders.length === 0 && <p className="text-sm text-zinc-500">No open orders to pack.</p>}
        {orders.map((o) => (
          <div key={o.id} className="flex items-center justify-between rounded-md border border-white/8 p-3 text-sm">
            <div>
              <div className="font-medium">Order {o.reference}</div>
              <div className="text-xs text-zinc-500">
                {o.customer_name} · {o.status} · {o.packing_status || "unpacked"}
              </div>
            </div>
            <Link href={`/packing/${o.id}`} className={buttonVariants()}>
              Open packing
            </Link>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
