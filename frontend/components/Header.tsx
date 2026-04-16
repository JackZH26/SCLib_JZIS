/**
 * Global header with the SCLib wordmark + primary nav.
 *
 * After login the JWT is in localStorage → we fetch /me to get the user
 * name + avatar and render them instead of the generic "Account" button.
 * Falls back to "Account" while loading or when not logged in.
 */
"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { loadToken } from "@/lib/auth-storage";
import { me, type User, ApiError } from "@/lib/api";

const NAV = [
  { href: "/search", label: "Search" },
  { href: "/ask", label: "Ask" },
  { href: "/materials", label: "Materials" },
  { href: "/timeline", label: "Timeline" },
  { href: "/stats", label: "Stats" },
];

export function Header() {
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    const token = loadToken();
    if (!token) return;
    me(token)
      .then(setUser)
      .catch((err) => {
        // Token expired / invalid — silently ignore, show Account button
        if (err instanceof ApiError && err.status === 401) {
          // Don't clear token here — let dashboard handle that
        }
      });
  }, []);

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
      </div>
    </header>
  );
}
