"use client";

/** Display clusters are coordinate overlaps, never scientific deduplication. */
import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { TimelineCoverage, TimelinePoint, TimelineRecordSummary, TimelineSampling } from "@/lib/api";
import { recordClassification } from "@/lib/result-semantics";
import { pressureLabel } from "@/lib/pressure-semantics";
import { FAMILY_COLORS, familyLabel } from "@/lib/families";
import { FormulaDisplay } from "@/components/FormulaDisplay";
import { knownVisibility, visibilityIsRestricted, visibilityLabel } from "@/lib/material-visibility";
import { clusterTimelinePoints, escapePlotlyHtml, formatTimelineTc, sortedTimelinePoints, timelineOrigin, timelinePointKey, timelineRenderBudget, timelineYearBasis } from "@/lib/timeline-display";

const PlotWebGL = dynamic(() => import("@/components/PlotlyGl2d"), { ssr: false, loading: () => null });
const PlotSvg = dynamic(() => import("@/components/PlotlyBasic2d"), { ssr: false, loading: () => null });
const SVG_POINT_LIMIT = 3000;
const TABLE_PAGE_SIZE = 25;
type TimelineRenderer = "detecting" | "webgl" | "svg";
type TemperatureView = "linear" | "log" | "low";

export function browserSupportsWebGL(): boolean {
  if (typeof document === "undefined") return false;
  try {
    const canvas = document.createElement("canvas");
    const attributes: WebGLContextAttributes = { preserveDrawingBuffer: true, premultipliedAlpha: true };
    return Boolean(canvas.getContext("webgl", attributes));
  } catch { return false; }
}

function pointOriginRole(point: TimelinePoint): string {
  const classification = recordClassification({ result_classification: point });
  return `${timelineOrigin(point)} · ${classification.role} source role`;
}

function numberLabel(value: number): string { return value.toLocaleString("en-US"); }

