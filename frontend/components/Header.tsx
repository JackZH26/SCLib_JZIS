/**
 * Global header with the SCLib wordmark + primary nav.
 *
 * Visually mirrors asrp.jzis.org's fixed nav: translucent sage bg with
 * a backdrop blur, sage border, muted link colour, and a gradient
 * "Account" CTA. Kept as a server component — no client state — so
 * the initial HTML is fully SSR'd.
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
    <header className="sticky top-0 z-50 border-b border-sage-border bg-[rgba(240,245,240,0.85)] backdrop-blur-md supports-[backdrop-filter]:bg-[rgba(240,245,240,0.72)]">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
        <Link href="/" className="flex items-baseline gap-2">
          <span className="bg-sage-gradient-text bg-clip-text text-xl font-bold tracking-tight text-transparent">
            SCLib
          </span>
          <span className="text-xs font-semibold uppercase tracking-widest text-sage-tertiary">
            JZIS
          </span>
        </Link>
        <nav className="flex items-center gap-6 text-sm">
          {NAV.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              className="text-sage-muted transition-colors hover:text-accent-deep"
            >
              {n.label}
            </Link>
          ))}
          <Link
            href="/dashboard"
            className="btn-primary !rounded-lg !px-4 !py-2 !text-sm"
          >
            Account
          </Link>
        </nav>
      </div>
    </header>
  );
}
