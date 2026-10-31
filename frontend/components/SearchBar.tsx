"use client";

/**
 * Minimal search input used by the home page and the /search page.
 * Pushes the query to /?q=... on submit so the home page
 * can handle filters + pagination without a client-side refetch here.
 */
import { useRouter } from "next/navigation";
import { useId } from "react";

export function SearchBar({
  placeholder = "Search papers or materials, or just ask a question…",
  initial = "",
  target = "/",
}: {
  placeholder?: string;
  initial?: string;
  target?: string;
}) {
  const inputId = useId();
  const router = useRouter();

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        // Read the actual input, including typing before hydration or autofill.
        const q = String(new FormData(e.currentTarget).get("q") ?? "").trim();
        if (q.length < 2) return;
        router.push(`${target}?q=${encodeURIComponent(q)}`);
      }}
      role="search"
      aria-label="Library search"
      className="library-search w-full"
    >
      <label htmlFor={inputId} className="mb-2 block text-sm font-semibold text-sage-ink">Search the library</label>
      <div className="flex gap-2 rounded-xl border border-sage-border bg-white p-1.5 shadow-sage focus-within:border-accent">
        <input
          id={inputId}
          type="search"
          name="q"
          aria-label="Search the library: papers, materials, wiki, or a research question"
          minLength={2}
          required
          defaultValue={initial}
          placeholder={placeholder}
          className="min-w-0 flex-1 rounded-lg bg-white px-3 py-3 text-base text-sage-ink placeholder:text-sage-muted focus-visible:outline-offset-[-2px]"
        />
        <button type="submit" className="btn-primary shrink-0 !px-5">
          Search
        </button>
      </div>
    </form>
  );
}
