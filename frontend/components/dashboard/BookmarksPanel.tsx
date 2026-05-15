"use client";

/**
 * Bookmarks tab: two sub-panels (Papers, Materials) with a pill switch.
 *
 * Each panel lazy-fetches when first selected so opening the dashboard
 * only hits the active type. Unbookmark lives inline per row — no
 * ConfirmModal, because the action is cheap to redo (just click the
 * ★ button on the detail page) unlike deleting ask history.
 */
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  deleteBookmark,
  listMaterialBookmarks,
  listPaperBookmarks,
  type BookmarkedMaterial,
  type BookmarkedPaper,
} from "@/lib/api";
import { loadToken } from "@/lib/auth-storage";

type Tab = "papers" | "materials";

export function BookmarksPanel() {
  const [tab, setTab] = useState<Tab>("papers");

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <TabPill label="Papers" active={tab === "papers"} onClick={() => setTab("papers")} />
        <TabPill
          label="Materials"
          active={tab === "materials"}
          onClick={() => setTab("materials")}
        />
      </div>
      {tab === "papers" ? <PapersPanel /> : <MaterialsPanel />}
    </div>
  );
}

function TabPill({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "rounded-full px-4 py-1.5 text-sm transition-colors",
        active
          ? "bg-accent-deep text-white"
          : "border border-sage-border bg-white text-sage-muted hover:text-accent-deep",
      ].join(" ")}
    >
      {label}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Papers
// ---------------------------------------------------------------------------

function PapersPanel() {
  const [rows, setRows] = useState<BookmarkedPaper[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    const token = loadToken();
    if (!token) return;
    try {
      const resp = await listPaperBookmarks(token);
      setRows(resp.results);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load bookmarks");
    }
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  async function onRemove(id: string) {
    const token = loadToken();
    if (!token) return;
    setBusyId(id);
    try {
      await deleteBookmark(token, id);
      setRows((prev) => prev?.filter((r) => r.id !== id) ?? prev);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Remove failed");
    } finally {
      setBusyId(null);
    }
  }

  if (rows === null) return <p className="text-sm text-sage-muted">Loading papers…</p>;
  if (error) return <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>;
  if (rows.length === 0) {
    return (
      <EmptyState
        title="No saved papers yet"
        blurb="Click the ★ Save button on any paper detail page to add it here."
      />
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-sage-border bg-white">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-xs uppercase tracking-wide text-sage-tertiary">
          <tr>
            <th className="px-4 py-2 text-left font-medium">Title</th>
            <th className="px-4 py-2 text-left font-medium">Authors</th>
            <th className="px-4 py-2 text-left font-medium">Family</th>
            <th className="px-4 py-2 text-left font-medium">Date</th>
            <th className="px-4 py-2 text-left font-medium">Saved</th>
            <th className="px-4 py-2 text-right font-medium">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((p) => (
            <tr key={p.id} className="hover:bg-slate-50/60">
              <td className="px-4 py-2">
                <Link
                  href={`/paper/${encodeURIComponent(p.target_id)}`}
                  className="block max-w-[24rem] truncate font-medium text-sage-ink hover:underline"
                  title={p.title}
                >
                  {p.title}
                </Link>
                {p.status === "retracted" && (
                  <span className="mt-0.5 inline-block rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-medium text-red-800">
                    retracted
                  </span>
                )}
              </td>
              <td className="px-4 py-2 text-sage-muted">
                {shortAuthors(p.authors)}
              </td>
              <td className="px-4 py-2 text-sage-muted">{p.material_family ?? "—"}</td>
              <td className="px-4 py-2 text-sage-muted">
                {p.date_submitted ?? "—"}
              </td>
              <td className="px-4 py-2 text-sage-muted">
                {formatAbs(p.created_at)}
              </td>
              <td className="px-4 py-2 text-right">
                <button
                  onClick={() => onRemove(p.id)}
                  disabled={busyId === p.id}
                  className="rounded-md border border-sage-border bg-white px-2.5 py-1 text-xs text-red-700 hover:bg-red-50 disabled:opacity-60"
                >
                  {busyId === p.id ? "Removing…" : "Remove"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Materials
// ---------------------------------------------------------------------------

function MaterialsPanel() {
  const [rows, setRows] = useState<BookmarkedMaterial[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    const token = loadToken();
    if (!token) return;
    try {
      const resp = await listMaterialBookmarks(token);
      setRows(resp.results);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load bookmarks");
    }
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  async function onRemove(id: string) {
    const token = loadToken();
    if (!token) return;
    setBusyId(id);
    try {
      await deleteBookmark(token, id);
      setRows((prev) => prev?.filter((r) => r.id !== id) ?? prev);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Remove failed");
    } finally {
      setBusyId(null);
    }
  }

  if (rows === null) return <p className="text-sm text-sage-muted">Loading materials…</p>;
  if (error) return <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>;
  if (rows.length === 0) {
    return (
      <EmptyState
        title="No saved materials yet"
        blurb="Click the ★ Save button on any material detail page to add it here."
      />
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-sage-border bg-white">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-xs uppercase tracking-wide text-sage-tertiary">
          <tr>
            <th className="px-4 py-2 text-left font-medium">Formula</th>
            <th className="px-4 py-2 text-left font-medium">Family</th>
            <th className="px-4 py-2 text-right font-medium">Tc max (K)</th>
            <th className="px-4 py-2 text-right font-medium">Tc ambient</th>
            <th className="px-4 py-2 text-right font-medium">arXiv year</th>
            <th className="px-4 py-2 text-left font-medium">Saved</th>
            <th className="px-4 py-2 text-right font-medium">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((m) => (
            <tr key={m.id} className="hover:bg-slate-50/60">
              <td className="px-4 py-2">
                <Link
                  href={`/materials/${encodeURIComponent(m.target_id)}`}
                  className="block max-w-[18rem] truncate font-medium text-sage-ink hover:underline"
                  title={m.formula}
                >
                  {m.formula}
                </Link>
              </td>
              <td className="px-4 py-2 text-sage-muted">{m.family ?? "—"}</td>
              <td className="px-4 py-2 text-right tabular-nums text-sage-ink">
                {m.tc_max != null ? m.tc_max.toFixed(1) : "—"}
              </td>
              <td className="px-4 py-2 text-right tabular-nums text-sage-muted">
                {m.tc_ambient != null ? m.tc_ambient.toFixed(1) : "—"}
              </td>
              <td className="px-4 py-2 text-right tabular-nums text-sage-muted">
                {m.arxiv_year ?? "—"}
              </td>
              <td className="px-4 py-2 text-sage-muted">
                {formatAbs(m.created_at)}
              </td>
              <td className="px-4 py-2 text-right">
                <button
                  onClick={() => onRemove(m.id)}
                  disabled={busyId === m.id}
                  className="rounded-md border border-sage-border bg-white px-2.5 py-1 text-xs text-red-700 hover:bg-red-50 disabled:opacity-60"
                >
                  {busyId === m.id ? "Removing…" : "Remove"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function EmptyState({ title, blurb }: { title: string; blurb: string }) {
  return (
    <div className="rounded-lg border border-dashed border-sage-border bg-white p-8 text-center">
      <p className="text-sm font-medium text-sage-ink">{title}</p>
      <p className="mt-1 text-sm text-sage-muted">{blurb}</p>
    </div>
  );
}

function shortAuthors(authors: string[]): string {
  if (authors.length === 0) return "—";
  if (authors.length === 1) return authors[0];
  if (authors.length === 2) return authors.join(" & ");
  return `${authors[0]} et al.`;
}

function formatAbs(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}
