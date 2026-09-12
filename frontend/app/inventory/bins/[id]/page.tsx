"use client";

import { FormEvent, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { QrDialog } from "@/components/qr-dialog";

type Bin = {
  id: string;
  name: string;
  location: string;
  part_sku: string | null;
  qr_token: string;
  public_code: string | null;
  quantity_on_hand: number;
  quantity_reserved: number;
  quantity_available: number;
  movements: { id: string; quantity: number; reason: string; notes: string; actor: string; created_at: string }[];
};

export default function BinDetailPage() {
  const params = useParams<{ id: string }>();
  const [bin, setBin] = useState<Bin | null>(null);
  const [bins, setBins] = useState<{ id: string; name: string }[]>([]);
  const [qty, setQty] = useState("1");
  const [count, setCount] = useState("");
  const [toBin, setToBin] = useState("");
  const [notes, setNotes] = useState("");

  async function load() {
    setBin(await api<Bin>(`/api/v1/bins/${params.id}`));
    setBins(await api<{ id: string; name: string }[]>("/api/v1/bins"));
  }
  useEffect(() => {
    load().catch((err) => toast.error(err instanceof Error ? err.message : "Failed to load bin"));
  }, [params.id]);

  if (!bin) return <div className="text-zinc-500">Loading bin…</div>;

  async function adjust(quantity: number, reason: string) {
    try {
      await api(`/api/v1/bins/${params.id}/adjust`, {
        method: "POST",
        body: JSON.stringify({ quantity, reason, notes }),
      });
      toast.success("Bin updated");
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Adjust failed");
    }
  }

  async function stockCount(e: FormEvent) {
    e.preventDefault();
    try {
      await api(`/api/v1/bins/${params.id}/adjust`, {
        method: "POST",
        body: JSON.stringify({ count: Number(count), notes }),
      });
      toast.success("Stock count recorded");
      setCount("");
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Count failed");
    }
  }

  async function move(e: FormEvent) {
    e.preventDefault();
    try {
      await api(`/api/v1/bins/${params.id}/move`, {
        method: "POST",
        body: JSON.stringify({ quantity: Number(qty), to_bin_id: toBin }),
      });
      toast.success("Stock moved");
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Move failed");
    }
  }

  return (
    <div className="space-y-4">
      <Link href="/inventory" className="text-xs text-amber-300 hover:underline">
        Back to inventory
      </Link>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle>{bin.name}</CardTitle>
            <p className="text-sm text-zinc-500">
              {bin.public_code} · {bin.location} · {bin.part_sku || "mixed parts"}
            </p>
          </div>
          <QrDialog kind="bin" token={bin.public_code || bin.qr_token} label={bin.name} />
        </CardHeader>
        <CardContent className="grid gap-3 text-sm md:grid-cols-3">
          <div>
            Physical <div className="font-mono text-2xl">{bin.quantity_on_hand}</div>
          </div>
          <div>
            Reserved <div className="font-mono text-2xl">{bin.quantity_reserved}</div>
          </div>
          <div>
            Available <div className="font-mono text-2xl">{bin.quantity_available}</div>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Adjust / count / move</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Input placeholder="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
          <div className="flex flex-wrap gap-2">
            <Input className="w-24" type="number" value={qty} onChange={(e) => setQty(e.target.value)} />
            <Button onClick={() => adjust(Number(qty), "add")}>Add stock</Button>
            <Button variant="outline" onClick={() => adjust(-Number(qty), "remove")}>
              Remove stock
            </Button>
            <Button variant="outline" onClick={() => adjust(Number(qty) - bin.quantity_on_hand, "correct")}>
              Set to this qty
            </Button>
          </div>
          <form onSubmit={stockCount} className="flex flex-wrap gap-2">
            <div>
              <Label>Stock count</Label>
              <Input value={count} onChange={(e) => setCount(e.target.value)} placeholder="Counted qty" />
            </div>
            <Button type="submit" className="self-end">
              Record count
            </Button>
          </form>
          <form onSubmit={move} className="flex flex-wrap gap-2">
            <select
              className="h-8 rounded-lg border border-input bg-transparent px-2 text-sm"
              value={toBin}
              onChange={(e) => setToBin(e.target.value)}
              required
            >
              <option value="">Move to bin…</option>
              {bins
                .filter((b) => b.id !== bin.id)
                .map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
            </select>
            <Button type="submit">Move available stock</Button>
          </form>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Transaction history</CardTitle>
        </CardHeader>
        <CardContent className="space-y-1 text-xs text-zinc-400">
          {(bin.movements || []).length === 0 && <p>No movements yet.</p>}
          {(bin.movements || []).map((m) => (
            <div key={m.id} className="flex justify-between gap-2">
              <span>
                {m.created_at ? new Date(m.created_at).toLocaleString() : ""} · {m.reason} · {m.quantity > 0 ? "+" : ""}
                {m.quantity}
              </span>
              <span>
                {m.notes} {m.actor}
              </span>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
