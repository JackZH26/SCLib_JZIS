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
import Link from "@/components/AppLink";
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
import { MaterialVisibilityNotice } from "@/components/MaterialVisibilityNotice";
import { eligibleForCatalogueRead, eligibleForScientificSeo, visibilityIsRestricted, visibilityLabel } from "@/lib/material-visibility";
import { MaterialSemanticsMini, MaterialSemanticsPanel } from "@/components/MaterialSemantics";
import { materialSourceCountLabel } from "@/lib/material-semantics";
import { StructureEvidencePanel, StructureEvidenceValue } from "@/components/StructureEvidence";
import { ExternalMaterialReferences } from "@/components/ExternalMaterialReferences";
import { MaterialEnrichment } from "@/components/MaterialEnrichment";
import { ExternalStructureReferences } from "@/components/ExternalStructureReferences";
import { ExternalCalculationReferences } from "@/components/ExternalCalculationReferences";
import { ExternalSuperconReferences } from "@/components/ExternalSuperconReferences";
import { MaterialProviderAvailabilityProvider } from "@/components/MaterialProviderAvailability";
import { materialStudyReading } from "@/lib/material-study-reading";
import { RetainedHc2, RetainedTcCriteria } from "@/components/RetainedRecordScientificFields";
import { retainedHc2 } from "@/lib/material-retained-record";

export const dynamic = "force-dynamic";

type MaterialPageProps = {
  params: Promise<{ id: string }>;
};

const loadMaterial = cache(getMaterial);

function materialDescription(mat: Awaited<ReturnType<typeof getMaterial>>): string {
  if (!eligibleForScientificSeo(mat.visibility)) return `${mat.formula} source-inspection Archive. ${visibilityLabel(mat.visibility)}. Not an accepted superconductivity result.`;
  const properties = [
    mat.family ? familyLabel(mat.family) : null,
    supportedPropertyDescription(mat.property_evidence, "tc_max"),
    `${materialSourceCountLabel(mat.material_semantics, mat.total_papers)} (not independent confirmations)`,
  ].filter(Boolean);
  return `${mat.formula} source-linked material catalogue: ${properties.join(", ")}. Catalogue eligibility is not scientific approval.`;
}

