"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const ITEMS = [
  { href: "/hardware", label: "Catalog" },
  { href: "/hardware/receive", label: "Receive pcs" },
];

export function HardwareNav() {
  const pathname = usePathname();
  return (
    <div className="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1 [scrollbar-width:none] lg:mx-0 lg:flex-wrap lg:overflow-visible lg:px-0 [&::-webkit-scrollbar]:hidden">
      {ITEMS.map((item) => {
        const active =
          item.href === "/hardware"
            ? pathname === "/hardware" || (pathname.startsWith("/hardware/") && !pathname.startsWith("/hardware/receive"))
            : pathname.startsWith(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            className={cn(
              "shrink-0 rounded-full px-3 py-2.5 text-sm font-medium lg:py-1.5 lg:text-xs",
              active ? "bg-amber-500/20 text-amber-200" : "bg-white/5 text-zinc-400 hover:text-zinc-100",
            )}
          >
            {item.label}
          </Link>
        );
      })}
    </div>
  );
}
