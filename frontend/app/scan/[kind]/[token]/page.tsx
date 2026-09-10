"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";

export default function ScanPage() {
  const params = useParams<{ kind: string; token: string }>();
  const router = useRouter();
  useEffect(() => {
    api<{ path: string }>(`/api/v1/scan/${params.kind}/${params.token}`)
      .then((res) => router.replace(res.path))
      .catch(() => router.replace("/"));
  }, [params, router]);
  return <div className="text-zinc-500">Resolving QR code…</div>;
}
