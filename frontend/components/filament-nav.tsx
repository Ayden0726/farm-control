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
    <div className="flex flex-wrap gap-1.5">
      {ITEMS.map((item) => {
        const active = item.href === "/filament" ? pathname === "/filament" : pathname.startsWith(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            className={cn(
              "rounded-full px-3 py-1.5 text-xs font-medium",
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
