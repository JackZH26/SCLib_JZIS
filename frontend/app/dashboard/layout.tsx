"use client";

/**
 * Dashboard shell — auth guard + sidebar + child slot.
 *
 * The shell is a client component because the JWT lives in
 * localStorage (not a cookie) so the whole tree is rendered after
 * client hydration. One `/auth/me` call happens here to keep the
 * sidebar badge (username, avatar, sign out) accurate without each
 * child re-fetching. Children still hit their own endpoints for the
 * tab-specific data (/usage, /keys, etc.).
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError, me, type User } from "@/lib/api";
import { clearToken, loadToken } from "@/lib/auth-storage";
import { Sidebar } from "@/components/dashboard/Sidebar";
import { DashboardUserProvider } from "@/components/dashboard/user-context";

const NAV = [
  { href: "/dashboard",          label: "Overview" },
  { href: "/dashboard/keys",     label: "API Keys" },
  { href: "/dashboard/history",  label: "Ask History" },
  { href: "/dashboard/saved",    label: "Bookmarks" },
  { href: "/dashboard/feedback", label: "Feedback",     placeholder: true },
];

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = loadToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    me(token)
      .then(setUser)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          clearToken();
          router.replace("/login");
        } else {
          setError(err instanceof Error ? err.message : "Failed to load profile");
        }
      });
  }, [router]);

  function onSignOut() {
    clearToken();
    router.push("/login");
  }

  if (error) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-20">
        <p className="text-red-700">{error}</p>
      </main>
    );
  }
  if (!user) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-20 text-slate-500">
        Loading dashboard…
      </main>
    );
  }

  return (
    <DashboardUserProvider value={{ user, setUser }}>
      <main className="mx-auto flex max-w-6xl gap-8 px-6 py-10">
        <Sidebar items={NAV} />
        <section className="min-w-0 flex-1">
          <header className="mb-6 flex items-start justify-between gap-4">
            <div className="flex items-center gap-3">
              {user.avatar_url ? (
                /* eslint-disable-next-line @next/next/no-img-element */
                <img
                  src={user.avatar_url}
                  alt=""
                  referrerPolicy="no-referrer"
                  className="h-10 w-10 rounded-full"
                />
              ) : (
                <span className="flex h-10 w-10 items-center justify-center rounded-full bg-accent text-sm font-semibold text-white">
                  {user.name.charAt(0).toUpperCase()}
                </span>
              )}
              <div>
                <h1 className="text-2xl font-semibold text-sage-ink">
                  {user.name}
                </h1>
                <p className="text-sm text-sage-muted">{user.email}</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Link
                href="/"
                className="rounded-md border border-sage-border bg-white px-3 py-1.5 text-sm text-sage-muted hover:text-accent-deep"
              >
                Back to site
              </Link>
              <button
                onClick={onSignOut}
                className="rounded-md bg-accent-deep px-3 py-1.5 text-sm font-medium text-white hover:bg-accent"
              >
                Sign out
              </button>
            </div>
          </header>
          {children}
        </section>
      </main>
    </DashboardUserProvider>
  );
}