export function TcTimeline({ points: receivedPoints, coverage, sampling, recordSummary }: {
  points: TimelinePoint[];
  coverage: TimelineCoverage | null;
  sampling?: TimelineSampling;
  recordSummary?: TimelineRecordSummary;
}) {
  const points = useMemo(() => sortedTimelinePoints(receivedPoints.filter(point => !visibilityIsRestricted(point.visibility))), [receivedPoints]);
  const hasRestrictedRecords = points.length !== receivedPoints.length || (recordSummary?.record_candidates ?? []).some(point => visibilityIsRestricted(point.visibility));
  const clusters = useMemo(() => clusterTimelinePoints(points), [points]);
  const [isPlotReady, setIsPlotReady] = useState(false);
  const [renderer, setRenderer] = useState<TimelineRenderer>("detecting");
  const [temperatureView, setTemperatureView] = useState<TemperatureView>("linear");
  const [selectedCluster, setSelectedCluster] = useState<string | null>(null);
  const [page, setPage] = useState(0);

  useEffect(() => { setRenderer(browserSupportsWebGL() ? "webgl" : "svg"); }, []);
  useEffect(() => {
    const showLinkedResult = () => {
      const index = points.findIndex(point => point.point_id && window.location.hash === `#timeline-result-${encodeURIComponent(point.point_id)}`);
      if (index >= 0) { setSelectedCluster(null); setPage(Math.floor(index / TABLE_PAGE_SIZE)); }
    };
    showLinkedResult();
    window.addEventListener("hashchange", showLinkedResult);
    return () => window.removeEventListener("hashchange", showLinkedResult);
  }, [points]);
  const fallBackToSvg = useCallback(() => { setIsPlotReady(false); setRenderer("svg"); }, []);
  const handleInitialized = useCallback((_figure: unknown, graphDiv: Readonly<HTMLElement>) => {
    if (renderer === "webgl" && graphDiv.querySelector(".no-webgl")) { fallBackToSvg(); return; }
    setIsPlotReady(true);
  }, [fallBackToSvg, renderer]);

  const eligibleClusters = useMemo(() => temperatureView === "log" ? clusters.filter(cluster => cluster.tc_kelvin > 0) : clusters, [clusters, temperatureView]);
  const renderClusters = useMemo(() => timelineRenderBudget(eligibleClusters, renderer, SVG_POINT_LIMIT), [eligibleClusters, renderer]);
  const traces = useMemo(() => {
    const grouped = new Map<string, typeof renderClusters>();
    for (const cluster of renderClusters) {
      const group = grouped.get(cluster.family);
      if (group) group.push(cluster); else grouped.set(cluster.family, [cluster]);
    }
    return Array.from(grouped, ([family, subset]) => ({
      type: renderer === "webgl" ? ("scattergl" as const) : ("scatter" as const),
      mode: "markers" as const,
      name: escapePlotlyHtml(family === "mixed" ? "Mixed families (overlap)" : family === "unknown" ? "Other / unknown family" : familyLabel(family)),
      x: subset.map(cluster => cluster.year),
      y: subset.map(cluster => cluster.tc_kelvin),
      customdata: subset.map(cluster => [
        cluster.id,
        escapePlotlyHtml(formatTimelineTc(cluster.tc_kelvin)),
        escapePlotlyHtml(cluster.members.length === 1 ? cluster.members[0].material : `${cluster.members.length} overlapping received results`),
        escapePlotlyHtml(`${cluster.members.length} received results · ${cluster.sourceCount} linked sources`),
        // All source strings are escaped before Plotly parses its limited HTML.
        cluster.members.slice(0, 3).map(point => escapePlotlyHtml(`${point.material}: ${pointOriginRole(point)}; ${visibilityLabel(point.visibility)}; ${pressureLabel(point.pressure_semantics, point.pressure_gpa)}; ${timelineYearBasis(point)}; ${point.paper_id ?? "source unavailable"}`)).join("<br>"),
        cluster.members.length > 3 ? "<br>More received members: click marker and inspect the table." : "",
      ]),
      hovertemplate: "<b>%{customdata[2]}</b><br>Tc = %{customdata[1]}<br>Plotted year = %{x}<br>%{customdata[3]}<br>%{customdata[4]}%{customdata[5]}<br>Click to inspect every received member.<extra></extra>",
      marker: {
        size: subset.map(cluster => Math.min(15, 6 + Math.log2(cluster.members.length) * 2)),
        opacity: 0.75,
        color: FAMILY_COLORS[family] ?? "#64748b",
        symbol: subset.map(cluster => cluster.origin === "Observed" ? "circle" : cluster.origin === "Computed" ? "circle-open" : cluster.origin === "Unknown / conflict" ? "x" : cluster.origin === "Mixed origins" ? "square-open" : "diamond-open"),
        line: { width: 1.3 },
      },
    }));
  }, [renderClusters, renderer]);

  const activeCluster = clusters.find(cluster => cluster.id === selectedCluster);
  const tablePoints = activeCluster?.members ?? points;
  const totalPages = Math.max(1, Math.ceil(tablePoints.length / TABLE_PAGE_SIZE));
  const safePage = Math.min(page, totalPages - 1);
  const shownRows = tablePoints.slice(safePage * TABLE_PAGE_SIZE, (safePage + 1) * TABLE_PAGE_SIZE);
  const Plot = renderer === "webgl" ? PlotWebGL : PlotSvg;
  const minYear = coverage?.year_min ?? points[0]?.year ?? 1990;
  const maxYear = coverage?.year_max ?? points[points.length - 1]?.year ?? new Date().getUTCFullYear();
  const positiveTcs = points.filter(point => point.tc_kelvin > 0).map(point => point.tc_kelvin);
  const minTc = positiveTcs.length ? Math.min(...positiveTcs) : 0.001;
  const maxTc = Math.max(300, ...points.map(point => point.tc_kelvin));
  const yRange = temperatureView === "log" ? [Math.log10(minTc) - 0.1, Math.log10(maxTc) + 0.05] : temperatureView === "low" ? [0, 1] : [0, maxTc * 1.05];

  return <section className="space-y-4" aria-label="Reported Tc results explorer">
    <TimelineSummary summary={hasRestrictedRecords ? undefined : recordSummary} />
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700" role="status">
      {sampling && !hasRestrictedRecords ? <>
        <p>{sampling.is_sampled ? "Display sample" : "Unsampled response selection"}: {numberLabel(sampling.returned_points)} returned results from {numberLabel(sampling.total_points)} eligible reported results. Method: {sampling.method.replaceAll("_", " ")}. This display selection is not a statistically representative sample or an ML dataset.</p>
        <p className="mt-1 text-xs">Selected before pagination: {numberLabel(sampling.selected_points)}. Strata represented: {numberLabel(sampling.strata_represented)} / {numberLabel(sampling.strata_total)}; omitted rare groups: {numberLabel(sampling.rare_groups_omitted)}. Policy: {sampling.policy_version}.</p>
      </> : <p>Server sampling metadata unavailable. {numberLabel(points.length)} received results are inspectable below; no claim of completeness or representativeness is made.</p>}
      {receivedPoints.length !== points.length && <p className="mt-1">{numberLabel(receivedPoints.length - points.length)} restricted results were withheld by the current visibility guard.</p>}
    </div>
    {points.length === 0 ? <p className="rounded-lg border border-dashed border-slate-300 p-8 text-center text-sm">No eligible reported Tc results match this filter.</p> : <>
      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600" aria-label="Result origin symbol legend">
            <span>● Observed</span><span>○ Computed</span><span>◇ Inferred / AI-Proposed</span><span>× Unknown / conflict</span><span>□ Mixed origins</span>
          </div>
          <label className="text-xs font-medium">Temperature view <select className="ml-2 rounded border bg-white p-1" value={temperatureView} onChange={event => setTemperatureView(event.target.value as TemperatureView)}>
            <option value="linear">Linear (K)</option><option value="log">Logarithmic (K)</option><option value="low">Low temperature (0–1 K)</option>
          </select></label>
        </div>
        <p className="px-4 py-2 text-xs text-slate-600">Markers describe reported result origin, not scientific approval. Catalogue eligibility is governed separately; each hover includes its visibility status. Exact year/Tc overlaps are display clusters only: no results are merged. Click a marker or use the overlap selector below to inspect every received member. Server sampling may omit additional results at the same coordinates; cluster counts refer to this received selection. Years are not jittered.</p>
        {points.some(point => !knownVisibility(point.visibility)?.public_catalogue_eligible) && <p className="border-y border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-950">Archive or visibility-unverified points are present in this response. Do not treat them as accepted records or training labels.</p>}
        {renderer === "svg" && <p className="border-y border-amber-100 bg-amber-50 px-4 py-2 text-xs text-amber-900" role="status">WebGL is unavailable; using the SVG compatibility renderer. {renderClusters.length < eligibleClusters.length ? `Renderer budget: showing the first ${numberLabel(renderClusters.length)} of ${numberLabel(eligibleClusters.length)} coordinate clusters in deterministic year/Tc/identity order, not a representative sample. All ${numberLabel(points.length)} received results remain accessible in the table.` : "Every coordinate cluster is rendered."}</p>}
        {temperatureView === "low" && <p className="px-4 py-2 text-xs">The chart is zoomed to 0–1 K. Higher-Tc results remain in the table; use Linear or Logarithmic to see their markers.</p>}
        {temperatureView === "log" && positiveTcs.length !== points.length && <p className="px-4 py-2 text-xs">Zero or nonpositive Tc cannot appear on a logarithmic axis; those results remain in the table.</p>}
        <div className="relative" style={{ minHeight: 560 }}>
          {!isPlotReady && <div className="pointer-events-none absolute right-4 top-2 z-10 rounded bg-white/90 px-3 py-2 text-xs text-slate-500" role="status">Rendering chart… The table is available below.</div>}
          {renderer !== "detecting" && <Plot key={renderer} data={traces} useResizeHandler onInitialized={handleInitialized} onError={renderer === "webgl" ? fallBackToSvg : undefined} onWebGlContextLost={renderer === "webgl" ? fallBackToSvg : undefined}
            onClick={event => { const custom = event.points[0]?.customdata as unknown; if (Array.isArray(custom) && typeof custom[0] === "string") { setSelectedCluster(custom[0]); setPage(0); } }}
            layout={{ autosize: true, height: 560, margin: { l: 70, r: 20, t: 24, b: 85 }, dragmode: "pan", hovermode: "closest", xaxis: { title: { text: "Reported year (basis shown per result)" }, range: [minYear - 1, maxYear + 1], dtick: maxYear - minYear < 15 ? 1 : undefined, gridcolor: "#eef2ee" }, yaxis: { title: { text: "Reported Tc (K)" }, type: temperatureView === "log" ? "log" : "linear", dtick: temperatureView === "log" ? 1 : undefined, range: yRange, minallowed: temperatureView === "log" ? undefined : 0, gridcolor: "#eef2ee" }, legend: { orientation: "h", y: -0.2 }, paper_bgcolor: "#fff", plot_bgcolor: "#fff" }}
            config={{ responsive: true, displayModeBar: true, scrollZoom: true, displaylogo: false, modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d", "toggleSpikelines"], toImageButtonOptions: { filename: "sclib-reported-tc-timeline", format: "png", scale: 2 } }} style={{ width: "100%", height: "560px" }} />}
        </div>
      </div>
      <div className="rounded-lg border border-slate-200 bg-white p-4" id="reported-results">
        <h2 className="text-lg font-semibold">Inspectable reported results</h2>
        <p className="mt-1 text-xs text-slate-600">All {numberLabel(points.length)} received results are available here, including coordinate overlaps and results omitted by the SVG renderer budget. This table does not include results omitted by server sampling. Linked sources count bibliographic identifiers, not independent works. An occurrence count is not independent replication; legacy records remain unreviewed.</p>
        <label className="mt-3 block text-sm">Overlap group <select aria-label="Overlap group" className="ml-2 max-w-full rounded border p-1" value={activeCluster?.id ?? ""} onChange={event => { setSelectedCluster(event.target.value || null); setPage(0); }}>
          <option value="">All received results</option>{clusters.filter(cluster => cluster.members.length > 1).map(cluster => <option key={cluster.id} value={cluster.id}>{cluster.year} · {formatTimelineTc(cluster.tc_kelvin)} · {cluster.members.length} results · {cluster.sourceCount} linked sources</option>)}
          {activeCluster?.members.length === 1 && <option value={activeCluster.id}>{activeCluster.year} · {formatTimelineTc(activeCluster.tc_kelvin)} · 1 result</option>}
        </select></label>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <caption className="pb-2 text-left text-slate-600">{activeCluster ? `${tablePoints.length} members of the selected coordinate cluster` : `${numberLabel(tablePoints.length)} received reported results`} · page {safePage + 1} of {totalPages}</caption>
            <thead className="border-b bg-slate-50"><tr>{["Material / result", "Reported Tc", "Year / basis", "Pressure", "Origin / role", "Source / provenance", "Governance"].map(heading => <th scope="col" className="px-2 py-2" key={heading}>{heading}</th>)}</tr></thead>
            <tbody>{shownRows.map((point, index) => <ResultRow key={`${timelinePointKey(point)}:${safePage * TABLE_PAGE_SIZE + index}`} point={point} />)}</tbody>
          </table>
        </div>
        <nav className="mt-3 flex items-center gap-4 text-sm" aria-label="Reported results pagination"><button className="rounded border px-3 py-1 disabled:opacity-40" disabled={safePage === 0} onClick={() => setPage(safePage - 1)}>Previous results</button><span aria-live="polite">Page {safePage + 1} of {totalPages}</span><button className="rounded border px-3 py-1 disabled:opacity-40" disabled={safePage + 1 === totalPages} onClick={() => setPage(safePage + 1)}>Next results</button></nav>
      </div>
    </>}
  </section>;
}

function TimelineSummary({ summary }: { summary?: TimelineRecordSummary }) {
  if (!summary || summary.scope !== "full_filtered_unsampled") return <p className="text-xs text-slate-600">Full filtered, unsampled summary unavailable. Extrema and material/source totals are not inferred from the display sample.</p>;
  return <aside className="rounded-lg border border-slate-200 bg-white p-4" aria-label="Full filtered unsampled summary">
    <h2 className="text-sm font-semibold">Full filtered dataset · before display sampling</h2>
    <p className="mt-1 text-sm">{numberLabel(summary.total_points)} reported results · {numberLabel(summary.total_materials)} materials · {numberLabel(summary.source_count)} linked sources</p>
    <p className="mt-1 text-xs text-slate-600">Sources count distinct bibliographic identifiers, not independent works or independent replications.</p>
    <p className="mt-1 text-sm">Reported Tc range: {summary.min_tc_kelvin == null ? "unavailable" : formatTimelineTc(summary.min_tc_kelvin)} – {summary.max_tc_kelvin == null ? "unavailable" : formatTimelineTc(summary.max_tc_kelvin)}. These are extrema in this filtered dataset, not world-record claims or independently confirmed Tc values.</p>
    <details className="mt-2 text-xs"><summary className="cursor-pointer">Inspect full-data coverage groups</summary><div className="mt-2 grid gap-3 sm:grid-cols-2">{[["Family", summary.by_family], ["Result origin", summary.by_origin], ["Year basis", summary.by_year_basis], ["Pressure state", summary.by_pressure_state]].map(([label, groups]) => <div key={String(label)}><h3 className="font-medium">{String(label)}</h3><dl>{Object.entries(groups as Record<string, number>).sort(([left], [right]) => left.localeCompare(right, "en")).map(([group, count]) => <div className="flex justify-between gap-3" key={group}><dt>{group.replaceAll("_", " ")}</dt><dd>{numberLabel(count)}</dd></div>)}</dl></div>)}</div></details>
    {summary.record_candidates.length > 0 && <details className="mt-2 text-xs"><summary className="cursor-pointer">Highest reported Tc in this filtered dataset (not a world-record claim)</summary><p className="mt-2">{summary.record_candidates.length} shown of {summary.record_candidate_count ?? summary.record_candidates.length} tied results{summary.record_candidates_truncated ? "; candidate list is truncated" : ""}. These full-data extrema may be absent from the display sample; no scientific acceptance is asserted.</p><ul className="mt-2 space-y-2">{summary.record_candidates.map((point, index) => <li key={`${timelinePointKey(point)}:${index}`}><span className="font-medium">{point.material} · {formatTimelineTc(point.tc_kelvin)}</span> · {point.year} ({timelineYearBasis(point)}) · criterion: {point.result_metadata?.tc_criterion ?? "unknown"} · {pointOriginRole(point)} · {point.paper_id ? <Link className="text-sky-800 underline" href={`/paper/${encodeURIComponent(point.paper_id)}`}>{point.paper_id}</Link> : "source unavailable"}{point.material_id && <> · <Link className="text-sky-800 underline" href={`/materials/${encodeURIComponent(point.material_id)}`}>Material details</Link></>}<div className="break-all text-slate-500">{point.result_metadata?.result_id ?? "result identity unavailable"} · {visibilityLabel(point.visibility)}</div></li>)}</ul></details>}
  </aside>;
}

function ResultRow({ point }: { point: TimelinePoint }) {
  const metadata = point.result_metadata;
  const anchor = point.point_id ? `timeline-result-${encodeURIComponent(point.point_id)}` : undefined;
  return <tr className="border-b align-top" id={anchor}>
    <td className="px-2 py-3"><div>{point.material_id ? <Link className="font-medium text-sky-800 underline" href={`/materials/${encodeURIComponent(point.material_id)}`}><FormulaDisplay formula={point.material} /></Link> : <FormulaDisplay formula={point.material} />}</div><div className="mt-1 break-all text-[10px] text-slate-500">{metadata?.result_id ?? "Result identity unavailable"}{anchor && <a href={`#${anchor}`} className="ml-1 text-sky-800 underline" aria-label={`Link to result ${metadata?.result_id ?? point.point_id}`}>#</a>}</div></td>
    <td className="whitespace-nowrap px-2 py-3">{formatTimelineTc(point.tc_kelvin)}<div className="mt-1 text-slate-500">Criterion: {metadata?.tc_criterion ?? "unknown"}</div></td>
    <td className="px-2 py-3">{point.year}<div className="mt-1 text-slate-500">{timelineYearBasis(point)}</div>{metadata?.source_date && <div>Source date: {metadata.source_date} ({metadata.source_date_basis ?? "basis unavailable"})</div>}{(metadata?.chronology_warnings ?? []).map(warning => <p key={warning} className="mt-1 text-amber-900">Chronology warning: {warning.replaceAll("_", " ")}</p>)}</td>
    <td className="px-2 py-3">{pressureLabel(point.pressure_semantics, point.pressure_gpa)}</td>
    <td className="px-2 py-3">{pointOriginRole(point)}</td>
    <td className="max-w-sm px-2 py-3">{point.paper_id ? <Link className="break-all text-sky-800 underline" href={`/paper/${encodeURIComponent(point.paper_id)}`}>{point.paper_id}</Link> : "Source unavailable"}<details className="mt-2"><summary className="cursor-pointer text-sky-800">Result provenance and state</summary><dl className="mt-2 space-y-1"><div><dt className="inline font-medium">Identity basis: </dt><dd className="inline">{metadata?.identity_basis ?? "unavailable"}</dd></div><div><dt className="inline font-medium">Result revision: </dt><dd className="inline">{metadata?.result_revision ?? "unavailable"}</dd></div><div><dt className="inline font-medium">Source version: </dt><dd className="inline">{metadata?.source_version ?? "unavailable"}</dd></div><div><dt className="inline font-medium">Source occurrences: </dt><dd className="inline">{metadata?.occurrence_count ?? "unavailable"} (not replication)</dd></div></dl><pre className="mt-2 max-w-sm overflow-x-auto whitespace-pre-wrap break-all">{JSON.stringify({ state: metadata?.state ?? {}, source_locator: metadata?.source_locator ?? {} }, null, 2)}</pre></details></td>
    <td className="px-2 py-3">{visibilityLabel(point.visibility)}<div className="mt-1 text-slate-500">{metadata?.review_status === "legacy_unreviewed" ? "Legacy result · unreviewed" : "Result-level review unavailable"}. No scientific acceptance asserted.</div>{metadata?.identity_conflict && <p className="mt-1 text-amber-900">Conflicting occurrences share a supplied result identity.</p>}{(metadata?.identity_warnings ?? []).map(warning => <p key={warning} className="mt-1 text-amber-900">Identity warning: {warning.replaceAll("_", " ")}</p>)}</td>
  </tr>;
}
