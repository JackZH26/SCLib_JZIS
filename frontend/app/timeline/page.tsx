/**
 * /timeline — Tc-vs-year Plotly scatter for the whole corpus or a
 * single family. Server component does the fetch; the chart itself
 * is a client component (plotly touches `window`).
 */
import { getTimeline } from "@/lib/api";
import { TcTimeline } from "@/components/TcTimeline";
import Link from "next/link";

const FAMILIES = [
  { slug: "", label: "All" },
  { slug: "cuprate", label: "Cuprate" },
  { slug: "iron", label: "Iron-based" },
  { slug: "hydride", label: "Hydride" },
  { slug: "mgb2", label: "MgB₂" },
  { slug: "heavy_fermion", label: "Heavy fermion" },
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
          Transition temperature versus year, one dot per reported measurement.
          Color by material family.
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
        <TcTimeline points={data.points} />
      )}
    </main>
  );
}
