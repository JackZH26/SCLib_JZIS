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
  { slug: "hydride",       label: "Hydride" },
  { slug: "mgb2",          label: "MgB₂" },
  { slug: "heavy_fermion", label: "Heavy fermion" },
  { slug: "fulleride",     label: "Fulleride" },
  { slug: "conventional",  label: "Conventional" },
];

export default async function TimelinePage({
  searchParams,
}: {
  searchParams: { family?: string };
}) {
  const current = searchParams.family ?? "";
  const data = await getTimeline(current || undefined).catch(() => null);

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

      <div className="flex flex-wrap gap-2">
        {FAMILIES.map((f) => {
          const active = f.slug === current;
          return (
            <Link
              key={f.slug}
              href={f.slug ? `/timeline?family=${f.slug}` : "/timeline"}
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
