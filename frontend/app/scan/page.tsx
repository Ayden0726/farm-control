"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { BarcodeScanner } from "@/components/barcode-scanner";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";

type Hit = {
  kind: string;
  id: string;
  path: string;
  name?: string;
  public_code?: string;
  barcode_id?: string;
  remaining_weight_g?: number;
  manufacturer?: string;
  material?: string;
  color?: string;
};

const ACTIONS = [
  { id: "auto", label: "Scan anything", hint: "FarmOS reads the code prefix and opens the right record" },
  { id: "receive", label: "Receive filament", hint: "Scan a FILT- profile barcode to add new rolls" },
  { id: "assign", label: "Assign spool", hint: "Scan printer QR, then spool QR" },
];

export default function ScanHubPage() {
  const router = useRouter();
  const [action, setAction] = useState<string | null>("auto");
  const [printer, setPrinter] = useState<Hit | null>(null);
  const [confirm, setConfirm] = useState<{ printer: Hit; spool: Hit } | null>(null);

  const onDetect = useCallback(
    async (code: string) => {
      try {
        const hit = await api<Hit>("/api/v1/filament/lookup", {
          method: "POST",
          body: JSON.stringify({ code }),
        });
        if (action === "receive") {
          if (hit.kind !== "product") {
            toast.error("Scan a FarmOS product barcode (FILT-…), not a spool QR.");
            return;
          }
          router.push(`/filament/products/${hit.id}?add=1`);
          return;
        }
        if (action === "assign") {
          if (!printer) {
            if (hit.kind !== "printer") {
              toast.error("Scan the printer QR first.");
              return;
            }
            setPrinter(hit);
            toast.success(`Printer ${hit.name}. Now scan a spool.`);
            return;
          }
          if (hit.kind !== "spool") {
            toast.error("Now scan the spool QR.");
            return;
          }
          setConfirm({ printer, spool: hit });
          return;
        }
        toast.success(`Opened ${hit.kind} ${hit.name || hit.public_code || hit.barcode_id || ""}`);
        router.push(hit.path);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Unknown code");
      }
    },
    [action, printer, router],
  );

  async function assign() {
    if (!confirm) return;
    try {
      const res = await api<{ message: string }>("/api/v1/filament/assign", {
        method: "POST",
        body: JSON.stringify({ printer_id: confirm.printer.id, spool_id: confirm.spool.id }),
      });
      toast.success(res.message);
      router.push(confirm.printer.path);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Assign failed");
    }
  }

  return (
    <div className="mx-auto max-w-lg space-y-4">
      <h2 className="text-2xl font-semibold">SCAN</h2>
      <p className="text-sm text-zinc-400">
        Prefixes route automatically: PRINTER-, SPOOL-, FILT-, BIN-, ORDER-, BATCH-, KIT-, HW-.
      </p>
      <div className="grid gap-2">
        {ACTIONS.map((a) => (
          <Button
            key={a.id}
            className="h-14 flex-col items-start px-4 text-left"
            variant={action === a.id ? "default" : "outline"}
            onClick={() => {
              setAction(a.id);
              setPrinter(null);
              setConfirm(null);
            }}
          >
            <span className="text-base">{a.label}</span>
            <span className="text-xs font-normal text-zinc-500">{a.hint}</span>
          </Button>
        ))}
      </div>
      {action && (
        <div className="space-y-3">
          <div className={confirm ? "hidden" : undefined}>
            {printer && <p className="text-sm text-amber-200">Printer: {printer.name}. Scan the spool.</p>}
            <BarcodeScanner onDetect={onDetect} />
          </div>
        </div>
      )}
      {confirm && (
        <div className="space-y-4 rounded-xl border border-white/10 p-4">
          <h3 className="text-lg font-semibold">
            Assign {confirm.spool.public_code || "spool"} to {confirm.printer.name}?
          </h3>
          <p>
            {confirm.spool.manufacturer} {confirm.spool.material}
            <br />
            {confirm.spool.color}
            <br />
            Estimated remaining: {((confirm.spool.remaining_weight_g || 0) / 1000).toFixed(2)} kg
          </p>
          <div className="flex gap-2">
            <Button className="h-12 flex-1" onClick={assign}>
              Assign
            </Button>
            <Button
              className="h-12 flex-1"
              variant="outline"
              onClick={() => {
                setConfirm(null);
                setPrinter(null);
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