export async function generateMetadata({
  params,
}: MaterialPageProps): Promise<Metadata> {
  const { id: encodedId } = await params;
  const id = decodeURIComponent(encodedId);
  try {
    const mat = await loadMaterial(id);
    const eligible = eligibleForScientificSeo(mat.visibility);
    if (visibilityIsRestricted(mat.visibility)) return { title: "Material not found", robots: { index: false, follow: false } };
    const title = `${mat.formula} ${eligible ? "material catalogue" : "material Archive"}`;
    const description = materialDescription(mat);
    const canonical = absoluteUrl(`/materials/${encodeURIComponent(mat.id)}`);
    return {
      title,
      description,
      robots: eligible ? undefined : { index: false, follow: false, noarchive: true },
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
  if (visibilityIsRestricted(mat.visibility)) notFound();
  const scientificSeoEligible = eligibleForScientificSeo(mat.visibility);
  const catalogueReadEligible = eligibleForCatalogueRead(mat.visibility);
  const hydrideParameters =
    mat.family === "hydride" && catalogueReadEligible ? await getMaterialHydrideParameters(id) : [];

  const flags: [string, boolean | null][] = [
    ["Catalogue risk flag: disputed", mat.disputed],
    ["Catalogue risk flag: retracted", mat.retracted],
  ];
  const activeFlags = flags.filter(([, v]) => v === true);
  const canonical = absoluteUrl(`/materials/${encodeURIComponent(mat.id)}`);
  const materialStructuredData = {
    "@context": "https://schema.org",
    "@type": "Dataset",
    name: `${mat.formula} ${scientificSeoEligible ? "material catalogue" : "material Archive"}`,
    description: materialDescription(mat),
    url: canonical,
    identifier: mat.id,
    keywords: [
      "superconductivity",
      mat.formula,
      mat.family,
      mat.subfamily,
    ].filter(Boolean),
    variableMeasured: scientificSeoEligible ? [
      propertyJsonLd(mat.property_evidence, "tc_max"),
      propertyJsonLd(mat.property_evidence, "tc_ambient"),
    ].filter(Boolean) : [],
    measurementTechnique: "Scientific literature extraction; result origin is not scientific validation",
    ...(scientificSeoEligible ? { includedInDataCatalog: {
      "@type": "DataCatalog",
      name: "SCLib — JZIS Superconductivity Library",
      url: absoluteUrl("/materials"),
    } } : {}),
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
        <div className="mt-2 flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
          <h1 className="min-w-0 max-w-full break-words text-3xl font-bold tracking-tight">
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

      <MaterialVisibilityNotice visibility={mat.visibility} quietIfClear />
      <ScientificAnomalyNotice review={mat.anomaly_review} quietIfClear />
      <details className="border-y border-sage-border py-3 text-sm text-slate-600">
        <summary className="cursor-pointer font-medium">How to read these data</summary>
        <p className="mt-3 max-w-4xl">Each property selection has its own source, conditions and result identity. Expand a value to inspect them. Observed and Computed describe the source report; catalogue eligibility and a clear anomaly check do not establish scientific validity. Different properties need not describe the same sample or state.</p>
        <p className="mt-2 max-w-4xl">Missing pressure is not ambient pressure. Text structure claims remain separate from validated coordinates. A source-linked value does not override a material review hold. Source recovery candidates and external calculated references do not replace selected measurements.</p>
      </details>

      <section className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <PropertyEvidenceFact evidence={mat.property_evidence} field="tc_max" />
        <PropertyEvidenceFact evidence={mat.property_evidence} field="tc_ambient" />
        <Fact label="Catalogue year" value={String(mat.arxiv_year ?? "—")} />
        <Fact label="Source links · not replications" value={materialSourceCountLabel(mat.material_semantics, mat.total_papers)} />
      </section>
      {catalogueReadEligible && (() => {
        const reading = materialStudyReading(mat.id, selectedProperty(mat.property_evidence, "tc_max"));
        return reading ? <aside className="min-w-0 rounded-lg border border-sage-border bg-sage-surface p-4" aria-label="Related paper context">
          <h2 className="text-sm font-semibold">Related paper context</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6">{reading.note}</p>
          <a href={reading.href} className="site-text-link mt-2 inline-block text-sm">{reading.label}</a>
          {reading.companion && <a href={reading.companion.href} className="site-text-link mt-2 block w-fit text-sm">{reading.companion.label}</a>}
          <p className="mt-2 text-xs leading-5 text-sage-muted">Captured paper reading; selected catalogue values remain separate.</p>
        </aside> : null;
      })()}
      <details className="rounded-lg border border-sage-border bg-white p-4"><summary className="cursor-pointer text-sm font-medium">Reported classifications and mechanism evidence</summary><div className="mt-4"><MaterialSemanticsPanel semantics={mat.material_semantics} /></div></details>
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
                  <th className="px-3 py-3 text-right font-medium">Source links</th>
                  <th className="px-3 py-3 text-left font-medium">Reported classifications</th>
                  <th className="px-3 py-3 text-right font-medium">Doping</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {mat.variants.filter(v => !visibilityIsRestricted(v.visibility)).map((v) => (
                  <tr key={v.id} className="hover:bg-slate-50">
                    <td className="px-3 py-2.5">
                      <Link
                        href={`/materials/${encodeURIComponent(v.id)}`}
                        className="font-medium text-accent-deep hover:underline"
                      >
                        <FormulaDisplay formula={v.formula} />
                      </Link>
                      <ScientificAnomalyNotice review={v.anomaly_review} compact quietIfClear />
                      <MaterialVisibilityNotice visibility={v.visibility} compact quietIfClear />
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums">
                      <PropertyEvidenceValue evidence={v.property_evidence} field="tc_max" compact includeUnit={false} />
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-slate-600">
                      <PropertyEvidenceValue evidence={v.property_evidence} field="tc_ambient" compact includeUnit={false} />
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-slate-600">
                      {materialSourceCountLabel(v.material_semantics, v.total_papers)}
                    </td>
                    <td className="min-w-[12rem] px-3 py-2.5"><MaterialSemanticsMini semantics={v.material_semantics} /><div className="mt-2"><span className="text-xs text-slate-500">Structure association</span><StructureEvidenceValue evidence={v.structure_evidence} /></div></td>
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
      <RawScientificArchive archive={mat.raw_archive} visibility={mat.visibility} />

      {mat.family === "hydride" && !catalogueReadEligible && <p className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">Specialized hydride results are not loaded for this Archive record. An alternate endpoint cannot bypass its review status.</p>}

      {hydrideParameters.length > 0 && (
        <HydrideParametersTable rows={hydrideParameters} />
      )}

      <details className="rounded-lg border border-sage-border bg-white p-4"><summary className="cursor-pointer text-sm font-medium">Structure and lattice evidence</summary><div className="mt-4 space-y-6"><StructureEvidencePanel evidence={mat.structure_evidence} /><PropertyEvidenceSection title="Lattice parameters — separate source selections" fields={STRUCTURE_FIELDS.filter(field => field === "lattice_params")} evidence={mat.property_evidence} /></div></details>
      <details className="rounded-lg border border-sage-border bg-white p-4"><summary className="cursor-pointer text-sm font-medium">Superconducting parameters</summary><div className="mt-4 space-y-6"><PropertyEvidenceSection title="Superconducting parameters" fields={SC_FIELDS.filter(field => field !== "pairing_symmetry")} evidence={mat.property_evidence} /><JointEpcNotice evidence={mat.property_evidence} /></div></details>
      <details className="rounded-lg border border-sage-border bg-white p-4"><summary className="cursor-pointer text-sm font-medium">Competing orders</summary><div className="mt-4"><PropertyEvidenceSection title="Competing orders" fields={ORDER_FIELDS} evidence={mat.property_evidence} /></div></details>
      <details className="rounded-lg border border-sage-border bg-white p-4"><summary className="cursor-pointer text-sm font-medium">Samples and pressure evidence</summary><div className="mt-4"><PropertyEvidenceSection title="Samples & pressure" fields={SAMPLE_FIELDS} evidence={mat.property_evidence} /></div></details>
      {catalogueReadEligible && <MaterialProviderAvailabilityProvider materialId={mat.id}>
        <MaterialEnrichment materialId={mat.id} />
        <ExternalSuperconReferences materialId={mat.id} />
        <ExternalMaterialReferences materialId={mat.id} />
        <ExternalStructureReferences materialId={mat.id} />
        <ExternalCalculationReferences materialId={mat.id} />
      </MaterialProviderAvailabilityProvider>}
      <p className="text-xs text-sage-muted"><Link href={`/dashboard/research/material-field-cases?material=${encodeURIComponent(mat.id)}`} prefetch={false} className="text-accent-deep underline">Open private field cases for this material</Link> · Authorized workspace; source proposals remain pending.</p>

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
            {rows.filter(r => !visibilityIsRestricted(r.visibility)).map((r) => {
              const paperRef = paperReference(r.paper_id);
              return (
                <tr key={r.id} className="hover:bg-slate-50">
                  <td className="px-3 py-2.5 font-medium text-slate-800">
                    <FormulaDisplay formula={r.formula} />
                    <MaterialVisibilityNotice visibility={r.visibility} compact />
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
  const rowsWithMethods = records.filter(record => !visibilityIsRestricted(record.visibility)).map<Record<string, unknown> & { _methods: Set<string> }>((record) => ({
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
  const hasRetainedHc2 = rows.some(record => retainedHc2(record) !== null);

  return (
    <section>
      <div className="mb-3 space-y-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Evidence ({rows.length} record{rows.length === 1 ? "" : "s"} from{" "}
          {new Set(rows.map((r) => r.paper_id).filter(id => typeof id === "string" && id.trim())).size} linked bibliographic IDs)
        </h2>
        <p className="text-xs text-slate-500">Each row is a retained extraction with its own conditions and source.</p>
        <p className="max-w-4xl text-xs leading-5 text-sage-muted">Tc type and lexical criterion remain separate retained fields.{hasRetainedHc2 && " Hc2 is a record field; sharing a row does not establish a joint measurement, its probe method or Hc2(0)."}</p>
        <details className="text-xs text-slate-500">
          <summary className="cursor-pointer">How to read these records</summary>
          <p className="mt-2 max-w-3xl">Retained values and catalogue eligibility do not establish scientific approval. Operational anomaly checks flag records for review; no findings is not scientific validation. Repeated reports are not independent replications. Open each row’s review details or the retained-record Archive to inspect the supplied policy metadata.</p>
        </details>
      </div>
      <div role="region" aria-label="Scrollable retained evidence" tabIndex={0} className="overflow-x-auto rounded-lg border border-sage-border bg-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
        <table className="w-full min-w-[56rem] text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-3 text-right font-medium">Retained Tc (K)</th>
              <th className="px-3 py-3 text-left font-medium">Record origin / role</th>
              <th className="px-3 py-3 text-left font-medium">Review</th>
              <th className="px-3 py-3 text-right font-medium">P (GPa)</th>
              <th className="px-3 py-3 text-left font-medium">Sample</th>
              <th className="px-3 py-3 text-left font-medium">Method</th>
              {hasRetainedHc2 && <th className="px-3 py-3 text-left font-medium">Retained Hc2</th>}
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
                    <RetainedTcCriteria record={r} />
                  </td>
                  <td className="px-3 py-2.5 text-xs text-slate-600" title={classification.version}>
                    <span className="block">{classification.status === "conflicted" ? "Classification conflict" : classification.origin}</span>
                    <span className="text-slate-400">{classification.role} source role</span>
                  </td>
                  <td className="px-3 py-2.5"><RecordAnomalyReview assessment={r.anomaly_review} compact /><MaterialVisibilityNotice visibility={r.visibility} compact quietIfClear scope={objectValue(r.visibility).material_link_status ? "source occurrence" : "material"} /></td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-slate-600">
                    {pressureLabel(r.pressure_semantics, p)}
                  </td>
                  <td className="px-3 py-2.5 text-slate-600">
                    {sample || "—"}
                  </td>
                  <td className="px-3 py-2.5 text-slate-600">
                    {methods || "—"}
                  </td>
                  {hasRetainedHc2 && <td className="px-3 py-2.5 text-slate-600"><RetainedHc2 record={r} /></td>}
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
