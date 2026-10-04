"use client";

/**
 * Left-rail navigation for the logged-in dashboard. Active item is
 * derived from the current pathname so the state survives refresh and
 * deep links. Placeholder tabs (History / Saved / Feedback) ship in
 * phase D but route to "coming soon" stubs until phase E/F fill them.
 */
import Link from "@/components/AppLink";
import { usePathname } from "next/navigation";
import { useState } from "react";

interface NavItem {
  href: string;
  label: string;
  /** Shown on the right as a soft badge — usage count, new-key, etc. */
  hint?: string;
  /** Phase D ships the first two; rest are placeholders. */
  placeholder?: boolean;
}

export function Sidebar({
  items,
}: {
  items: NavItem[];
}) {
  const pathname = usePathname();
  const [openFor, setOpenFor] = useState<string | null>(null);
  const expanded = openFor === pathname;
  const activeItem = items.find(item => pathname === item.href ||
    (item.href !== "/dashboard" && pathname.startsWith(`${item.href}/`)));

  return (
    <aside className="w-full shrink-0 border-b border-sage-border bg-white/60 md:w-56 md:border-b-0 md:border-r">
      <button type="button" aria-controls="dashboard-navigation" aria-expanded={expanded}
        onClick={() => setOpenFor(expanded ? null : pathname)}
        className="flex min-h-11 w-full items-center justify-between gap-3 px-4 py-3 text-left text-sm text-sage-ink md:hidden">
        <span>Workspace navigation{activeItem ? ` · ${activeItem.label}` : ""}</span>
        <span aria-hidden="true">{expanded ? "−" : "+"}</span>
      </button>
      {/* Site Header is sticky at ~64px — align the sidebar's sticky
          top to match so it doesn't slip under the header or leave a
          gap. Keep this in lockstep with Header.tsx padding. */}
      <nav id="dashboard-navigation" className={`${expanded ? "flex" : "hidden"} flex-wrap gap-0.5 p-3 text-sm md:sticky md:top-16 md:flex md:flex-col`} aria-label="Dashboard navigation">
        {items.map((item) => {
          const active = item === activeItem;
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              onClick={() => setOpenFor(null)}
              className={[
                "flex items-center justify-between rounded-md px-3 py-2 transition-colors",
                active
                  ? "bg-[rgba(58,125,92,0.12)] font-medium text-accent-deep"
                  : "text-sage-muted hover:bg-[rgba(58,125,92,0.06)] hover:text-accent-deep",
              ].join(" ")}
            >
              <span>{item.label}</span>
              {item.hint ? (
                <span className="rounded-full bg-white px-2 py-0.5 text-xs font-medium text-sage-tertiary ring-1 ring-sage-border">
                  {item.hint}
                </span>
              ) : item.placeholder ? (
                <span className="text-xs font-medium text-slate-400">soon</span>
              ) : null}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
