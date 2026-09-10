"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  Bell,
  Boxes,
  ClipboardCheck,
  Factory,
  LayoutDashboard,
  Library,
  LogOut,
  Package,
  Printer,
  Settings,
  ShoppingCart,
  Wrench,
  Menu,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { api, getToken, setToken } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/queue", label: "Print Queue", icon: Factory },
  { href: "/printers", label: "Printers", icon: Printer },
  { href: "/production", label: "Production", icon: ClipboardCheck },
  { href: "/library", label: "G-code Library", icon: Library },
  { href: "/inventory", label: "Inventory & QC", icon: Boxes },
  { href: "/filament", label: "Filament", icon: Package },
  { href: "/orders", label: "Orders", icon: ShoppingCart },
  { href: "/products", label: "Products / BOM", icon: Boxes },
  { href: "/analytics", label: "Analytics", icon: Activity },
  { href: "/maintenance", label: "Maintenance", icon: Wrench },
  { href: "/settings", label: "Settings", icon: Settings },
];

type Note = { id: string; title: string; is_read: boolean; severity: string };

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [notes, setNotes] = useState<Note[]>([]);
  const [open, setOpen] = useState(false);
  const unread = notes.filter((n) => !n.is_read).length;

  useEffect(() => {
    if (!getToken()) return;
    let cancel = false;
    const load = async () => {
      try {
        const rows = await api<Note[]>("/api/v1/notifications?unread_only=true");
        if (!cancel) setNotes(rows);
      } catch {
        /* ignore */
      }
    };
    load();
    const id = setInterval(load, 8000);
    return () => {
      cancel = true;
      clearInterval(id);
    };
  }, [pathname]);

  const title = useMemo(
    () => NAV.find((n) => (n.href === "/" ? pathname === "/" : pathname.startsWith(n.href)))?.label || "FarmOS",
    [pathname],
  );

  function NavList({ onClick }: { onClick?: () => void }) {
    return (
      <nav className="flex flex-col gap-0.5 px-2">
        {NAV.map((item) => {
          const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={onClick}
              className={cn(
                "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors",
                active
                  ? "bg-amber-500/15 text-amber-200"
                  : "text-zinc-400 hover:bg-white/5 hover:text-zinc-100",
              )}
            >
              <Icon className="size-4 shrink-0" />
              {item.label}
            </Link>
          );
        })}
      </nav>
    );
  }

  return (
    <div className="flex min-h-screen bg-background">
      <aside className="hidden w-60 shrink-0 border-r border-white/5 bg-[#0b0f14] lg:flex lg:flex-col">
        <div className="flex items-center gap-2.5 px-4 py-5">
          <div className="flex size-9 items-center justify-center rounded-md bg-amber-500 text-sm font-bold text-zinc-950">
            RK
          </div>
          <div>
            <div className="text-sm font-semibold tracking-wide text-zinc-100">RackKit FarmOS</div>
            <div className="text-[11px] uppercase tracking-[0.18em] text-zinc-500">Print farm control</div>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto pb-4">
          <NavList />
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-3 border-b border-white/5 bg-[#0d1218]/90 px-4 py-3 backdrop-blur">
          <div className="flex items-center gap-2">
            <Sheet open={open} onOpenChange={setOpen}>
              <SheetTrigger
                render={<Button variant="ghost" size="icon" className="lg:hidden" />}
              >
                <Menu className="size-4" />
              </SheetTrigger>
              <SheetContent side="left" className="w-64 bg-[#0b0f14] p-0">
                <div className="px-4 py-5 text-sm font-semibold">RackKit FarmOS</div>
                <NavList onClick={() => setOpen(false)} />
              </SheetContent>
            </Sheet>
            <h1 className="text-base font-semibold text-zinc-100">{title}</h1>
          </div>
          <div className="flex items-center gap-2">
            <Link href="/notifications" className="relative">
              <Button variant="ghost" size="icon">
                <Bell className="size-4" />
              </Button>
              {unread > 0 && (
                <span className="absolute -right-0.5 -top-0.5 flex size-4 items-center justify-center rounded-full bg-amber-500 text-[10px] font-bold text-zinc-950">
                  {unread > 9 ? "9+" : unread}
                </span>
              )}
            </Link>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setToken(null);
                router.push("/login");
              }}
            >
              <LogOut className="size-4" />
              Sign out
            </Button>
          </div>
        </header>
        <main className="flex-1 p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}
