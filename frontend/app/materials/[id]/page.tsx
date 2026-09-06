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
 * Scientific catalogue values require a current atomic evidence selection.
 * Missing support stays visible as unavailable, never a legacy scalar fallback.
 */
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cache } from "react";
import { getMaterial, getMaterialHydrideParameters } from "@/lib/api";
import type { HydrideTcParameterRecord } from "@/lib/api";
import { ApiError } from "@/lib/api";
import { familyLabel } from "@/lib/families";
import { absoluteUrl, serializeJsonLd } from "@/lib/seo";
import { BookmarkButton } from "@/components/BookmarkButton";
import { FormulaDisplay } from "@/components/FormulaDisplay";
import { recordClassification, scientificNumber } from "@/lib/result-semantics";
import { pressureLabel } from "@/lib/pressure-semantics";
import { JointEpcNotice, PropertyEvidenceFact, PropertyEvidenceSection, PropertyEvidenceValue } from "@/components/PropertyEvidence";
import { RawScientificArchive, RecordAnomalyReview, ScientificAnomalyNotice } from "@/components/ScientificAnomalies";
import { evidenceText, objectValue, ORDER_FIELDS, propertyJsonLd, SAMPLE_FIELDS, SC_FIELDS, selectedProperty, STRUCTURE_FIELDS, supportedPropertyDescription } from "@/lib/property-evidence";

type MaterialPageProps = {
  params: Promise<{ id: string }>;
};

const loadMaterial = cache(getMaterial);

function materialDescription(mat: Awaited<ReturnType<typeof getMaterial>>): string {
  const properties = [
    mat.family ? familyLabel(mat.family) : null,
    supportedPropertyDescription(mat.property_evidence, "tc_max"),
    mat.total_papers === 1 ? "1 indexed paper" : `${mat.total_papers} indexed papers`,
  ].filter(Boolean);
  return `${mat.formula} superconducting material data: ${properties.join(", ")}.`;
}

export async function generateMetadata({
  params,
}: MaterialPageProps): Promise<Metadata> {
  const { id: encodedId } = await params;
  const id = decodeURIComponent(encodedId);
  try {
    const mat = await loadMaterial(id);
    const title = `${mat.formula} superconducting material`;
    const description = materialDescription(mat);
    const canonical = absoluteUrl(`/materials/${encodeURIComponent(mat.id)}`);
    return {
      title,
      description,
      alternates: { canonical },
      openGraph: {
        type: "website",
        url: canonical,
        title,
        description,
      },
      twitter: { card: "summary", title, description },
    };
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return {
        title: "Material not found",
        robots: { index: false, follow: false },
      };
    }
    throw error;
  }
}

