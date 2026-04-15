/**
 * /materials/[id] — single-material detail page.
 * Server-rendered; hydrates the material's TcRecord array into a
 * simple table. Links each record's source paper back to the paper
 * detail page.
 */
import Link from "next/link";
import { notFound } from "next/navigation";
import { getMaterial } from "@/lib/api";
import { ApiError } from "@/lib/api";

export default async function MaterialDetailPage({
  params,
}: {
  params: { id: string };
}) {
  const id = decodeURIComponent(params.id);
  let mat;
  try {
    mat = await getMaterial(id);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }

  return (
    <main className="space-y-8">
      <div>
        <Link href="/materials" className="text-sm text-slate-500 hover:underline">
          ← Materials
        </Link>
        <h1 className="mt-2 text-3xl font-bold tracking-tight">{mat.formula}</h1>
        <p className="mt-1 text-sm text-slate-600">
          {[mat.family, mat.subfamily, mat.crystal_structure]
            .filter(Boolean)
            .join(" · ") || "—"}
        </p>
      </div>

      <section className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Fact label="Tc max" value={mat.tc_max?.toFixed(1) ?? "—"} suffix=" K" />
        <Fact
          label="Tc ambient"
          value={mat.tc_ambient?.toFixed(1) ?? "—"}
          suffix=" K"
        />
        <Fact label="Discovery" value={String(mat.discovery_year ?? "—")} />
        <Fact label="Papers" value={mat.total_papers.toString()} />
      </section>

      {mat.records.length > 0 && (
        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Tc records ({mat.records.length})
          </h2>
          <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-3 text-right font-medium">Tc (K)</th>
                  <th className="px-4 py-3 text-right font-medium">Year</th>
                  <th className="px-4 py-3 text-right font-medium">
                    Pressure (GPa)
                  </th>
                  <th className="px-4 py-3 text-left font-medium">Paper</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {mat.records.map((r, i) => {
                  const tc = num(r.tc_kelvin);
                  const year = num(r.year ?? r.measurement_year);
                  const p = num(r.pressure_gpa);
                  const pid =
                    typeof r.paper_id === "string" ? r.paper_id : null;
                  return (
                    <tr key={i} className="hover:bg-slate-50">
                      <td className="px-4 py-3 text-right tabular-nums">
                        {tc != null ? tc.toFixed(1) : "—"}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-slate-600">
                        {year ?? "—"}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-slate-600">
                        {p != null ? p.toFixed(1) : "ambient"}
                      </td>
                      <td className="px-4 py-3 text-sm">
                        {pid ? (
                          <Link
                            href={`/paper/${encodeURIComponent(pid)}`}
                            className="text-accent hover:text-accent-deep hover:underline"
                          >
                            {pid}
                          </Link>
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </main>
  );
}

function Fact({
  label,
  value,
  suffix,
}: {
  label: string;
  value: string;
  suffix?: string;
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">
        {value}
        {suffix && value !== "—" && (
          <span className="text-base text-slate-500">{suffix}</span>
        )}
      </div>
    </div>
  );
}

function num(x: unknown): number | null {
  if (typeof x === "number") return x;
  if (typeof x === "string" && x.trim() !== "") {
    const n = Number(x);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}
