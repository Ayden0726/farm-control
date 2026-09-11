"use client";

import { Button } from "@/components/ui/button";

export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="mx-auto max-w-lg space-y-3 p-6">
      <h2 className="text-xl font-semibold">This page hit an error</h2>
      <p className="text-sm text-zinc-400">{error.message || "Try again from here instead of reloading the whole app."}</p>
      <Button onClick={reset}>Try again</Button>
    </div>
  );
}
