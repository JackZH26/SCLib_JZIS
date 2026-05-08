/**
 * Shows the current guest quota ("2/3 queries remaining today") and
 * a nudge to register. Hidden when `remaining` is null (authed user).
 */
import Link from "next/link";

export function GuestBanner({ remaining }: { remaining: number | null }) {
  if (remaining === null || remaining === undefined) return null;
  return (
    <div className="rounded-md border border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-900">
      Guest mode: <strong>{remaining}</strong>{" "}
      {remaining === 1 ? "query" : "queries"} remaining today.{" "}
      <Link href="/register" className="underline hover:text-amber-700">
        Register for more queries
      </Link>
      .
    </div>
  );
}
