/**
 * Global header with the SCLib wordmark + primary nav.
 *
 * Rendered from the root layout so every page gets it. Kept as a
 * server component — no client state — so the initial HTML is
 * fully SSR'd.
 */
import Link from "next/link";

const NAV = [
  { href: "/search", label: "Search" },
  { href: "/ask", label: "Ask" },
  { href: "/materials", label: "Materials" },
  { href: "/timeline", label: "Timeline" },
  { href: "/stats", label: "Stats" },
];

export function Header() {
  return (
    <header className="border-b border-slate-200 bg-white/80 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
        <Link href="/" className="flex items-baseline gap-2">
          <span className="text-xl font-bold tracking-tight">SCLib</span>
          <span className="text-xs text-slate-500">JZIS</span>
        </Link>
        <nav className="flex items-center gap-6 text-sm">
          {NAV.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              className="text-slate-700 hover:text-slate-900"
            >
              {n.label}
            </Link>
          ))}
          <Link
            href="/dashboard"
            className="rounded-md bg-slate-900 px-3 py-1.5 text-white hover:bg-slate-700"
          >
            Account
          </Link>
        </nav>
      </div>
    </header>
  );
}
