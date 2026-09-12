"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const ITEMS = [
  { href: "/filament", label: "Dashboard" },
  { href: "/filament/products", label: "Profiles" },
  { href: "/filament/receive", label: "Scan receive" },
  { href: "/filament/labels", label: "Inventory Labels" },
  { href: "/filament/purchasing", label: "Purchasing" },
  { href: "/filament/locations", label: "Locations" },
  { href: "/labels", label: "All Labels" },
];

export function FilamentNav() {
  const pathname = usePathname();
  return (
    <div className="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1 [scrollbar-width:none] lg:mx-0 lg:flex-wrap lg:overflow-visible lg:px-0 [&::-webkit-scrollbar]:hidden">
      {ITEMS.map((item) => {
        const active = item.href === "/filament" ? pathname === "/filament" : pathname.startsWith(item.href);
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
