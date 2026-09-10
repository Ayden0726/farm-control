"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatGrams, formatMoney } from "@/lib/format";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

type Analytics = {
  totals: {
    jobs: number;
    completed: number;
    failed: number;
    success_rate: number;
    filament_g: number;
    filament_cost: number;
    print_hours: number;
  };
  jobs_per_printer: {
    name: string;
    completed: number;
    failed: number;
    print_hours: number;
    filament_cost: number;
  }[];
  cost_by_part: { sku: string; parts: number; cost: number; filament_g: number }[];
  output_day: { period: string; parts: number }[];
  completed_today: number;
  completed_week: number;
  completed_month: number;
};

export default function AnalyticsPage() {
  const [data, setData] = useState<Analytics | null>(null);
  useEffect(() => {
    api<Analytics>("/api/v1/analytics").then(setData);
  }, []);
  if (!data) return <div className="text-zinc-500">Loading analytics…</div>;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Success rate</CardTitle>
          </CardHeader>
          <CardContent className="font-mono text-2xl">{data.totals.success_rate}%</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Filament used</CardTitle>
          </CardHeader>
          <CardContent className="font-mono text-2xl">{formatGrams(data.totals.filament_g)}</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Filament cost</CardTitle>
          </CardHeader>
          <CardContent className="font-mono text-2xl">{formatMoney(data.totals.filament_cost)}</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Print hours</CardTitle>
          </CardHeader>
          <CardContent className="font-mono text-2xl">{data.totals.print_hours.toFixed(1)}</CardContent>
        </Card>
      </div>
      <p className="text-sm text-muted-foreground">
        Output {data.completed_today} today · {data.completed_week} this week · {data.completed_month} this month
      </p>
      <Card>
        <CardHeader>
          <CardTitle>Production output by day</CardTitle>
        </CardHeader>
        <CardContent className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data.output_day}>
              <CartesianGrid strokeDasharray="3 3" stroke="#223" />
              <XAxis dataKey="period" stroke="#889" fontSize={11} />
              <YAxis stroke="#889" fontSize={11} />
              <Tooltip />
              <Bar dataKey="parts" fill="#e8a54b" radius={4} />
            </BarChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Jobs per printer</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {data.jobs_per_printer.map((p) => (
              <div key={p.name} className="flex justify-between">
                <span>{p.name}</span>
                <span className="font-mono">
                  {p.completed} ok / {p.failed} fail · {p.print_hours.toFixed(1)} h · {formatMoney(p.filament_cost)}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Cost by part</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {data.cost_by_part.length === 0 && <p className="text-zinc-500">Complete some prints to see cost by SKU.</p>}
            {data.cost_by_part.map((p) => (
              <div key={p.sku} className="flex justify-between">
                <span>{p.sku}</span>
                <span className="font-mono">
                  {p.parts} pcs · {formatGrams(p.filament_g)} · {formatMoney(p.cost)}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
