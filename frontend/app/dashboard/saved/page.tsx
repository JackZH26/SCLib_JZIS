"use client";

/**
 * /dashboard/saved — Bookmarks tab.
 *
 * Thin wrapper around BookmarksPanel (which carries the tab state
 * and per-type fetch). Split so the ComingSoon → real-UI diff for
 * this tab touches exactly one file.
 */
import { BookmarksPanel } from "@/components/dashboard/BookmarksPanel";

export default function SavedPage() {
  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-sage-ink">Bookmarks</h2>
        <p className="mt-1 text-sm text-sage-muted">
          Papers and materials you&apos;ve starred. Open any detail page and
          click the ★ button to add more. Bookmarks are private to your
          account.
        </p>
      </div>
      <BookmarksPanel />
    </div>
  );
}
