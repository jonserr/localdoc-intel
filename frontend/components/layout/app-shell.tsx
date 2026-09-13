"use client";

import {
  BarChart3,
  Database,
  FileText,
  Home,
  MessageSquareText,
  Moon,
  Settings,
  Upload,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { SafeIcon } from "@/components/ui/safe-icon";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/", label: "Dashboard", icon: Home },
  { href: "/documents", label: "Documents", icon: FileText },
  { href: "/documents/upload", label: "Upload", icon: Upload },
  { href: "/chat", label: "Chat", icon: MessageSquareText },
  { href: "/evaluations", label: "Evaluations", icon: BarChart3 },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [dark, setDark] = useState(false);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

  return (
    <div className="min-h-screen bg-background">
      <aside className="fixed inset-y-0 left-0 hidden w-64 border-r bg-card lg:flex lg:flex-col">
        <div className="flex h-16 items-center gap-3 border-b px-5">
          <div className="flex size-9 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <SafeIcon icon={Database} />
          </div>
          <div className="flex flex-col">
            <span className="text-sm font-semibold">LocalDoc Intel</span>
            <span className="text-xs text-muted-foreground">
              Private RAG workspace
            </span>
          </div>
        </div>
        <nav className="flex flex-1 flex-col gap-1 p-3">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active =
              pathname === item.href ||
              (item.href !== "/" && pathname.startsWith(item.href));
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground",
                  active && "bg-accent text-accent-foreground",
                )}
              >
                <SafeIcon icon={Icon} />
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="border-t p-4">
          <div className="rounded-lg border bg-background p-3">
            <div className="flex items-center gap-2 text-sm font-medium">
              <SafeIcon icon={Zap} />
              Local services
            </div>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              Backend, Redis, and Qdrant are designed to run on your machine.
            </p>
          </div>
        </div>
      </aside>
      <div className="lg:pl-64">
        <header className="sticky top-0 z-10 border-b bg-background/95 backdrop-blur">
          <div className="flex h-16 items-center justify-between px-4 md:px-8">
            <div className="flex flex-col">
              <span className="text-sm font-semibold">LocalDoc Intel</span>
              <span className="text-xs text-muted-foreground">
                Local-first document intelligence
              </span>
            </div>
            <div className="flex items-center gap-3">
              <div className="hidden items-center gap-2 rounded-md border bg-card px-3 py-2 text-xs text-muted-foreground sm:flex">
                <span className="size-2 rounded-full bg-primary" />
                Local API via backend proxy
              </div>
              <Button
                variant="outline"
                size="icon"
                onClick={() => setDark((value) => !value)}
                aria-label="Toggle dark mode"
              >
                <SafeIcon icon={Moon} />
              </Button>
            </div>
          </div>
          <nav className="flex gap-1 overflow-x-auto border-t px-3 py-2 lg:hidden">
            {navItems.map((item) => {
              const Icon = item.icon;
              const active =
                pathname === item.href ||
                (item.href !== "/" && pathname.startsWith(item.href));
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "flex h-9 shrink-0 items-center gap-2 rounded-md px-3 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground",
                    active && "bg-accent text-accent-foreground",
                  )}
                >
                  <SafeIcon icon={Icon} />
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </header>
        <main className="mx-auto flex w-full max-w-7xl flex-col gap-6 p-4 md:p-8">
          {children}
        </main>
      </div>
    </div>
  );
}
