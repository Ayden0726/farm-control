"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type Hit = { kind: string; id: string; label: string; path: string };

function SearchInner() {
  const params = useSearchParams();
  const router = useRouter();
  const initial = params.get("q") || "";
  const [q, setQ] = useState(initial);
  const [hits, setHits] = useState<Hit[]>([]);

  useEffect(() => {
    const t = setTimeout(async () => {
      if (!q.trim()) {
        setHits([]);
        return;
      }
      const res = await api<{ results: Hit[] }>(`/api/v1/search?q=${encodeURIComponent(q)}`);
      setHits(res.results);
    }, 200);
    return () => clearTimeout(t);
  }, [q]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Search</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <Input className="h-12 text-base md:h-8 md:text-sm" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Order, part, printer, spool, bin, batch, G-code, PO…" autoFocus />
        {hits.map((h) => (
          <button
            key={h.kind + h.id}
            className="block min-h-14 w-full rounded-md border border-white/8 p-3 text-left text-sm hover:bg-white/5"
            onClick={() => router.push(h.path)}
          >
            <span className="text-xs uppercase text-zinc-500">{h.kind}</span>
            <div>{h.label}</div>
          </button>
        ))}
        {q && hits.length === 0 && <p className="text-sm text-zinc-500">No matches.</p>}
      </CardContent>
    </Card>
  );
}

export default function SearchPage() {
  return (
    <Suspense fallback={<div className="text-zinc-500">Search…</div>}>
      <SearchInner />
    </Suspense>
  );
}
