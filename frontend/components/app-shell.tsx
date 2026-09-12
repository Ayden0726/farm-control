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
  HeartPulse,
  LayoutDashboard,
  Library,
  LogOut,
  Package,
  Printer,
  ScanLine,
  Search,
  Settings,
  ShoppingCart,
  Wrench,
  Menu,
  CalendarClock,
  PackageCheck,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, getToken, setToken } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/planner", label: "Planner", icon: CalendarClock },
  { href: "/timeline", label: "Timeline", icon: CalendarClock },
  { href: "/queue", label: "Print Queue", icon: Factory },
  { href: "/printers", label: "Printers", icon: Printer },
  { href: "/production", label: "Production", icon: ClipboardCheck },
  { href: "/library", label: "G-code Library", icon: Library },
  { href: "/inventory", label: "Inventory & QC", icon: Boxes },
  { href: "/hardware", label: "Hardware", icon: Package },
  { href: "/kits", label: "Kitting", icon: PackageCheck },
  { href: "/packing", label: "Packing", icon: PackageCheck },
  { href: "/filament", label: "Filament", icon: Package },
  { href: "/scan", label: "Scan", icon: ScanLine },
  { href: "/orders", label: "Orders", icon: ShoppingCart },
  { href: "/products", label: "Products / BOM", icon: Boxes },
  { href: "/analytics", label: "Analytics", icon: Activity },
  { href: "/costing", label: "Costing", icon: Activity },
  { href: "/maintenance", label: "Maintenance", icon: Wrench },
  { href: "/health", label: "System health", icon: HeartPulse },
  { href: "/notifications", label: "Notifications", icon: Bell },
  { href: "/settings", label: "Settings", icon: Settings },
];

const MOBILE_TABS = [
  { href: "/scan", label: "Scan", icon: ScanLine },
  { href: "/queue", label: "Queue", icon: Factory },
  { href: "/printers", label: "Printers", icon: Printer },
  { href: "/inventory", label: "QC", icon: ClipboardCheck },
  { href: "/filament", label: "Filament", icon: Package },
];

type Note = { id: string; title: string; is_read: boolean; severity: string };

function pathActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

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
    () => NAV.find((n) => pathActive(pathname, n.href))?.label || "FarmOS",
    [pathname],
  );

  function NavList({ onClick }: { onClick?: () => void }) {
    return (
      <nav className="flex flex-col gap-0.5 px-2">
        {NAV.map((item) => {
          const active = pathActive(pathname, item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={onClick}
              className={cn(
                "flex min-h-11 items-center gap-2.5 rounded-md px-3 py-2.5 text-sm transition-colors lg:min-h-0 lg:py-2",
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
    <div className="flex min-h-dvh bg-background">
      <aside className="hidden w-60 shrink-0 border-r border-white/5 bg-[#0b0f14] lg:flex lg:flex-col">
        <div className="flex items-center gap-2.5 px-4 py-5">
          <div className="flex size-9 items-center justify-center rounded-md bg-amber-500 text-sm font-bold text-zinc-950">
            PF
          </div>
          <div>
            <div className="text-sm font-semibold tracking-wide text-zinc-100">Print FarmOS</div>
            <div className="text-[11px] uppercase tracking-[0.18em] text-zinc-500">Print farm control</div>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto pb-4">
          <NavList />
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-40 flex items-center justify-between gap-2 border-b border-white/5 bg-[#0d1218]/90 px-3 py-2 backdrop-blur pt-[max(0.5rem,env(safe-area-inset-top))] md:px-4 md:py-3">
          <div className="flex min-w-0 items-center gap-2">
            <Sheet open={open} onOpenChange={setOpen}>
              <SheetTrigger
                render={<Button variant="ghost" size="icon" className="size-11 lg:hidden" />}
              >
                <Menu className="size-5" />
              </SheetTrigger>
              <SheetContent side="left" className="w-[min(18rem,90vw)] bg-[#0b0f14] p-0">
                <div className="px-4 py-5 text-sm font-semibold">Print FarmOS</div>
                <div className="overflow-y-auto pb-8">
                  <NavList onClick={() => setOpen(false)} />
                </div>
              </SheetContent>
            </Sheet>
            <h1 className="truncate text-base font-semibold text-zinc-100">{title}</h1>
          </div>
          <div className="flex shrink-0 items-center gap-1 md:gap-2">
            <form
              className="hidden md:block"
              onSubmit={(e) => {
                e.preventDefault();
                const q = (e.currentTarget.elements.namedItem("q") as HTMLInputElement)?.value;
                if (q) router.push(`/search?q=${encodeURIComponent(q)}`);
              }}
            >
              <div className="relative">
                <Search className="absolute left-2 top-2 size-3.5 text-zinc-500" />
                <Input name="q" placeholder="Search orders, parts, bins…" className="h-8 w-52 pl-7 text-xs" />
              </div>
            </form>
            <Link href="/search" className="md:hidden">
              <Button variant="ghost" size="icon" className="size-11">
                <Search className="size-5" />
              </Button>
            </Link>
            <Link href="/notifications" className="relative">
              <Button variant="ghost" size="icon" className="size-11 lg:size-8">
                <Bell className="size-5 lg:size-4" />
              </Button>
              {unread > 0 && (
                <span className="absolute right-1 top-1 flex size-4 items-center justify-center rounded-full bg-amber-500 text-[10px] font-bold text-zinc-950 lg:-right-0.5 lg:-top-0.5">
                  {unread > 9 ? "9+" : unread}
                </span>
              )}
            </Link>
            <Button
              variant="ghost"
              size="icon"
              className="size-11 lg:h-8 lg:w-auto lg:px-2.5"
              onClick={() => {
                setToken(null);
                router.push("/login");
              }}
            >
              <LogOut className="size-5 lg:size-4" />
              <span className="hidden lg:inline">Sign out</span>
            </Button>
          </div>
        </header>
        <main className="flex-1 overflow-x-hidden p-4 pb-[calc(5.5rem+env(safe-area-inset-bottom))] md:px-6 md:pt-6 lg:pb-6">
          {children}
        </main>
        <nav className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t border-white/10 bg-[#0d1218]/95 pb-[max(0.4rem,env(safe-area-inset-bottom))] pt-1 backdrop-blur lg:hidden">
          {MOBILE_TABS.map((tab) => {
            const Icon = tab.icon;
            const active = pathActive(pathname, tab.href);
            return (
              <Link
                key={tab.href}
                href={tab.href}
                className={cn(
                  "flex min-h-12 flex-col items-center justify-center gap-0.5 text-[11px] font-medium",
                  active ? "text-amber-200" : "text-zinc-500",
                )}
              >
                <Icon className="size-5" />
                {tab.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </div>
  );
}
