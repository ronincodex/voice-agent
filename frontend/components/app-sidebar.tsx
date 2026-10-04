"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Phone, PhoneCall, Plus, Settings } from "lucide-react";

import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  icon: typeof Phone;
}

const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Dashboard", icon: Phone },
  { href: "/calls", label: "Calls", icon: PhoneCall },
  { href: "/call/new", label: "New Call", icon: Plus },
  { href: "/config", label: "Agent Config", icon: Settings },
];

/**
 * Fixed left sidebar. Uses usePathname() to highlight the current
 * route, which requires the "use client" directive: usePathname is
 * a React hook and hooks only run in Client Components.
 */
export function AppSidebar() {
  const pathname = usePathname();

  return (
    <aside className="hidden md:flex w-64 flex-col border-r bg-muted/40 p-4">
      <div className="mb-8 px-2">
        <h1 className="text-lg font-semibold tracking-tight">Voice Agent</h1>
        <p className="text-xs text-muted-foreground">IT-Webhut</p>
      </div>
      <nav className="flex flex-col gap-1">
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                active
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
              )}
            >
              <Icon className="h-4 w-4" />
              {label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
