"use client";

import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { QrCode } from "lucide-react";

export function QrDialog({ kind, token, label }: { kind: string; token: string; label: string }) {
  return (
    <Dialog>
      <DialogTrigger render={<Button variant="outline" size="sm" />}>
        <QrCode className="size-3.5" />
        QR
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{label}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col items-center gap-3 py-2">
          <img
            src={`/api/v1/qr/${kind}/${token}`}
            alt={`${label} QR code`}
            className="size-56 rounded-md bg-white p-3"
          />
          <p className="text-center text-xs text-muted-foreground">
            Scan to open this {kind} in FarmOS. Code: {token}
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
}
