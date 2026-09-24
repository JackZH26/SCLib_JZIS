"use client";

/**
 * Minimal search input used by the home page and the /search page.
 * Pushes the query to /search?q=... on submit so the full page
 * can handle filters + pagination without a client-side refetch here.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";

export function SearchBar({
  placeholder = "Search papers or materials, or just ask a question…",
  initial = "",
  target = "/search",
}: {
  placeholder?: string;
  initial?: string;
  target?: string;
}) {
  const [q, setQ] = useState(initial);
  const router = useRouter();

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (q.trim().length < 2) return;
        router.push(`${target}?q=${encodeURIComponent(q.trim())}`);
      }}
      role="search"
      aria-label="Library search"
      className="flex w-full gap-2"
    >
      <input
        type="search"
        name="q"
        aria-label="Search papers, materials, or ask a research question"
        minLength={2}
        required
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={placeholder}
        className="min-w-0 flex-1 rounded-[10px] border border-sage-border bg-white px-4 py-3 text-base text-sage-ink shadow-sage placeholder:text-sage-tertiary focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
      />
      <button type="submit" className="btn-primary shrink-0">
        Search
      </button>
    </form>
  );
}
