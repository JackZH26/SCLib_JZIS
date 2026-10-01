/** The URL owns filtering, ordering and paging; properties retain their individual source scope. */
import type { Metadata } from "next";
import Link from "next/link";
import { listMaterials } from "@/lib/api";
import { MaterialTable } from "@/components/MaterialTable";
import { MaterialsFilters } from "@/components/MaterialsFilters";
import { Pagination } from "@/components/Pagination";
import { absoluteUrl } from "@/lib/seo";
import { materialsHref, materialsPageIndex, materialsPageSize, materialsParams, materialsQueryErrors, materialResultFiltersActive, type MaterialsQuery } from "@/lib/materials-browser";
import "./materials.css";

export const metadata: Metadata = {
  title: "Superconducting materials database",
  description: "Browse superconducting materials, critical temperatures, structures, pressure conditions, and supporting literature.",
  alternates: { canonical: absoluteUrl("/materials") }, openGraph: { url: absoluteUrl("/materials") },
};

export default async function MaterialsPage({ searchParams }: { searchParams: Promise<MaterialsQuery> }) {
  const query = await searchParams;
  const page = materialsPageIndex(query.page);
  const perPage = materialsPageSize(query.per_page);
  const params = materialsParams(query);
  const queryErrors = materialsQueryErrors(query);
  const data = query.structure_phase || queryErrors.length ? null : await listMaterials(params).catch(() => null);
  // A full-document recovery discards stale route state and preserves all other filters.
  const phaseRecoveryHref = `${process.env.NEXT_PUBLIC_BASE_PATH || ""}${materialsHref(query, ["structure_phase"])}`;
  return <main className="materials-browser">
    <header className="materials-heading"><h1>Materials</h1><p>Explore reported superconducting properties, measurement conditions, and their sources.</p></header>
    <MaterialsFilters query={query} pageSize={perPage} />
    {query.structure_phase && <div role="status" className="materials-alert">Reviewed phase filtering is unavailable. Your saved phase filter was not silently ignored. <a href={phaseRecoveryHref}>Remove the phase filter and reload</a>.</div>}
    <div className="materials-results-toolbar">
      <p>{data ? <><strong>{data.total.toLocaleString("en-US")}</strong> materials{data.total > 0 && <span> · {Math.min(page * perPage + 1, data.total).toLocaleString("en-US")}–{Math.min((page + 1) * perPage, data.total).toLocaleString("en-US")} shown</span>}</> : "Results unavailable"}</p>
      <label className="materials-sort"><span>Sort</span><select name="sort" form="materials-filter-form" defaultValue={params.sort}>
        <option value="tc_max">Reported Tc max</option><option value="tc_ambient">Reported ambient Tc</option><option value="arxiv_year">Source year</option><option value="total_papers">Source links</option>
      </select></label>
      <details className="materials-methodology"><summary>Data &amp; methodology</summary><div>
        <p>Family, Tc, pressure and result-evidence filters must match the same extracted result. Unknown pressure does not satisfy a pressure limit. The row shows one Tc result and that result’s conditions.</p>
        <p>Pairing and classification filters use source reports, not family priors. They apply to the material reported-summary scope, not a joint Tc/state result. A false classification filter requires an explicit negative report with method and detection conditions; missing data does not match false.</p>
        <p>Catalogue eligibility and source tier do not establish scientific approval, independent replication or ML readiness. Operational anomaly checks flag records for review; “no findings” is not scientific validation. Retained values are not capped or rewritten.</p>
        <p>Sources count identifiers or legacy links, not independent experiments. Source year comes from the displayed Tc result. Optional classification and structure columns may describe other source results or states. The catalogue maximum remains separate when a filter matches another result.</p>
        <p>{data?.sort_basis === "current_projected_catalogue" ? "Sorting uses current source-scoped catalogue projections." : "Sorting uses legacy catalogue columns; unsupported stored values can affect ranking."} Missing data, unavailable sources and pending review remain distinct. Open Evidence for provenance and status details.</p>
        <p><Link className="site-text-link" href="/materials/source-references">Source reference pilot</Link>: inspect seven CrB₂ paper items and three independent COD structures, with conditions, source links and downloadable metadata.</p>
      </div></details>
    </div>
    {data == null ? <div role="alert" className="materials-error">{queryErrors.length ? queryErrors.join(" ") : query.structure_phase ? "Pending structure proposals cannot be used as reviewed material/state filters." : query.ambient_sc === "false" ? "The negative ambient filter is unsupported: missing ambient evidence is not a negative experiment. Choose Any or Explicit ambient + observed Tc." : "Failed to load materials. Reload the page to try again."}</div> : <>
      <MaterialTable rows={data.results} resultFiltersActive={materialResultFiltersActive(query)} />
      <Pagination total={data.total} limit={perPage} offset={page * perPage} basePath="/materials" searchParams={query} />
    </>}
  </main>;
}
