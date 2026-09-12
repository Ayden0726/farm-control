"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatMoney } from "@/lib/format";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

type PartCost = {
  sku: string;
  name: string;
  filament_cost: number;
  electricity: number;
  failure_allowance: number;
  machine_time: number;
  estimated_cost: number;
};

export default function CostingPage() {
  const [parts, setParts] = useState<PartCost[]>([]);
  const [profit, setProfit] = useState<{
    orders: { reference: string; revenue: number; estimated_total_cost: number; gross_profit: number; gross_margin_pct: number }[];
    by_week: { period: string; revenue: number; cost: number; profit: number }[];
  } | null>(null);

  useEffect(() => {
    api<PartCost[]>("/api/v1/costing/parts").then(setParts).catch(() => undefined);
    api<{
      orders: { reference: string; revenue: number; estimated_total_cost: number; gross_profit: number; gross_margin_pct: number }[];
      by_week: { period: string; revenue: number; cost: number; profit: number }[];
    }>("/api/v1/costing/profitability")
      .then(setProfit)
      .catch(() => undefined);
  }, []);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Cost per part</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Part</TableHead>
                <TableHead>Filament</TableHead>
                <TableHead>Electricity</TableHead>
                <TableHead>Failure</TableHead>
                <TableHead>Machine</TableHead>
                <TableHead>Estimated</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {parts.map((p) => (
                <TableRow key={p.sku}>
                  <TableCell>
                    {p.sku}
                    <div className="text-xs text-zinc-500">{p.name}</div>
                  </TableCell>
                  <TableCell>{formatMoney(p.filament_cost)}</TableCell>
                  <TableCell>{formatMoney(p.electricity)}</TableCell>
                  <TableCell>{formatMoney(p.failure_allowance)}</TableCell>
                  <TableCell>{formatMoney(p.machine_time)}</TableCell>
                  <TableCell>{formatMoney(p.estimated_cost)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Order profitability</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {(profit?.orders || []).map((o) => (
            <div key={o.reference} className="flex justify-between">
              <span>Order {o.reference}</span>
              <span>
                {formatMoney(o.revenue)} · cost {formatMoney(o.estimated_total_cost)} · profit {formatMoney(o.gross_profit)}{" "}
                ({o.gross_margin_pct}%)
              </span>
            </div>
          ))}
          {(profit?.by_week || []).map((w) => (
            <div key={w.period} className="text-zinc-400">
              {w.period}: {formatMoney(w.profit)} profit on {formatMoney(w.revenue)}
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
