/**
 * /timeline — Tc-vs-year Plotly scatter for the whole corpus or a
 * single family.  Server component does the fetch; the chart itself
 * is a client component (plotly touches `window`).
 *
 * Family slugs MUST match the strings written into Material.family
 * by the aggregator / classify_family() in nims.py. The previous
 * revision used "iron" as the slug while the DB stores "iron_based",
 * so the Iron-based filter button produced zero points. Fixed here.
 */
import { getTimeline } from "@/lib/api";
import { TcTimeline } from "@/components/TcTimeline";
import Link from "next/link";

const FAMILIES = [
  { slug: "",              label: "All" },
  { slug: "cuprate",       label: "Cuprate" },
  { slug: "iron_based",    label: "Iron-based" },
  { slug: "nickelate",     label: "Nickelate" },
  { slug: "hydride",       label: "Hydride" },
  { slug: "mgb2",          label: "MgB₂" },
  { slug: "heavy_fermion", label: "Heavy fermion" },
  { slug: "fulleride",     label: "Fulleride" },
  { slug: "conventional",  label: "Conventional" },
];

export default async function TimelinePage({
  searchParams,
}: {
  searchParams: { family?: string; experimental_only?: string };
}) {
  const current = searchParams.family ?? "";
  // Booleans on URL: anything other than the literal string "true"
  // is treated as off, so back-button / shared links don't end up in
  // a half-checked state when query strings are sloppy.
  const experimentalOnly = searchParams.experimental_only === "true";
  const data = await getTimeline({
    family: current || undefined,
    experimentalOnly,
  }).catch(() => null);

  // Build hrefs that round-trip the *other* filter so toggling one
  // never silently resets the other. The family buttons preserve
  // experimental_only, and the experimental toggle preserves family.
  const buildHref = (
    nextFamily: string,
    nextExperimentalOnly: boolean,
  ): string => {
    const qs = new URLSearchParams();
    if (nextFamily) qs.set("family", nextFamily);
    if (nextExperimentalOnly) qs.set("experimental_only", "true");
    const s = qs.toString();
    return s ? `/timeline?${s}` : "/timeline";
  };

  return (
    <main className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Tc timeline</h1>
        <p className="mt-1 text-sm text-slate-600">
          Transition temperature versus year, one dot per reported
          measurement. Colour by material family. Implausible Tc
          values (&gt;250&nbsp;K at ambient pressure — usually NER
          confusing a Curie / melting / structural transition with
          the SC Tc) are filtered out automatically.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {FAMILIES.map((f) => {
          const active = f.slug === current;
          return (
            <Link
              key={f.slug}
              href={buildHref(f.slug, experimentalOnly)}
              className={
                active
                  ? "rounded-md bg-slate-900 px-3 py-1.5 text-sm text-white"
                  : "rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-100"
              }
            >
              {f.label}
            </Link>
          );
        })}

        {/*
          "Only experimental" toggle. Clicking flips the URL flag and
          Next re-renders the server component with the filtered set
          (the API drops theoretical points before responding, so
          coverage counts also shrink to match). Rendered as a
          checkbox-shaped Link rather than an <input type="checkbox">
          so the filter row stays a single SSR-friendly component
          with no client state.
        */}
        <Link
          href={buildHref(current, !experimentalOnly)}
          aria-pressed={experimentalOnly}
          className={
            "ml-auto inline-flex items-center gap-2 rounded-md border " +
            "px-3 py-1.5 text-sm transition-colors " +
            (experimentalOnly
              ? "border-[color:var(--accent)] bg-[color:var(--accent)] text-white hover:bg-[color:var(--accent-deep)]"
              : "border-slate-300 bg-white text-slate-700 hover:bg-slate-100")
          }
        >
          <span
            aria-hidden
            className={
              "flex h-4 w-4 items-center justify-center rounded-sm border " +
              (experimentalOnly
                ? "border-white bg-white text-[color:var(--accent)]"
                : "border-slate-400 bg-white text-transparent")
            }
          >
            <svg
              viewBox="0 0 16 16"
              width="12"
              height="12"
              className={experimentalOnly ? "" : "invisible"}
            >
              <path
                d="M3 8l3 3 7-7"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </span>
          Only experimental
        </Link>
      </div>

      {data == null ? (
        <p className="text-sm text-red-600">Failed to load timeline.</p>
      ) : (
        <>
          {data.coverage && data.coverage.total_points > 0 && (
            <p className="text-xs text-slate-500">
              <span className="font-medium text-slate-700">
                {data.coverage.total_points.toLocaleString()}
              </span>{" "}
              measurement{data.coverage.total_points === 1 ? "" : "s"}{" "}
              from{" "}
              <span className="font-medium text-slate-700">
                {data.coverage.total_materials.toLocaleString()}
              </span>{" "}
              materials
              {data.coverage.year_min != null &&
                data.coverage.year_max != null && (
                  <>
                    {" "}
                    · years{" "}
                    <span className="font-medium text-slate-700">
                      {data.coverage.year_min}
                    </span>
                    –
                    <span className="font-medium text-slate-700">
                      {data.coverage.year_max}
                    </span>
                  </>
                )}
              {" "}· drag to pan, scroll to zoom
            </p>
          )}
          <TcTimeline points={data.points} coverage={data.coverage} />
        </>
      )}
    </main>
  );
}
