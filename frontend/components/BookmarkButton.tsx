"use client";

/**
 * ★ Save / ★ Saved toggle. Embedded on paper + material detail pages.
 *
 * State machine:
 *
 *   loading     (fetching bookmark list to see if this target is saved)
 *   logged-out  (no JWT; render a muted prompt that links to /login)
 *   unsaved     (saved=false; click POSTs and transitions to saved)
 *   saved       (saved=true, holds the bookmark.id; click DELETEs)
 *
 * On mount we pull the user's full bookmark list for the relevant
 * type and scan for this target_id. That's one round-trip per page
 * load, acceptable while per-user counts stay in the hundreds. If
 * usage ever outgrows that, add a dedicated GET /bookmarks/lookup
 * endpoint — the button contract doesn't change.
 */
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  ApiError,
  createBookmark,
  deleteBookmark,
  listMaterialBookmarks,
  listPaperBookmarks,
  type BookmarkTargetType,
} from "@/lib/api";
import { loadToken } from "@/lib/auth-storage";

type State =
  | { kind: "loading" }
  | { kind: "logged-out" }
  | { kind: "unsaved" }
  | { kind: "saved"; bookmarkId: string };

export function BookmarkButton({
  targetType,
  targetId,
}: {
  targetType: BookmarkTargetType;
  targetId: string;
}) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = loadToken();
    if (!token) {
      setState({ kind: "logged-out" });
      return;
    }
    const fetcher =
      targetType === "paper" ? listPaperBookmarks : listMaterialBookmarks;
    fetcher(token)
      .then((resp) => {
        const hit = resp.results.find((r) => r.target_id === targetId);
        setState(hit ? { kind: "saved", bookmarkId: hit.id } : { kind: "unsaved" });
      })
      .catch(() => setState({ kind: "unsaved" }));
  }, [targetType, targetId]);

  async function toggle() {
    const token = loadToken();
    if (!token) return; // button is disabled in logged-out state anyway
    if (state.kind === "loading") return;
    setBusy(true);
    setError(null);
    try {
      if (state.kind === "saved") {
        await deleteBookmark(token, state.bookmarkId);
        setState({ kind: "unsaved" });
      } else {
        const bm = await createBookmark(token, targetType, targetId);
        setState({ kind: "saved", bookmarkId: bm.id });
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  if (state.kind === "logged-out") {
    return (
      <Link
        href="/login"
        className="inline-flex items-center gap-1.5 rounded-md border border-sage-border bg-white px-3 py-1.5 text-sm text-sage-muted hover:text-accent-deep"
      >
        <StarIcon filled={false} />
        Sign in to save
      </Link>
    );
  }

  const isSaved = state.kind === "saved";
  const label =
    state.kind === "loading" ? "…"
      : isSaved ? "Saved"
      : "Save";

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={toggle}
        disabled={busy || state.kind === "loading"}
        className={[
          "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm transition-colors disabled:opacity-60",
          isSaved
            ? "border-accent bg-[rgba(58,125,92,0.1)] text-accent-deep hover:bg-[rgba(58,125,92,0.18)]"
            : "border-sage-border bg-white text-sage-muted hover:text-accent-deep",
        ].join(" ")}
        aria-pressed={isSaved}
        title={isSaved ? "Click to remove from your bookmarks" : "Click to save"}
      >
        <StarIcon filled={isSaved} />
        {busy ? (isSaved ? "Removing…" : "Saving…") : label}
      </button>
      {error ? (
        <span className="text-xs text-red-700" role="alert">
          {error}
        </span>
      ) : null}
    </div>
  );
}

function StarIcon({ filled }: { filled: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="14"
      height="14"
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth="2"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <polygon points="12 2 15 9 22 9.5 17 14 18.5 21 12 17.5 5.5 21 7 14 2 9.5 9 9" />
    </svg>
  );
}
