"use client";

import { useEffect, useRef, useState } from "react";
import {
  getRpsDetail, getRpsPage, getRpsReleases, PHYSICAL_DIMENSIONS, verifyRpsDetail, verifyRpsPage,
  type RpsDetail, type RpsPage, type RpsRelease, type RpsRow,
} from "@/lib/research-priority";

const number = (value: number | null) => value === null ? "—" : value.toLocaleString("en-US", { maximumFractionDigits: 2 });
const signed = (value: number | null) => value === null ? "—" : `${value > 0 ? "+" : ""}${number(value)}`;
const explanationLabels: Record<string, string> = {
  missing_support: "Missing support — not adverse evidence",
  assessed_support: "Supporting evidence", adverse_evidence: "Adverse evidence",
  mixed_evidence: "Mixed evidence", neutral_evidence: "Neutral evidence",
  evidence_polarity_unclassified: "Evidence direction not classified",
  uncertainty_discount: "Conservative uncertainty discount",
};

export function ResearchPriorityBoard() {
  const [releases, setReleases] = useState<RpsRelease[]>([]);
  const [selected, setSelected] = useState("");
  const [page, setPage] = useState<RpsPage | null>(null);
  const [rows, setRows] = useState<RpsRow[]>([]);
  const [group, setGroup] = useState("discovery");
  const [status, setStatus] = useState<"loading" | "ready" | "empty" | "error">("loading");
  const [error, setError] = useState("");
  const [moreBusy, setMoreBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const generation = useRef(0);

  useEffect(() => {
    let alive = true;
    setStatus("loading"); setError(""); setRows([]); setPage(null);
    getRpsReleases().then(catalog => {
      if (!alive) return;
      if (catalog.schema_version !== "rps-catalog/1.2") throw new Error("Unsupported release contract");
      setReleases(catalog.items);
      setSelected(catalog.items[0]?.id ?? "");
      if (!catalog.items.length) setStatus("empty");
    }).catch(() => { if (alive) { setStatus("error"); setError("The RPS publication service is unavailable. No legacy score has been substituted."); } });
    return () => { alive = false; };
  }, [retry]);

  useEffect(() => {
    const release = releases.find(item => item.id === selected);
    if (!release) return;
    const current = ++generation.current;
    setStatus("loading"); setRows([]); setPage(null); setError(""); setMoreBusy(false);
    getRpsPage(release.id, 0, group).then(result => {
      if (current !== generation.current) return;
      verifyRpsPage(result, release, 0, [], group);
      setPage(result); setRows(result.items); setStatus("ready");
    }).catch(() => { if (current === generation.current) { setStatus("error"); setError("This release failed to load or verify. Scores are hidden until verification succeeds."); } });
    return () => { generation.current++; };
  }, [selected, releases, group]);

  async function loadMore() {
    const release = releases.find(item => item.id === selected);
    if (!release || moreBusy) return;
    const current = generation.current;
    setMoreBusy(true); setError("");
    try {
      const result = await getRpsPage(release.id, rows.length, group);
      if (current !== generation.current) return;
      verifyRpsPage(result, release, rows.length, rows, group);
      setRows([...rows, ...result.items]); setPage(result);
    } catch { if (current === generation.current) setError("The next page could not be verified. Existing rows remain in the same release; please retry."); }
    finally { if (current === generation.current) setMoreBusy(false); }
  }
  const release = releases.find(item => item.id === selected);
  const visible = rows;

  return (
    <section className="space-y-5" aria-labelledby="rps-heading">
      <div className="border-y border-sage-border py-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div><h2 id="rps-heading" className="text-xl font-semibold">Research priority</h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-sage-muted">A material, a defined state, and a next research action. Higher scores indicate higher priority within the same campaign and budget — not a probability of superconductivity.</p></div>
          <div className="text-right"><p className="font-mono text-xl">1,000–10,000</p><p className="text-xs text-sage-muted">RPS-v1.2 · 50-point steps</p></div>
        </div>
      </div>

      <details className="rounded-xl border border-sage-border bg-white p-4">
        <summary className="cursor-pointer font-medium">How the score works · scientific limits</summary>
        <div className="mt-4 space-y-3 text-sm leading-6 text-sage-muted">
          <p className="font-mono text-sage-ink">RPS = 1,000 + 90 × (0.50 P + 0.30 G + 0.20 A)</p>
          <p><strong>P · Physical support.</strong> Six evidence-based dimensions with common anchors and preassigned family weights. Use conservative lower bounds and keep a fixed denominator. Unknown means missing support, not evidence against superconductivity.</p>
          <p><strong>G · Decision gain.</strong> The next action must distinguish outcomes that change a research decision. G = 100 × decision impact × discrimination.</p>
          <p><strong>A · Executability.</strong> Readiness and affordability under a fixed, multi-resource budget. Unknown costs are not free. Exceeding any required resource budget prevents ranking.</p>
          <p>A versioned, reviewed action template defines prerequisites. Critical structure, sample or equipment requirements must be satisfied before execution can rank. All five resource categories require an explicit applicability declaration; unknown applicability stays pending, and not-applicable declarations require a rationale and evidence.</p>
          <p>Family-specific weights are blended 50:50 with common weights. References and unresolved assessments do not occupy discovery ranks. Mechanism studies have a separate ranking.</p>
          <p>Reported ranges reflect assessment bounds, not statistical confidence intervals. Comparability is policy-defined and requires prospective validation; empirical calibration is pending. It does not establish a universal material quality scale. A top-K list is not a jointly budget-feasible action portfolio.</p>
        </div>
      </details>

      {status === "loading" && <p role="status" className="py-8 text-sm text-sage-muted">Loading a verified research release…</p>}
      {status === "empty" && <div className="rounded-xl border border-dashed border-sage-border p-6">
        <h3 className="font-semibold">No reviewed RPS release published yet</h3>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-sage-muted">The scoring framework is ready for curated assessments. Historical candidates below remain research leads; their old heuristic scores have not been converted into RPS. A release requires defined states, actionable questions, evidence review, frozen scoring rules and verified costs.</p>
      </div>}
      {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">{error} {status === "error" && <button className="ml-2 underline" onClick={() => setRetry(n => n + 1)}>Retry</button>}</div>}

      {releases.length > 0 && <div className="space-y-3">
        <label className="flex flex-wrap items-center gap-3 text-sm font-medium">Fixed release
          <select className="max-w-full rounded-lg border border-sage-border bg-white p-2" value={selected} onChange={e => setSelected(e.target.value)}>
            {releases.map(item => <option key={item.id} value={item.id}>{item.id} · {item.campaign_id}</option>)}
          </select>
        </label>
        {release && <div className="space-y-1 text-xs text-sage-muted"><p>{release.objective}</p><p>Evidence cutoff: {release.evidence_cutoff} · Campaign {release.campaign_version}</p><p className="break-all font-mono">Manifest SHA-256: {release.manifest_sha256}</p></div>}
      </div>}

      {status === "ready" && <>
        <div className="flex flex-wrap gap-2" role="group" aria-label="Assessment group">
          {[["discovery", "Discovery actions"], ["mechanism", "Mechanism actions"], ["unranked", "Unranked / references"]].map(([key, label]) => <button key={key} aria-pressed={group === key} onClick={() => setGroup(key)} className={`rounded-lg border px-3 py-2 text-sm ${group === key ? "border-accent bg-accent text-white" : "border-sage-border bg-white"}`}>{label}</button>)}
        </div>
        <div className="max-w-full overflow-x-auto rounded-xl border border-sage-border" tabIndex={0} aria-label="Research priority comparison table">
          <table className="w-full min-w-[1060px] border-collapse text-left text-sm">
            <caption className="sr-only">Action-specific RPS and six physical support dimensions. Unknown values are not adverse evidence.</caption>
            <thead className="bg-sage-surface text-xs text-sage-muted"><tr>
              <th scope="col" className="p-3">Rank / RPS</th><th scope="col" className="p-3">Material · state · next action</th>
              {PHYSICAL_DIMENSIONS.map(([key, label]) => <th key={key} scope="col" className="p-3">{label}</th>)}
              <th scope="col" className="p-3">Assessed weight</th>
            </tr></thead>
            <tbody>{visible.map(row => <PriorityRow key={`${selected}:${row.id}`} row={row} release={release!} />)}</tbody>
          </table>
        </div>
        {visible.length === 0 && <p className="text-sm text-sage-muted">No assessments in this group in this release.</p>}
        <div className="flex items-center justify-between gap-4 text-sm text-sage-muted"><p>{rows.length} / {page?.total ?? 0} assessments loaded in this group</p>
          {page?.has_more && <button disabled={moreBusy} onClick={loadMore} className="rounded-lg border border-sage-border px-4 py-2 text-sage-ink disabled:opacity-50">{moreBusy ? "Verifying…" : "Load next 24"}</button>}
        </div>
      </>}
    </section>
  );
}

function PriorityRow({ row, release }: { row: RpsRow; release: RpsRelease }) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<RpsDetail | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  async function expand() {
    setOpen(!open);
    if (open || detail || loading) return;
    setLoading(true); setError("");
    try {
      const value = await getRpsDetail(release.id, row.id);
      setDetail(verifyRpsDetail(value, release, row));
    } catch { setError("Evidence detail could not be verified. Close and reopen to retry."); }
    finally { setLoading(false); }
  }
  return <>
    <tr className="border-t border-sage-border align-top bg-white">
      <td className="p-3"><span className="text-xs text-sage-muted">{row.rank === null ? "Unranked" : `#${row.rank}`}</span><p className="mt-1 font-mono text-xl font-semibold">{number(row.result.score_display)}</p><span className="text-xs text-sage-muted">{row.result.score_display === null ? row.result.eligibility.replaceAll("_", " ") : "research priority"}</span></td>
      <td className="max-w-[320px] p-3"><button onClick={expand} aria-expanded={open} aria-controls={`detail-${row.id}`} className="text-left font-semibold text-accent underline decoration-dotted underline-offset-4">{row.formula} · {row.family}</button><p className="mt-1 text-xs text-sage-muted">{row.state_summary}</p><p className="mt-2 leading-5">{row.action_summary}</p></td>
      {PHYSICAL_DIMENSIONS.map(([key]) => { const d = row.dimensions[key]; return <td key={key} className="p-3 font-mono text-xs">{d.status === "unknown" ? <span className="font-sans text-sage-muted" title={d.missing_reason ?? "Missing support"}>Unknown</span> : <span>{d.lower}–{d.upper}</span>}</td>; })}
      <td className="p-3 font-mono text-xs">{Math.round(row.result.assessed_weight * 100)}%</td>
    </tr>
    {open && <tr id={`detail-${row.id}`} className="border-t border-sage-border bg-sage-surface"><td colSpan={9} className="p-5">
      <div className="max-w-4xl space-y-4 text-sm">
        <h3 className="font-semibold">Why this action is prioritised</h3>
        <p>Relative to the 5,500-point reference: physical {signed(row.result.contributions.physical)} · gain {signed(row.result.contributions.gain)} · execution {signed(row.result.contributions.action)} · rounding {signed(row.result.contributions.rounding)}. {row.result.score_display === null ? "No published score: eligibility gates were not met or this is a reference." : `Conservative score ${number(row.result.score_raw)}; assessment upper bound ${number(row.result.score_upper)}.`}</p>
        {row.result.reason_codes.length > 0 && <p>Eligibility notes: {row.result.reason_codes.join(", ")}</p>}
        <p className="text-xs text-sage-muted">Unknown dimensions lower conservative priority through missing support, not a physical claim that superconductivity is absent.</p>
        {loading && <p role="status">Loading evidence…</p>}{error && <p role="alert">{error}</p>}
        {detail && <>
          <p>State: {detail.state.phase} · pressure {detail.state.pressure_gpa === null ? "unknown" : `${number(detail.state.pressure_gpa)} GPa`} ({detail.state.pressure_status.replaceAll("_", " ")}). {detail.state.sample_context}</p>
          {detail.action.kind === "conversion" && <p>Conversion target: {number(detail.action.conversion_target_pressure_gpa ?? null)} GPa. {detail.action.conversion_rationale}</p>}
          <dl className="grid gap-3 md:grid-cols-2">{PHYSICAL_DIMENSIONS.map(([key, label]) => {
            const explanation = row.result.contributions.dimension_explanations[key];
            return <div key={key}><dt className="font-medium">{label} · {signed(row.result.contributions.dimensions[key])} points</dt><dd className="mt-1 text-sage-muted">{detail.assessment.dimensions[key].rationale}</dd>
              <dd className="text-xs text-sage-muted">{explanation.reason_codes.map(code => explanationLabels[code] ?? code).join(" · ")}</dd>
              <dd className="text-xs text-sage-muted">Anchor: {signed(explanation.anchor_contribution)} · uncertainty: {signed(explanation.uncertainty_discount)} · missing support: {signed(explanation.missing_support_contribution)}</dd>
              <dd className="text-xs text-sage-muted">Rule: {detail.assessment.dimensions[key].rule_id}</dd></div>;
          })}</dl>
          <h4 className="font-medium">Reviewed action contract</h4>
          <p>Template: {row.action_template.id} · version {row.action_template.version} · review {row.action_template.review_id}</p>
          <p className="text-xs text-sage-muted">{detail.assessment.action_requirements.template.scope} {detail.assessment.action_requirements.template.prerequisite_completeness_rationale}</p>
          <h4 className="font-medium">Prerequisites and dependencies</h4>
          <ul className="space-y-2">{detail.assessment.action_requirements.prerequisites.map(item => <li key={item.key}>
            <span className="font-medium">{item.key}: {item.status.replaceAll("_", " ")}</span>
            {detail.assessment.action_requirements.template.prerequisites.find(rule => rule.key === item.key)?.critical ? " · critical" : " · noncritical"}
            <p className="text-sage-muted">{item.rationale}</p>
            <p className="text-xs text-sage-muted">Dependency IDs: {item.dependency_ids.join(", ") || "none declared"} · evidence IDs: {item.evidence.map(ref => ref.id).join(", ") || "none declared"}</p>
          </li>)}</ul>
          <ul className="space-y-1 text-xs text-sage-muted">{detail.assessment.action_requirements.dependencies.map(item => <li key={item.id}>{item.id} ({item.kind}): {item.status} · {item.rationale} · evidence IDs: {item.evidence.map(ref => ref.id).join(", ") || "none declared"}</li>)}</ul>
          <h4 className="font-medium">What the next action would change</h4><ul className="list-disc space-y-1 pl-5">{detail.assessment.outcomes.map(o => <li key={o.observation}>{o.observation} → {o.decision}</li>)}</ul>
          <h4 className="font-medium">All resource declarations</h4><ul className="space-y-2">{detail.assessment.action_requirements.resources.map(resource => <li key={resource.resource}>{resource.resource}: {resource.applicability.replaceAll("_", " ")} · {resource.rationale}<p className="text-xs text-sage-muted">Evidence IDs: {resource.evidence.map(ref => ref.id).join(", ") || "none declared"}</p></li>)}</ul>
          <h4 className="font-medium">Required resource cost bounds</h4><ul className="space-y-1">{detail.assessment.costs.map(c => <li key={c.resource}>{c.resource}: {number(c.lower)}–{c.upper === null ? "unknown" : number(c.upper)} · {c.basis}</li>)}</ul>
          <h4 className="font-medium">Traceable sources</h4><ul className="space-y-2">{detail.evidence.map(e => <li key={e.id}><a href={/^https?:\/\//.test(e.source.url) ? e.source.url : undefined} target="_blank" rel="noopener noreferrer" className="text-accent underline">{e.source.title}</a><p className="text-xs text-sage-muted">{e.source.source_version} · {e.source.locator} · {e.source.validity}</p></li>)}</ul>
        </>}
      </div>
    </td></tr>}
  </>;
}
