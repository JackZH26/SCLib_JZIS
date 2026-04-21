"use client";

/**
 * Left-rail navigation for the logged-in dashboard. Active item is
 * derived from the current pathname so the state survives refresh and
 * deep links. Placeholder tabs (History / Saved / Feedback) ship in
 * phase D but route to "coming soon" stubs until phase E/F fill them.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";

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

  return (
    <aside className="w-56 shrink-0 border-r border-sage-border bg-white/60">
      <nav className="sticky top-20 flex flex-col gap-0.5 p-3 text-sm">
        {items.map((item) => {
          // Exact match for the root /dashboard; prefix match for children
          const active =
            item.href === "/dashboard"
              ? pathname === "/dashboard"
              : pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
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
