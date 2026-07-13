/**
 * Global header with the SCLib wordmark + primary nav.
 *
 * The browser session lives in an HttpOnly API cookie, so we fetch /me to get
 * the user name + avatar and render them instead of the generic button.
 * Falls back to "Account" while loading or when not logged in.
 *
 * Because the header is always mounted, we also subscribe to the
 * same-tab auth-change event (see lib/auth-session.ts) so the chip
 * flips to the logged-in state the moment /auth/callback or the
 * login form establishes a session — no refresh or navigation needed.
 */
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { onAuthChange } from "@/lib/auth-session";
import { me, type User, ApiError } from "@/lib/api";

const NAV = [
  { href: "/", label: "Home" },
  { href: "/search", label: "Search" },
  { href: "/materials", label: "Materials" },
  { href: "/timeline", label: "Timeline" },
  { href: "/discovery", label: "Discovery" },
  { href: "/stats", label: "Stats" },
];

export function Header() {
  const [user, setUser] = useState<User | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    function refresh() {
      me()
        .then(setUser)
        .catch((err) => {
          // Expired/missing session: silently show the Account button.
          if (err instanceof ApiError && err.status === 401) {
            setUser(null);
          }
        });
    }
    refresh();
    return onAuthChange(refresh);
  }, []);

  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!menuOpen) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setMenuOpen(false);
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [menuOpen]);

  return (
    <header className="sticky top-0 z-50 border-b border-sage-border bg-[rgba(240,245,240,0.85)] backdrop-blur-md supports-[backdrop-filter]:bg-[rgba(240,245,240,0.72)]">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3 sm:px-6 sm:py-4">
        <Link href="/" className="flex shrink-0 items-baseline gap-2">
          <span className="bg-sage-gradient-text bg-clip-text text-xl font-bold tracking-tight text-transparent">
            SCLib
          </span>
          <span className="text-xs font-semibold uppercase tracking-widest text-sage-tertiary">
            JZIS
          </span>
        </Link>
        <nav className="hidden items-center gap-5 text-sm md:flex lg:gap-6">
          {NAV.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              className="text-sage-muted transition-colors hover:text-accent-deep"
            >
              {n.label}
            </Link>
          ))}

          {user ? (
            <Link
              href="/dashboard"
              className="flex items-center gap-2 rounded-lg border border-sage-border px-3 py-1.5 transition-colors hover:bg-white/60"
            >
              {user.avatar_url ? (
                <img
                  src={user.avatar_url}
                  alt=""
                  className="h-7 w-7 rounded-full"
                  referrerPolicy="no-referrer"
                />
              ) : (
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-accent text-xs font-semibold text-white">
                  {user.name.charAt(0).toUpperCase()}
                </span>
              )}
              <span className="max-w-[100px] truncate text-sm font-medium text-sage-muted">
                {user.name}
              </span>
            </Link>
          ) : (
            <Link
              href="/dashboard"
              className="btn-primary !rounded-lg !px-4 !py-2 !text-sm"
            >
              Account
            </Link>
          )}
        </nav>

        <button
          type="button"
          aria-expanded={menuOpen}
          aria-controls="mobile-navigation"
          aria-label={menuOpen ? "Close navigation" : "Open navigation"}
          onClick={() => setMenuOpen((open) => !open)}
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-sage-border bg-white/70 text-sage-muted transition-colors hover:bg-white hover:text-accent-deep focus:outline-none focus:ring-2 focus:ring-accent/30 md:hidden"
        >
          <span className="sr-only">
            {menuOpen ? "Close navigation" : "Open navigation"}
          </span>
          <span aria-hidden className="relative block h-4 w-5">
            <span
              className={`absolute left-0 top-0.5 h-0.5 w-5 rounded bg-current transition-transform ${
                menuOpen ? "translate-y-[6px] rotate-45" : ""
              }`}
            />
            <span
              className={`absolute left-0 top-[7px] h-0.5 w-5 rounded bg-current transition-opacity ${
                menuOpen ? "opacity-0" : ""
              }`}
            />
            <span
              className={`absolute bottom-0.5 left-0 h-0.5 w-5 rounded bg-current transition-transform ${
                menuOpen ? "-translate-y-[6px] -rotate-45" : ""
              }`}
            />
          </span>
        </button>
      </div>

      {menuOpen && (
        <nav
          id="mobile-navigation"
          aria-label="Mobile navigation"
          className="absolute inset-x-0 top-full max-h-[calc(100vh-4rem)] overflow-y-auto border-b border-sage-border bg-sage-bg/95 px-4 pb-4 pt-2 shadow-lg backdrop-blur-md md:hidden"
        >
          <div className="mx-auto grid max-w-6xl grid-cols-2 gap-2">
            {NAV.map((item) => {
              const active =
                item.href === "/"
                  ? pathname === "/"
                  : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={
                    "rounded-lg px-3 py-2.5 text-sm font-medium transition-colors " +
                    (active
                      ? "bg-accent-light text-accent-deep"
                      : "bg-white/60 text-sage-muted hover:bg-white")
                  }
                >
                  {item.label}
                </Link>
              );
            })}
          </div>
          <Link
            href="/dashboard"
            className="mx-auto mt-3 flex max-w-6xl items-center justify-center gap-2 rounded-lg bg-sage-gradient px-4 py-2.5 text-sm font-semibold text-white shadow-sm"
          >
            {user ? `Account · ${user.name}` : "Account"}
          </Link>
        </nav>
      )}
    </header>
  );
}
