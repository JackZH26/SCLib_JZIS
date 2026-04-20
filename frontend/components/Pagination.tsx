/**
 * arXiv-style pagination footer.
 *
 * Renders two rows:
 *
 *   Total of N entries : 1-50  51-100  101-150  ...  851-896
 *   Showing up to 50 entries per page:  fewer | more | all
 *
 * Server-rendered — every control is a plain <Link>. That keeps the
 * page SSR-friendly and means the browser's back/forward buttons work
 * naturally. All other existing search params are preserved when
 * changing page or page size.
 *
 * The API used here (/materials) caps `limit` at 200, so "all" folds
 * to 200 rather than loading the whole table at once (which would be
 * ~7000 rows and hurt TTFB for no real gain). If the backend ever
 * lifts that cap we can drop the MAX_LIMIT clamp here too.
 */
import Link from "next/link";

const PAGE_SIZES = [25, 50, 100, 200] as const;
const MAX_LIMIT = 200;

interface PaginationProps {
  total: number;
  limit: number;
  offset: number;
  basePath: string;
  /** All current query params so links preserve active filters. */
  searchParams: Record<string, string | undefined>;
}

/**
 * Decide which page indices to show, with ellipsis gaps.
 * Indices are 0-based page numbers; "..." marks a collapsed gap.
 *
 * - ≤7 pages: show all
 * - current near start: 0,1,2,3,4,…,last
 * - current near end: 0,…,last-4..last
 * - middle: 0,…,current-1,current,current+1,…,last
 */
function pageWindow(current: number, total: number): (number | "...")[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i);
  if (current <= 3) return [0, 1, 2, 3, 4, "...", total - 1];
  if (current >= total - 4)
    return [
      0,
      "...",
      total - 5,
      total - 4,
      total - 3,
      total - 2,
      total - 1,
    ];
  return [0, "...", current - 1, current, current + 1, "...", total - 1];
}

export function Pagination({
  total,
  limit,
  offset,
  basePath,
  searchParams,
}: PaginationProps) {
  if (total === 0) return null;

  const effectiveLimit = Math.min(Math.max(limit, 1), MAX_LIMIT);
  const totalPages = Math.max(1, Math.ceil(total / effectiveLimit));
  const currentPage = Math.min(
    totalPages - 1,
    Math.floor(offset / effectiveLimit),
  );

  // Build a query string from the current params, optionally overriding
  // page and per_page. Empty strings and the "default" values are
  // dropped so canonical URLs stay short (e.g. /materials for page 0).
  const buildHref = (page: number, perPage?: number): string => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(searchParams)) {
      if (v == null || v === "") continue;
      if (k === "page" || k === "per_page") continue;
      qs.set(k, v);
    }
    if (page > 0) qs.set("page", String(page));
    const pp = perPage ?? effectiveLimit;
    if (pp !== 50) qs.set("per_page", String(pp));
    const qstr = qs.toString();
    return qstr ? `${basePath}?${qstr}` : basePath;
  };

  // Render a page-range label: "1-50", "51-100", "851-896"
  const rangeLabel = (pageIdx: number): string => {
    const from = pageIdx * effectiveLimit + 1;
    const to = Math.min((pageIdx + 1) * effectiveLimit, total);
    return `${from}-${to}`;
  };

  // fewer / more / all controls: pick the next smaller/larger size
  // relative to the current effectiveLimit. "all" hops straight to MAX.
  const idxInSizes = PAGE_SIZES.indexOf(effectiveLimit as (typeof PAGE_SIZES)[number]);
  const smaller = idxInSizes > 0 ? PAGE_SIZES[idxInSizes - 1] : null;
  const larger =
    idxInSizes >= 0 && idxInSizes < PAGE_SIZES.length - 1
      ? PAGE_SIZES[idxInSizes + 1]
      : null;
  const allSize = MAX_LIMIT;

  // When changing page size we reset to page 0 so the user isn't
  // stranded past the new end-of-list.
  const sizeHref = (size: number) => buildHref(0, size);

  const window = pageWindow(currentPage, totalPages);

  return (
    <nav
      aria-label="Pagination"
      className="mt-6 space-y-1.5 border-t border-sage-border pt-4 text-sm text-slate-600"
    >
      {/* Row 1: Total + page-range links */}
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="text-slate-500">
          Total of{" "}
          <span className="font-semibold text-slate-800">
            {total.toLocaleString()}
          </span>{" "}
          entries :
        </span>
        {window.map((item, i) =>
          item === "..." ? (
            <span key={`gap-${i}`} className="text-slate-400">
              …
            </span>
          ) : item === currentPage ? (
            <span
              key={item}
              aria-current="page"
              className="font-semibold text-slate-900"
            >
              {rangeLabel(item)}
            </span>
          ) : (
            <Link
              key={item}
              href={buildHref(item)}
              className="text-[color:var(--accent)] hover:text-[color:var(--accent-deep)] hover:underline"
            >
              {rangeLabel(item)}
            </Link>
          ),
        )}
      </div>

      {/* Row 2: page-size controls */}
      <div className="flex flex-wrap items-baseline gap-x-2 text-slate-500">
        <span>
          Showing up to{" "}
          <span className="font-semibold text-slate-800">
            {effectiveLimit}
          </span>{" "}
          entries per page:
        </span>
        {smaller != null ? (
          <Link
            href={sizeHref(smaller)}
            className="text-[color:var(--accent)] hover:text-[color:var(--accent-deep)] hover:underline"
          >
            fewer
          </Link>
        ) : (
          <span className="text-slate-300">fewer</span>
        )}
        <span className="text-slate-300">|</span>
        {larger != null ? (
          <Link
            href={sizeHref(larger)}
            className="text-[color:var(--accent)] hover:text-[color:var(--accent-deep)] hover:underline"
          >
            more
          </Link>
        ) : (
          <span className="text-slate-300">more</span>
        )}
        <span className="text-slate-300">|</span>
        {effectiveLimit < allSize ? (
          <Link
            href={sizeHref(allSize)}
            className="text-[color:var(--accent)] hover:text-[color:var(--accent-deep)] hover:underline"
          >
            all
          </Link>
        ) : (
          <span className="text-slate-300">all</span>
        )}
      </div>
    </nav>
  );
}
