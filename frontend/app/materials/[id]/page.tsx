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

      {mat.tc_max_conditions && (
        <p className="-mt-4 text-xs text-slate-500">
          Tc max measured at{" "}
          <span className="font-medium text-slate-700">
            {mat.tc_max_conditions}
          </span>
        </p>
      )}

      {/*
        Records / provenance section lives near the top (not at the
        bottom) so readers can immediately see the evidence behind the
        flat-column aggregates above. The flat columns pick one value
        per field (max / weighted mode / ..., see
        ingestion/.../materials_aggregator.py), but research papers
        rarely agree exactly — this table lets the reader verify the
        claim and cross-check against the source paper.
      */}
      {mat.records.length > 0 && (
        <RecordsTable records={mat.records} />
      )}

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

    </main>
  );
}

/**
 * The "evidence trail" behind the flat columns. Each row is one
 * paper's claim about this material: Tc at some pressure on some
 * sample form measured with some method. Deduped by paper_id +
 * tc_kelvin + pressure_gpa so multiple rows from the same paper
 * reporting the same Tc under the same conditions don't clutter.
 *
 * Sorted most-informative first: Tc descending, then year descending
 * (prefer latest measurement when Tcs tie).
 */
function RecordsTable({
  records,
}: {
  records: Record<string, unknown>[];
}) {
  // Dedupe: same paper reporting same Tc at same pressure = one row.
  // The NER sometimes emits one record per measurement technique
  // (resistivity vs susceptibility) which is interesting only when
  // the Tc differs; otherwise collapse them and show all techniques.
  const seen = new Map<string, Record<string, unknown> & { _methods: Set<string> }>();
  for (const r of records) {
    const tc = num(r.tc_kelvin ?? r.tc);
    const p = num(r.pressure_gpa ?? r.pressure);
    const pid = typeof r.paper_id === "string" ? r.paper_id : "";
    const key = `${pid}::${tc ?? "_"}::${p ?? "_"}`;
    const prev = seen.get(key);
    const meas = typeof r.measurement === "string" ? r.measurement : "";
    if (prev) {
      if (meas && meas.toLowerCase() !== "unknown") prev._methods.add(meas);
    } else {
      const methods = new Set<string>();
      if (meas && meas.toLowerCase() !== "unknown") methods.add(meas);
      seen.set(key, { ...r, _methods: methods });
    }
  }

  const rows = Array.from(seen.values()).sort((a, b) => {
    const ta = num(a.tc_kelvin ?? a.tc) ?? -Infinity;
    const tb = num(b.tc_kelvin ?? b.tc) ?? -Infinity;
    if (ta !== tb) return tb - ta;
    const ya = num(a.year ?? a.measurement_year) ?? 0;
    const yb = num(b.year ?? b.measurement_year) ?? 0;
    return yb - ya;
  });

  return (
    <section>
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Evidence ({rows.length} record{rows.length === 1 ? "" : "s"} from{" "}
          {new Set(rows.map((r) => r.paper_id)).size} paper
          {new Set(rows.map((r) => r.paper_id)).size === 1 ? "" : "s"})
        </h2>
        <span className="text-xs text-slate-400">
          the flat columns above are aggregates — each line here is one
          paper&apos;s claim
        </span>
      </div>
      <div className="overflow-x-auto rounded-lg border border-sage-border bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-3 text-right font-medium">Tc (K)</th>
              <th className="px-3 py-3 text-right font-medium">P (GPa)</th>
              <th className="px-3 py-3 text-left font-medium">Sample</th>
              <th className="px-3 py-3 text-left font-medium">Method</th>
              <th className="px-3 py-3 text-left font-medium">Pairing</th>
              <th className="px-3 py-3 text-right font-medium">Year</th>
              <th className="px-3 py-3 text-left font-medium">Paper</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((r, i) => {
              const tc = num(r.tc_kelvin ?? r.tc);
              const year = num(r.year ?? r.measurement_year);
              const p = num(r.pressure_gpa ?? r.pressure);
              const pid = typeof r.paper_id === "string" ? r.paper_id : null;
              const arx = pid ? pid.replace(/^arxiv:/, "") : null;
              const sample =
                typeof r.sample_form === "string" ? r.sample_form : "";
              const methods = Array.from(r._methods as Set<string>).join(", ");
              const pairing =
                typeof r.pairing_symmetry === "string" ? r.pairing_symmetry : "";
              return (
                <tr key={i} className="hover:bg-slate-50">
                  <td className="px-3 py-2.5 text-right tabular-nums font-medium">
                    {tc != null ? tc.toFixed(1) : "—"}
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-slate-600">
                    {p == null
                      ? "—"
                      : p === 0
                        ? "ambient"
                        : p.toFixed(1)}
                  </td>
                  <td className="px-3 py-2.5 text-slate-600">
                    {sample || "—"}
                  </td>
                  <td className="px-3 py-2.5 text-slate-600">
                    {methods || "—"}
                  </td>
                  <td className="px-3 py-2.5 text-slate-600">
                    {pairing || "—"}
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-slate-600">
                    {year ?? "—"}
                  </td>
                  <td className="px-3 py-2.5">
                    {pid && arx ? (
                      // Link directly to the original on arXiv, new
                      // tab. The previous internal /paper/<id> route
                      // had the arXiv id URL-encoded in a way Next
                      // couldn't route (%2F and %3A combined with the
                      // /sclib basePath produced silent no-op clicks
                      // in some browsers). Going straight to the
                      // source also matches "原文地址" — what users
                      // expect when they click a paper citation.
                      <a
                        href={`https://arxiv.org/abs/${arx}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-accent hover:text-accent-deep hover:underline"
                        title={`Open ${pid} on arXiv in a new tab`}
                      >
                        {arx}
                        <span aria-hidden="true" className="text-[0.7em] text-slate-400">↗</span>
                      </a>
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
