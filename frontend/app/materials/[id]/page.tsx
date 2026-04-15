/**
 * /materials/[id] — single-material detail page.
 *
 * Layout (v2):
 *   1. Header: formula, family lineage, marquee flags
 *   2. Key stats grid: Tc max / Tc ambient / discovery / paper count
 *   3. Structure section: space group, lattice params, phase
 *   4. SC parameters: pairing, gap, Hc2, lambda_eph, omega_log, rho_s
 *   5. Competing orders: T_CDW/SDW/AFM, rho_exponent, competing_order
 *   6. Samples & pressure: sample_form, substrate, doping, pressure_type
 *   7. Tc records table (per-measurement detail from NER/NIMS)
 *
 * All v2 fields are nullable so each section gracefully hides any
 * row with no data; sections themselves hide entirely when every
 * row is empty.
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

  const flags: [string, boolean | null][] = [
    ["ambient SC", mat.ambient_sc],
    ["unconventional", mat.is_unconventional],
    ["topological", mat.is_topological],
    ["2D / interface", mat.is_2d_or_interface],
    ["competing order", mat.has_competing_order],
    ["disputed", mat.disputed],
    ["retracted", mat.retracted],
  ];
  const activeFlags = flags.filter(([, v]) => v === true);

  return (
    <main className="space-y-8">
      <div>
        <Link href="/materials" className="text-sm text-slate-500 hover:underline">
          ← Materials
        </Link>
        <h1 className="mt-2 text-3xl font-bold tracking-tight">{mat.formula}</h1>
        <p className="mt-1 text-sm text-slate-600">
          {[mat.family, mat.subfamily, mat.crystal_structure, mat.structure_phase]
            .filter(Boolean)
            .join(" · ") || "—"}
        </p>
        {activeFlags.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {activeFlags.map(([label]) => (
              <span
                key={label}
                className="inline-flex items-center rounded-full border border-sage-border bg-[rgba(58,125,92,0.08)] px-3 py-0.5 text-xs font-medium text-accent-deep"
              >
                {label}
              </span>
            ))}
          </div>
        )}
      </div>

      <section className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Fact label="Tc max" value={fmtNum(mat.tc_max, 1)} suffix=" K" />
        <Fact label="Tc ambient" value={fmtNum(mat.tc_ambient, 1)} suffix=" K" />
        <Fact label="Discovery" value={String(mat.discovery_year ?? "—")} />
        <Fact label="Papers" value={mat.total_papers.toString()} />
      </section>

      <DetailSection
        title="Structure"
        rows={[
          ["Crystal structure", mat.crystal_structure],
          ["Space group", mat.space_group],
          ["Phase", mat.structure_phase],
          ["Lattice a (Å)", fmtLattice(mat.lattice_params, "a")],
          ["Lattice c (Å)", fmtLattice(mat.lattice_params, "c")],
        ]}
      />

      <DetailSection
        title="Superconducting parameters"
        rows={[
          ["Pairing symmetry", mat.pairing_symmetry],
          ["Gap structure", mat.gap_structure],
          [
            "Hc2",
            mat.hc2_tesla != null
              ? `${mat.hc2_tesla.toFixed(1)} T${
                  mat.hc2_conditions ? ` (${mat.hc2_conditions})` : ""
                }`
              : null,
          ],
          ["λ_eph (e–ph coupling)", fmtNum(mat.lambda_eph, 2)],
          ["ω_log", mat.omega_log_k != null ? `${mat.omega_log_k.toFixed(0)} K` : null],
          ["ρ_s (superfluid stiffness)", mat.rho_s_mev != null ? `${mat.rho_s_mev.toFixed(1)} meV` : null],
        ]}
      />

      <DetailSection
        title="Competing orders"
        rows={[
          ["Competing order", mat.competing_order],
          ["T_CDW", mat.t_cdw_k != null ? `${mat.t_cdw_k.toFixed(1)} K` : null],
          ["T_SDW", mat.t_sdw_k != null ? `${mat.t_sdw_k.toFixed(1)} K` : null],
          ["T_AFM", mat.t_afm_k != null ? `${mat.t_afm_k.toFixed(1)} K` : null],
          [
            "ρ(T) exponent",
            mat.rho_exponent != null ? mat.rho_exponent.toFixed(2) : null,
          ],
        ]}
      />

      <DetailSection
        title="Samples & pressure"
        rows={[
          ["Sample form", mat.sample_form],
          ["Substrate", mat.substrate],
          ["Pressure type", mat.pressure_type],
          ["Doping type", mat.doping_type],
          [
            "Doping level",
            mat.doping_level != null ? mat.doping_level.toFixed(3) : null,
          ],
        ]}
      />

      {mat.records.length > 0 && (
        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Tc records ({mat.records.length})
          </h2>
          <div className="overflow-x-auto rounded-lg border border-sage-border bg-white">
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
                  const tc = num(r.tc_kelvin ?? r.tc);
                  const year = num(r.year ?? r.measurement_year);
                  const p = num(r.pressure_gpa ?? r.pressure);
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

function DetailSection({
  title,
  rows,
}: {
  title: string;
  rows: [string, string | number | null | undefined][];
}) {
  const filled = rows.filter(([, v]) => v != null && v !== "");
  if (filled.length === 0) return null;
  return (
    <section>
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </h2>
      <div className="overflow-hidden rounded-lg border border-sage-border bg-white">
        <dl className="divide-y divide-slate-100">
          {filled.map(([label, value]) => (
            <div
              key={label}
              className="grid grid-cols-[180px_1fr] gap-4 px-4 py-3 text-sm"
            >
              <dt className="text-slate-500">{label}</dt>
              <dd className="font-medium text-slate-900">{String(value)}</dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
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
    <div className="rounded-lg border border-sage-border bg-white p-4 shadow-sage">
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

function fmtNum(x: number | null | undefined, digits = 1): string {
  return x != null ? x.toFixed(digits) : "—";
}

function fmtLattice(
  lp: Record<string, number> | null | undefined,
  key: "a" | "c",
): string | null {
  const v = lp?.[key];
  return typeof v === "number" ? v.toFixed(3) : null;
}

function num(x: unknown): number | null {
  if (typeof x === "number") return x;
  if (typeof x === "string" && x.trim() !== "") {
    const n = Number(x);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}
