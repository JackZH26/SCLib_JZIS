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
      className="flex w-full gap-2"
    >
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={placeholder}
        className="flex-1 rounded-[10px] border border-sage-border bg-white px-4 py-3 text-base text-sage-ink shadow-sage placeholder:text-sage-tertiary focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
      />
      <button type="submit" className="btn-primary">
        Search
      </button>
    </form>
  );
}