export default async function MaterialDetailPage({ params }: MaterialPageProps) {
  const { id: encodedId } = await params;
  const id = decodeURIComponent(encodedId);
  let mat;
  try {
    mat = await loadMaterial(id);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  const hydrideParameters =
    mat.family === "hydride" ? await getMaterialHydrideParameters(id) : [];

  const flags: [string, boolean | null][] = [
    ["Catalogue risk flag: disputed", mat.disputed],
    ["Catalogue risk flag: retracted", mat.retracted],
  ];
  const activeFlags = flags.filter(([, v]) => v === true);
  const canonical = absoluteUrl(`/materials/${encodeURIComponent(mat.id)}`);
  const materialStructuredData = {
    "@context": "https://schema.org",
    "@type": "Dataset",
    name: `${mat.formula} superconducting material data`,
    description: materialDescription(mat),
    url: canonical,
    identifier: mat.id,
    keywords: [
      "superconductivity",
      mat.formula,
      mat.family,
      mat.subfamily,
    ].filter(Boolean),
    variableMeasured: [
      propertyJsonLd(mat.property_evidence, "tc_max"),
      propertyJsonLd(mat.property_evidence, "tc_ambient"),
    ].filter(Boolean),
    measurementTechnique: "Scientific literature extraction; result origin is not scientific validation",
    includedInDataCatalog: {
      "@type": "DataCatalog",
      name: "SCLib — JZIS Superconductivity Library",
      url: absoluteUrl("/materials"),
    },
    creator: {
      "@type": "Organization",
      name: "JZ Institute of Science",
    },
  };

  return (
    <main className="space-y-8">
      <script
        id="sclib-material-structured-data"
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: serializeJsonLd(materialStructuredData),
        }}
      />
      <div>
        <Link href="/materials" className="text-sm text-slate-500 hover:underline">
          ← Materials
        </Link>
        <div className="mt-2 flex items-start justify-between gap-4">
          <h1 className="text-3xl font-bold tracking-tight">
            <FormulaDisplay formula={mat.formula} />
          </h1>
          <div className="shrink-0 pt-1">
            <BookmarkButton targetType="material" targetId={mat.id} />
          </div>
        </div>
        <p className="mt-1 text-sm text-slate-600">
          {[
            mat.family ? familyLabel(mat.family) : null,
            mat.subfamily,
          ]
            .filter(Boolean)
            .join(" · ") || "—"}
        </p>
        {mat.mp_id && (
          // Cross-link to Materials Project for DFT structure / band data.
          // Rendered only when the Phase B sync (scripts/sync_mp_ids.py)
          // matched this formula. The "+N polymorphs" hint surfaces
          // mp_alternate_ids when the formula has multiple structures
          // (e.g. high-pressure phases) so the reader knows the chosen
          // mp_id is just the lowest-energy one.
          <div className="mt-3">
            <a
              href={`https://next-gen.materialsproject.org/materials/${mat.mp_id}`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-md border border-sage-border bg-white px-3 py-1.5 text-xs font-medium text-accent-deep shadow-sm transition-colors hover:bg-[rgba(58,125,92,0.06)]"
            >
              <span>Formula-matched Materials Project entry</span>
              <span className="font-mono text-[10px] text-slate-500">
                {mat.mp_id}
              </span>
              {mat.mp_alternate_ids.length > 1 && (
                <span className="text-[10px] text-slate-500">
                  · +{mat.mp_alternate_ids.length - 1} polymorph
                  {mat.mp_alternate_ids.length - 1 === 1 ? "" : "s"}
                </span>
              )}
              <svg
                width="11"
                height="11"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M7 17L17 7M9 7h8v8" />
              </svg>
            </a>
          </div>
        )}
        {mat.mp_id && <p className="mt-1 text-xs text-slate-500">Formula-level cross-reference; correspondence to a measured sample, pressure state or selected structure is not established by this link.</p>}
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

      <p className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">These are catalogue property selections, not a joint observation or an ML feature row. Expand each value for its contributing result, source and conditions. Observed/Computed labels describe the source record, not independent validation of each property. Missing source/state associations are not filled from another record. Family labels are catalogue classifications, not measurement evidence.</p>
      <ScientificAnomalyNotice review={mat.anomaly_review} />

      <section className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <PropertyEvidenceFact evidence={mat.property_evidence} field="tc_max" />
        <PropertyEvidenceFact evidence={mat.property_evidence} field="tc_ambient" />
        <Fact label="arXiv year" value={String(mat.arxiv_year ?? "—")} />
        <Fact label="Papers" value={mat.total_papers.toString()} />
      </section>
      {(selectedProperty(mat.property_evidence, "tc_max_experimental") || selectedProperty(mat.property_evidence, "tc_max_theoretical")) && (
        <section className="-mt-2 grid grid-cols-2 gap-4 md:grid-cols-4">
          <PropertyEvidenceFact evidence={mat.property_evidence} field="tc_max_experimental" />
          <PropertyEvidenceFact evidence={mat.property_evidence} field="tc_max_theoretical" />
        </section>
      )}

      {/* P2: Doping variants table */}
      {mat.variants && mat.variants.length > 0 && (
        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Doping variants ({mat.variants.length})
          </h2>
          <div className="overflow-x-auto rounded-lg border border-sage-border bg-white">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-3 py-3 text-left font-medium">Formula</th>
                  <th className="px-3 py-3 text-right font-medium">Tc max (K)</th>
                  <th className="px-3 py-3 text-right font-medium">Tc amb. (K)</th>
                  <th className="px-3 py-3 text-right font-medium">Papers</th>
                  <th className="px-3 py-3 text-right font-medium">Doping</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {mat.variants.map((v) => (
                  <tr key={v.id} className="hover:bg-slate-50">
                    <td className="px-3 py-2.5">
                      <Link
                        href={`/materials/${encodeURIComponent(v.id)}`}
                        className="font-medium text-accent-deep hover:underline"
                      >
                        <FormulaDisplay formula={v.formula} />
                      </Link>
                      <ScientificAnomalyNotice review={v.anomaly_review} compact />
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums">
                      <PropertyEvidenceValue evidence={v.property_evidence} field="tc_max" compact includeUnit={false} />
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-slate-600">
                      <PropertyEvidenceValue evidence={v.property_evidence} field="tc_ambient" compact includeUnit={false} />
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-slate-600">
                      {v.total_papers}
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-slate-600">
                      <PropertyEvidenceValue evidence={v.property_evidence} field="doping_level" compact />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
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
      <RawScientificArchive archive={mat.raw_archive} />

      {hydrideParameters.length > 0 && (
        <HydrideParametersTable rows={hydrideParameters} />
      )}

      <PropertyEvidenceSection title="Structure — separate source selections" fields={STRUCTURE_FIELDS} evidence={mat.property_evidence} />
      <PropertyEvidenceSection title="Superconducting parameters" fields={SC_FIELDS} evidence={mat.property_evidence} />
      <JointEpcNotice evidence={mat.property_evidence} />
      <PropertyEvidenceSection title="Competing orders" fields={ORDER_FIELDS} evidence={mat.property_evidence} />
      <PropertyEvidenceSection title="Samples & pressure" fields={SAMPLE_FIELDS} evidence={mat.property_evidence} />
      <PropertyEvidenceSection title="Source-linked classifications" fields={["is_unconventional", "has_competing_order"]} evidence={mat.property_evidence} />

    </main>
  );
}

function HydrideParametersTable({
  rows,
}: {
  rows: HydrideTcParameterRecord[];
}) {
  return (
    <section>
      <div className="mb-3 flex items-baseline justify-between gap-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Hydride Tc parameters ({rows.length})
        </h2>
        <span className="text-xs text-slate-400">
          independent NER enrichment for pressure, λ, μ*, and ω_log
        </span>
      </div>
      <p className="mb-3 rounded border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">Independent extraction leads, not association-complete EPC inputs. A row does not establish a shared structure/state/run for λ, μ* and ω_log. Expand each extracted field for source context; these values are not used as catalogue headline selections or model-ready pairs.</p>
      <div className="overflow-x-auto rounded-lg border border-sage-border bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-3 text-left font-medium">Formula</th>
              <th className="px-3 py-3 text-right font-medium">Reported Tc</th>
              <th className="px-3 py-3 text-right font-medium">P (GPa)</th>
              <th className="px-3 py-3 text-right font-medium normal-case">λ</th>
              <th className="px-3 py-3 text-right font-medium normal-case">μ*</th>
              <th className="px-3 py-3 text-right font-medium normal-case">
                Reported ω_log
              </th>
              <th className="px-3 py-3 text-left font-medium">Method</th>
              <th className="px-3 py-3 text-right font-medium">Year</th>
              <th className="px-3 py-3 text-left font-medium">Paper</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((r) => {
              const paperRef = paperReference(r.paper_id);
              return (
                <tr key={r.id} className="hover:bg-slate-50">
                  <td className="px-3 py-2.5 font-medium text-slate-800">
                    <FormulaDisplay formula={r.formula} />
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums">
                    <HydrideExtractedField row={r} field="tc_kelvin" fallback={r.tc_kelvin} unit="K" />
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-slate-600">
                    {pressureLabel(r.pressure_semantics, r.pressure_gpa)}
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-slate-600">
                    <HydrideExtractedField row={r} field="lambda_eph" fallback={r.lambda_eph} />
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-slate-600">
                    <HydrideExtractedField row={r} field="mu_star" fallback={r.mu_star} />
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-slate-600">
                    <HydrideExtractedField row={r} field="omega_log_k" fallback={r.omega_log_k} unit="K" />
                  </td>
                  <td className="px-3 py-2.5 text-slate-600">
                    {r.method || r.evidence_type || "—"}
                    {r.validation_flags.length > 0 && (
                      <span
                        className="ml-2 inline-flex rounded-full border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700"
                        title={r.validation_flags.join(", ")}
                      >
                        check
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-slate-600">
                    {r.year ?? "—"}
                  </td>
                  <td className="px-3 py-2.5">
                    {paperRef?.href ? (
                      <a
                        href={paperRef.href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-accent hover:text-accent-deep hover:underline"
                        title={paperRef.title}
                      >
                        {paperRef.label}
                        <span aria-hidden="true" className="text-[0.7em] text-slate-400">↗</span>
                      </a>
                    ) : paperRef ? (
                      <span className="text-slate-600">{paperRef.label}</span>
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

function HydrideExtractedField({ row, field, fallback, unit = "" }: { row: HydrideTcParameterRecord; field: string; fallback: number | null; unit?: string }) {
  const proposal = objectValue(objectValue(row.provenance).extraction_proposal);
  const quantities = objectValue(proposal.scientific_values);
  let raw = objectValue(quantities[field]);
  if (field === "omega_log_k" && raw.raw_value == null) raw = objectValue(quantities.omega_log_source_value);
  const rawText = evidenceText(raw.raw_value) ?? (Array.isArray(raw.raw_value) && raw.raw_value.length === 2 && raw.raw_value.every(value => evidenceText(value) !== null) ? `[${raw.raw_value.map(evidenceText).join(", ")}]` : null);
  const displayed = rawText ? `${rawText}${typeof raw.raw_value === "number" && evidenceText(raw.raw_unit) ? ` ${evidenceText(raw.raw_unit)}` : ""}` : fallback == null ? "—" : `${scientificNumber(fallback)}${unit ? ` ${unit}` : ""}`;
  return <details className="text-xs">
    <summary className="cursor-pointer"><span>{displayed}</span><span className="block text-[10px] text-slate-500">{rawText ? "Raw extraction" : fallback == null ? "Not reported" : "Legacy extraction · unverified precision"}</span></summary>
    <dl className="mt-2 max-w-sm space-y-1 text-left font-normal text-slate-600">
      <div><dt className="inline">Enrichment record: </dt><dd className="inline">{row.id}</dd></div>
      <div><dt className="inline">Paper: </dt><dd className="inline">{row.paper_id}</dd></div>
      <div><dt className="inline">Source section: </dt><dd className="inline">{row.source_section ?? "Not reported"}</dd></div>
      <div><dt className="inline">Method: </dt><dd className="inline">{row.method ?? "Not reported"}</dd></div>
      <div><dt className="inline">Source unit: </dt><dd className="inline">{evidenceText(raw.raw_unit) ?? "Not reported in this proposal"}</dd></div>
      <div><dt className="inline">Extraction version: </dt><dd className="inline">{row.prompt_version}</dd></div>
    </dl>
    <p className="mt-2 max-w-sm text-left font-normal text-slate-500">No paired-run/state verification is established by this extraction record. A parser or numerical consistency check is not independent source validation.</p>
  </details>;
}

/**
 * The "evidence trail" behind the flat columns. Each row is one
 * paper's claim about this material: Tc at some pressure on some
 * sample form reported with some method. Equal scalar values alone
 * do not establish that two records describe the same result.
 *
 * Sorted most-informative first: Tc descending, then year descending
 * (prefer latest measurement when Tcs tie).
 */
function RecordsTable({
  records,
}: {
  records: Record<string, unknown>[];
}) {
  // Preserve individual extracted results: equal Tc/pressure is not enough
  // to merge sample, method, origin, criterion or source-role evidence.
  const rowsWithMethods = records.map<Record<string, unknown> & { _methods: Set<string> }>((record) => ({
    ...record,
    _methods: new Set(
      typeof record.measurement === "string" && record.measurement.toLowerCase() !== "unknown"
        ? [record.measurement] : [],
    ),
  }));

  const rows = rowsWithMethods.sort((a, b) => {
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
          retained extraction records, including proposals that may need review;
          repeated reports are not independent replications
        </span>
      </div>
      <div className="overflow-x-auto rounded-lg border border-sage-border bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-3 text-right font-medium">Retained Tc (K)</th>
              <th className="px-3 py-3 text-left font-medium">Record origin / role</th>
              <th className="px-3 py-3 text-left font-medium">Review status</th>
              <th className="px-3 py-3 text-right font-medium">P (GPa)</th>
              <th className="px-3 py-3 text-left font-medium">Sample</th>
              <th className="px-3 py-3 text-left font-medium">Method</th>
              <th className="px-3 py-3 text-left font-medium">Pairing</th>
              <th className="px-3 py-3 text-right font-medium">Year</th>
              <th className="px-3 py-3 text-center font-medium" title="Source tier is not experimental confirmation">Source tier</th>
              <th className="px-3 py-3 text-left font-medium">Paper</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((r, i) => {
              const tc = num(r.tc_kelvin ?? r.tc);
              const classification = recordClassification(r);
              const year = num(r.year ?? r.measurement_year);
              const p = num(r.pressure_gpa ?? r.pressure);
              const pid = typeof r.paper_id === "string" ? r.paper_id : null;
              const paperRef = paperReference(pid);
              const sample =
                typeof r.sample_form === "string" ? r.sample_form : "";
              const methods = Array.from(r._methods as Set<string>).join(", ");
              const pairing =
                typeof r.pairing_symmetry === "string" ? r.pairing_symmetry : "";
              return (
                <tr key={i} className="hover:bg-slate-50">
                  <td className="px-3 py-2.5 text-right tabular-nums font-medium">
                    {tc != null ? scientificNumber(tc) : "—"}
                    <span className="block text-[10px] font-normal text-slate-500">Stored extraction, not approval</span>
                  </td>
                  <td className="px-3 py-2.5 text-xs text-slate-600" title={classification.version}>
                    <span className="block">{classification.status === "conflicted" ? "Classification conflict" : classification.origin}</span>
                    <span className="text-slate-400">{classification.role} source role</span>
                  </td>
                  <td className="px-3 py-2.5"><RecordAnomalyReview assessment={r.anomaly_review} /></td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-slate-600">
                    {pressureLabel(r.pressure_semantics, p)}
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
                  <td className="px-3 py-2.5 text-center">
                    {(() => {
                      const tier = typeof r.credibility_tier === "string" ? r.credibility_tier : null;
                      if (!tier) return "—";
                      const cls = tier === "T1" ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                        : tier === "T2" ? "bg-blue-50 text-blue-700 border-blue-200"
                        : "bg-slate-50 text-slate-500 border-slate-200";
                      return <span className={`inline-flex items-center rounded-full border px-1.5 py-0.5 text-[10px] font-medium ${cls}`}>{tier}</span>;
                    })()}
                  </td>
                  <td className="px-3 py-2.5">
                    {paperRef?.href ? (
                      <a
                        href={paperRef.href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-accent hover:text-accent-deep hover:underline"
                        title={paperRef.title}
                      >
                        {paperRef.label}
                        <span aria-hidden="true" className="text-[0.7em] text-slate-400">↗</span>
                      </a>
                    ) : paperRef ? (
                      <span className="text-slate-600">{paperRef.label}</span>
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

function paperReference(paperId: string | null): {
  label: string;
  href?: string;
  title: string;
} | null {
  const id = paperId?.trim();
  if (!id) return null;
  if (id.startsWith("aps:")) {
    const doi = id.slice(4);
    return {
      label: `DOI: ${doi}`,
      href: `https://doi.org/${doi}`,
      title: `Open DOI ${doi} in a new tab`,
    };
  }
  if (id.startsWith("doi:")) {
    const doi = id.slice(4);
    return {
      label: `DOI: ${doi}`,
      href: `https://doi.org/${doi}`,
      title: `Open DOI ${doi} in a new tab`,
    };
  }
  if (id.startsWith("arxiv:")) {
    const arxivId = id.slice(6);
    return {
      label: arxivId,
      href: `https://arxiv.org/abs/${arxivId}`,
      title: `Open arXiv ${arxivId} in a new tab`,
    };
  }
  if (id.startsWith("nims:")) {
    return {
      label: `NIMS: ${id.slice(5)}`,
      title: `NIMS reference ${id.slice(5)}`,
    };
  }
  return { label: id, title: id };
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

function num(x: unknown): number | null {
  if (typeof x === "number") return x;
  if (typeof x === "string" && x.trim() !== "") {
    const n = Number(x);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}
