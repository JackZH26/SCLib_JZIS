"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { FormulaDisplay } from "@/components/FormulaDisplay";
import type { SourceHypothesis, SourceHypothesisBrowseCatalogue } from "@/lib/discovery-source-hypotheses";
import { verifySourceHypothesisDetail } from "@/lib/discovery-source-hypothesis-detail";
import { compareResearchPriority, sourceSupport, verifyDiscoveryEvidenceCard } from "@/lib/discovery-evidence-policy";
import type { DiscoveryEvidenceCard, ResearchGoal } from "@/lib/discovery-evidence-policy";
import { readReadableEvidence, readableFieldLabels } from "@/lib/discovery-readable-evidence";
import type { ReadableEvidenceCopy, ReadableEvidenceField } from "@/lib/discovery-readable-evidence";

type Candidate = SourceHypothesisBrowseCatalogue["candidates"][number];
const normalize = (value: string) => value.toLowerCase().replace(/[₀₁₂₃₄₅₆₇₈₉]/g, digit => String("₀₁₂₃₄₅₆₇₈₉".indexOf(digit))).trim();
const formulaOrder = new Intl.Collator("en-US", { numeric: true, sensitivity: "base" });
const number = (value: number | null | undefined) => typeof value === "number" && Number.isFinite(value)
  ? value.toLocaleString("en-US", { maximumFractionDigits: 3 }) : "Unknown";
const difference = (value: number | null | undefined) => typeof value === "number" && Number.isFinite(value)
  ? `${value > 0 ? "+" : ""}${number(value)}` : "Unknown";
const label = (value: string) => value.replaceAll("_", " ").replace(/^./, character => character.toUpperCase());
// Phase captions identify these frozen source states, not every phase of their composition.
const sourcePhaseCaptions: Readonly<Record<string, string>> = {
  agm002028410: "FCC source phase",
  agm003157370: "Ordered tetragonal source phase",
  agm001192155: "B1 / rock-salt source phase",
};

/** Read one immutable, same-origin detail. The server catalogue supplies its exact byte and hash pin. */
export async function readSourceHypothesisDetail(candidate: Candidate, signal: AbortSignal): Promise<SourceHypothesis> {
  const expected = candidate.detail;
  if (!/^agm[0-9]{9}$/.test(candidate.source_state) || expected.url !== `/research-hypotheses/details/${candidate.source_state}.json`
    || !Number.isSafeInteger(expected.bytes) || expected.bytes <= 0 || expected.bytes > 1024 * 1024) throw new Error("Invalid source detail reference");
  const response = await fetch(expected.url, { credentials: "omit", cache: "no-store", redirect: "error", signal });
  if (response.status !== 200 || !response.headers.get("content-type")?.toLowerCase().startsWith("application/json") || !response.body) throw new Error("Source evidence is unavailable");
  const reader = response.body.getReader();
  const bytes = new Uint8Array(expected.bytes);
  let offset = 0;
  try {
    while (true) {
      if (signal.aborted) throw new Error("Cancelled source evidence read");
      const chunk = await reader.read();
      if (chunk.done) break;
      if (offset + chunk.value.byteLength > bytes.byteLength) throw new Error("Source detail exceeded its pinned size");
      bytes.set(chunk.value, offset); offset += chunk.value.byteLength;
    }
    if (offset !== bytes.byteLength || signal.aborted) throw new Error("Incomplete source evidence");
    const detail = await verifySourceHypothesisDetail(bytes, candidate);
    if (signal.aborted) throw new Error("Cancelled source evidence read");
    return detail.candidate;
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}

export async function readResearchEvidenceCard(candidate: Candidate, signal: AbortSignal): Promise<DiscoveryEvidenceCard> {
  const expected = candidate.research_evidence.detail;
  if (expected.url !== `/research-hypotheses/evidence-cards/2026-10-08-evidence103-v1/${candidate.source_state}.json`
    || expected.bytes <= 0 || expected.bytes > 256 * 1024) throw new Error("Invalid research evidence reference");
  const response = await fetch(expected.url, { credentials: "omit", cache: "no-store", redirect: "error", signal });
  if (response.status !== 200 || !response.headers.get("content-type")?.toLowerCase().startsWith("application/json") || !response.body) throw new Error("Research evidence is unavailable");
  const reader = response.body.getReader(), bytes = new Uint8Array(expected.bytes);
  let offset = 0;
  try {
    while (true) {
      if (signal.aborted) throw new Error("Cancelled research evidence read");
      const chunk = await reader.read(); if (chunk.done) break;
      if (offset + chunk.value.byteLength > bytes.byteLength) throw new Error("Research evidence exceeded its pinned size");
      bytes.set(chunk.value, offset); offset += chunk.value.byteLength;
    }
    if (offset !== bytes.byteLength || signal.aborted) throw new Error("Incomplete research evidence");
    return await verifyDiscoveryEvidenceCard(bytes, candidate);
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}

/** Provisional research groups, separate from formal action/budget RPS assessments. */
export function DiscoverySourceCandidates({ catalogue }: { catalogue: SourceHypothesisBrowseCatalogue }) {
  const [query, setQuery] = useState("");
  const [risk, setRisk] = useState("all");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(24);
  const [goal, setGoal] = useState<ResearchGoal>("source_pairing");
  const [sort, setSort] = useState("priority");
  const ordered = useMemo(() => [...catalogue.candidates].sort((left, right) => sort === "priority"
    ? compareResearchPriority(left, right, goal) : formulaOrder.compare(left.formula, right.formula)
    || formulaOrder.compare(left.source_state, right.source_state)), [catalogue, goal, sort]);
  const search = normalize(query);
  const filtered = ordered.filter(candidate => (!search || [candidate.formula, candidate.reduced_formula, candidate.source_state,
    candidate.control_state, ...candidate.elements].some(value => normalize(value).includes(search)))
    && (risk === "all" || (risk === "none" ? candidate.risk_tags.length === 0 : candidate.risk_tags.some(tag => tag === risk))));
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, pages);
  const start = (currentPage - 1) * pageSize;
  const visible = filtered.slice(start, start + pageSize);
  const riskOptions = Object.entries(catalogue.risk_tag_labels).filter(([key]) => ordered.some(candidate => candidate.risk_tags.some(tag => tag === key)));
  const clear = () => { setQuery(""); setRisk("all"); setPage(1); };

  return <section id="discovery-source-candidates" className="discovery-source-browser" aria-labelledby="discovery-source-heading">
    <header className="discovery-source-heading">
      <h2 id="discovery-source-heading">Source-computed candidate materials</h2>
      <p id="discovery-source-tc-scope">Source Eliashberg T<sub>c</sub>, μ* = 0.1. Experimental and room-temperature superconductivity are unknown.</p>
    </header>
    <div className="discovery-source-filters">
      <label className="discovery-source-field">Find a source candidate
        <input type="search" value={query} placeholder="Formula, element or source state ID" onChange={event => { setQuery(event.target.value); setPage(1); }} />
      </label>
      <label className="discovery-source-field">Research target
        <select value={goal} onChange={event => { setGoal(event.target.value as ResearchGoal); setPage(1); }}>
          <option value="source_pairing">Test source pairing response</option><option value="ambient_300K">Approx. 300 K, ambient pressure</option>
        </select>
      </label>
      <div className="discovery-source-filter-options">
        <details className="discovery-source-secondary-filters"><summary>Filters and ordering{risk !== "all" ? " · Concern filter active" : ""}</summary>
          <div className="discovery-source-advanced-fields">
            <label className="discovery-source-field">Composition or model concern
              <select value={risk} onChange={event => { setRisk(event.target.value); setPage(1); }}>
                <option value="all">All concern tags</option>
                {riskOptions.map(([key, text]) => <option key={key} value={key}>{text}</option>)}
                {ordered.some(candidate => candidate.risk_tags.length === 0) && <option value="none">No additional listed tag</option>}
              </select>
            </label>
            <label className="discovery-source-field">Browse order
              <select value={sort} onChange={event => { setSort(event.target.value); setPage(1); }}>
                <option value="priority">Provisional research groups</option><option value="formula">Formula A to Z</option>
              </select>
            </label>
            <label className="discovery-source-field">Rows per page
              <select value={pageSize} onChange={event => { setPageSize(Number(event.target.value)); setPage(1); }}>
                <option value={24}>24</option><option value={48}>48</option><option value={catalogue.candidates.length}>All {catalogue.candidates.length}</option>
              </select>
            </label>
          </div>
        </details>
        <button type="button" disabled={!query && risk === "all"} onClick={clear}>Clear filters</button>
      </div>
    </div>
    <div className="discovery-source-toolbar">
      <p role="status" aria-live="polite"><strong>{filtered.length.toLocaleString("en-US")}</strong> / {catalogue.candidates.length.toLocaleString("en-US")} materials
        {filtered.length > 0 && <> · Showing {start + 1} to {Math.min(start + pageSize, filtered.length)}</>} · {sort === "formula" ? "Formula A to Z" : "Provisional groups"}</p>
      <a href={catalogue.download_url} download>Download catalogue JSON</a>
    </div>
    <details className="discovery-source-scope">
      <summary>Scope, evidence and how to read this catalogue</summary>
      <div>
        <p>These materials are research hypotheses based on published source calculations and source-selected comparisons. T<sub>c</sub> belongs to the listed source state and model, not to every phase of a chemical composition. Method and sampling differences remain attached to each comparison.</p>
        <p>The displayed value uses the source Eliashberg result at μ* = 0.1. It is not assigned to an individual Gaussian-smearing row. A source-computed transition does not establish an experimental transition or approximately 300 K superconductivity at ambient pressure.</p>
        <p>All 103 materials currently remain C (exploratory) and E1 (published source theory). Evidence does not support a calibrated potential ranking within this group. For the source-response target, explicit alternative-control limitations form a review group after other exploratory cases. This is a research grouping, not a success probability. Formula resolves ties; Source T<sub>c</sub> never sets priority. For the approximately 300 K target, all cases have no direct support and retain formula order.</p>
        <p>The six-axis P support rubric has fixed weights for stability (20%), electronic response (20%), pairing (25%), coherence (15%), geometry (10%) and competition (10%). Source pairing has an uncalibrated ordinal anchor of 25 to 50 for its own research target. Other axes remain unknown (0 to 100); weights are not redistributed. Weighted quantified coverage is 25% for the source-response target and 0% for the 300 K target. These support ranges are not measured probabilities or confidence intervals. Provisional A/B policy cutoffs of 75/55 also require independent evidence and relevant coverage; legacy support 3/4 is not converted to P.</p>
        <p>Formal RPS assessments require their own published research action, campaign and budget. They remain separate in <a href="#discovery-formal-assessments">Research &amp; tools</a>.</p>
        <p>Concern tags highlight selected limitations; an absent tag does not establish absence of risk. Expand each material for its controls, competing explanations, source scope and a testable next action.</p>
        <p>Inclusion does not claim a first discovery. Published computational proposals, previously studied compositions and distinct proposed phases retain their source context. Unrelaxed COD coordinate proposals are a separate <a href="#discovery-coordinate-proposals">research catalogue</a> and are not counted here.</p>
        <p>Source: <a href={catalogue.dataset_source.url}>{catalogue.dataset_source.title}</a>, {catalogue.dataset_source.authors.join(", ")} · {catalogue.dataset_source.version}. <a href={catalogue.dataset_source.license_url}>{catalogue.dataset_source.license}</a>. {catalogue.dataset_source.attribution}</p>
        <details><summary>Common source and publication scope</summary>
          <pre className="discovery-source-evidence-json">{JSON.stringify({ dataset_source: catalogue.dataset_source, scope: catalogue.scope, counts: catalogue.counts }, null, 2)}</pre>
        </details>
      </div>
    </details>
    {visible.length ? <div className="discovery-source-table-scroll" tabIndex={0} role="region" aria-label="Source-computed candidate table, scroll horizontally for all columns">
      <table className="discovery-source-table" aria-describedby="discovery-source-tc-scope">
        <caption className="sr-only">Source-computed hypotheses in {sort === "formula" ? "formula order" : "provisional research groups"}. Open details to inspect support, prior work and limitations.</caption>
        <thead><tr>
          <th scope="col" aria-sort={sort === "formula" ? "ascending" : undefined}>Material</th><th scope="col">Research route</th><th scope="col">Source T<sub>c</sub> (K)</th>
          <th scope="col">Support / evidence</th><th scope="col">Key concerns</th><th scope="col">Details</th>
        </tr></thead>
        <tbody>{visible.map(candidate => <CandidateRow key={candidate.id} candidate={candidate} riskLabels={catalogue.risk_tag_labels} goal={goal} />)}</tbody>
      </table>
    </div> : <div className="discovery-source-empty"><p>No source candidates match this search and concern tag.</p><button type="button" onClick={clear}>Show all materials</button></div>}
    {filtered.length > 0 && <nav className="discovery-source-pagination" aria-label="Source candidate pages">
      <p>Page {currentPage} of {pages}</p>
      <div>
        <label>Go to page<select value={currentPage} onChange={event => setPage(Number(event.target.value))}>
          {Array.from({ length: pages }, (_, index) => <option key={index + 1} value={index + 1}>{index + 1}</option>)}
        </select></label>
        <button type="button" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}>Previous materials</button>
        <button type="button" disabled={currentPage === pages} onClick={() => setPage(currentPage + 1)}>Next materials</button>
      </div>
    </nav>}
  </section>;
}

function CandidateRow({ candidate, riskLabels, goal }: { candidate: Candidate; riskLabels: SourceHypothesisBrowseCatalogue["risk_tag_labels"]; goal: ResearchGoal }) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<SourceHypothesis | null>(null);
  const [card, setCard] = useState<DiscoveryEvidenceCard | null>(null);
  const [readerCopy, setReaderCopy] = useState<ReadableEvidenceCopy>({});
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const trigger = useRef<HTMLButtonElement>(null);
  const request = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const detailsId = `source-hypothesis-${encodeURIComponent(candidate.id)}`;
  useEffect(() => () => { generation.current++; request.current?.abort(); }, []);
  const load = async () => {
    const current = ++generation.current;
    request.current?.abort();
    const controller = new AbortController(); request.current = controller; setStatus("loading");
    const timeout = setTimeout(() => controller.abort(), 20_000);
    try {
      const [result, dossier] = await Promise.all([readSourceHypothesisDetail(candidate, controller.signal), readResearchEvidenceCard(candidate, controller.signal)]);
      if (current !== generation.current) return;
      if (controller.signal.aborted) throw new Error("Cancelled source evidence read");
      const copy = await readReadableEvidence(candidate, result, dossier);
      if (current !== generation.current) return;
      if (controller.signal.aborted) throw new Error("Cancelled source evidence read");
      setDetail(result); setCard(dossier); setReaderCopy(copy); setStatus("ready");
    } catch {
      controller.abort();
      if (current === generation.current) { setDetail(null); setCard(null); setReaderCopy({}); setStatus("error"); }
    } finally { clearTimeout(timeout); }
  };
  const close = () => { generation.current++; request.current?.abort(); setOpen(false); if (!detail) setStatus("idle"); trigger.current?.focus(); };
  const toggle = () => { if (open) close(); else { setOpen(true); if (!detail) void load(); } };
  const concerns = candidate.risk_tags.slice(0, 2);
  const assessment = sourceSupport(candidate.research_evidence, goal);
  const copyText = (field: ReadableEvidenceField, original: string) => readerCopy[field]?.text ?? original;
  return <>
    <tr data-source-candidate={candidate.id} data-formula={candidate.formula}>
      <th scope="row" className="discovery-source-formula"><FormulaDisplay formula={candidate.formula} />
        {sourcePhaseCaptions[candidate.source_state] && <span className="discovery-source-phase">{sourcePhaseCaptions[candidate.source_state]}</span>}
      </th>
      <td className="discovery-source-route">Geometry construction</td>
      <td className="discovery-source-tc">{number(candidate.source_tc.target_K)}</td>
      <td className="discovery-source-support"><strong>{assessment.grade} · {assessment.evidence_level}</strong>
        <span>{goal === "ambient_300K" ? "No direct target support" : "Exploratory"}</span></td>
      <td className="discovery-source-status"><span className="discovery-source-unscored">{candidate.research_evidence.counterevidence_count > 0 ? `${candidate.research_evidence.counterevidence_count} control limitations` : "Feasibility unresolved"}</span>
        {concerns.length > 0 && <div className="discovery-source-tags">{concerns.map(tag => <span key={tag} className="discovery-source-tag">{riskLabels[tag] ?? label(tag)}</span>)}
          {candidate.risk_tags.length > concerns.length && <span className="discovery-source-more-tags">+{candidate.risk_tags.length - concerns.length} in details</span>}
        </div>}
      </td>
      <td><button ref={trigger} type="button" aria-expanded={open} aria-controls={open ? detailsId : undefined}
        aria-label={`${open ? "Hide" : "Show"} details for ${candidate.formula}`} onClick={toggle}>{open ? "Hide details" : "Details"}</button></td>
    </tr>
    {open && <tr id={detailsId} className="discovery-source-detail-row"><td colSpan={6}>
      <div className="discovery-source-detail">
        <header><div><h3><FormulaDisplay formula={candidate.formula} /> · Source evidence</h3><p>Target {candidate.source_state} · Control {candidate.control_state}</p></div>
          <button type="button" onClick={close} aria-label={`Close details for ${candidate.formula}`}>Close</button></header>
        {status === "loading" && <p role="status">Loading and verifying source evidence…</p>}
        {status === "error" && <div><p role="alert">This material's source evidence could not be verified. No detail values are shown.</p><button type="button" onClick={() => void load()}>Retry source evidence</button></div>}
        {detail && card && <>
        <section className="discovery-source-assessment"><h4>Provisional support for the selected research target</h4>
          <p><strong>{assessment.grade} · {assessment.evidence_level}</strong> · P policy-derived ordinal bounds {number(assessment.lower)} to {number(assessment.upper)} · Weighted quantified coverage {assessment.coverage_percent}% · Formal RPS unscored</p>
          <p>The bounds come from uncalibrated policy anchors. They are not measured potential, predictive accuracy, a probability or a confidence interval.</p>
          <p>{goal === "ambient_300K" ? "No direct support for approximately 300 K at ambient pressure. This is an evidence gap, not a claim of physical impossibility." : "All current materials share overlapping C support bounds. Alternative controls limit specific source-response claims; they do not reject an entire composition."}</p>
          <details><summary>Six axes, anchors and unknowns</summary><dl>{Object.entries(assessment.axes).map(([axis, evidence]) => <div key={axis}><dt>{label(axis)} · {label(evidence.anchor)} · {evidence.quantified_for_goal ? "Quantified for target" : "Unquantified for target"}</dt><dd>{evidence.scope}</dd></div>)}</dl></details>
        </section>
        {Object.keys(readerCopy).length > 0 && <p className="discovery-source-reader-label"><strong>Reader’s summary</strong></p>}
        <div className="discovery-source-dossier">
          <section><h4>Prior work and novelty boundary</h4><p>{copyText("prior.case_context", card.prior.case_context)}</p><p>{card.prior.claim_boundary}</p>
            <p>{card.prior.sources.map((source, index) => <span key={source.url}>{index > 0 && " · "}<a href={source.url}>{source.title}</a></span>)}</p></section>
          <section><h4>Decision bottleneck</h4><p>{copyText("bottleneck.summary", card.bottleneck.summary)}</p>
            {card.bottleneck.counterevidence.length > 0 && <ul className="discovery-source-counterevidence">{card.bottleneck.counterevidence.map(item => <li key={`${item.comparison_origin}:${item.countercontrol_index}`}><strong>{item.direction === "joint_adverse" ? "Adverse alternative" : "Discordant response"}: {item.control_reference}</strong><p>{item.lambda_unit === "percent" ? "Relative λ change (target vs control)" : "λ target minus control"}: {difference(item.lambda_target_minus_control_range[0])} to {difference(item.lambda_target_minus_control_range[1])} {item.lambda_unit === "percent" ? "%" : ""}; separate source ΔT<sub>c</sub> {difference(item.source_tc_target_minus_control_K)} K.</p><p>{item.scope}</p></li>)}</ul>}
          </section>
          <section><h4>Proposed contribution and next action</h4><p>{copyText("proposed_contribution.intervention", card.proposed_contribution.intervention)}</p><p><strong>Next action:</strong> {copyText("proposed_contribution.next_action", card.proposed_contribution.next_action)}</p><p><strong>Decision rule:</strong> {card.proposed_contribution.falsifier}</p><p>{card.proposed_contribution.new_state_inheritance}</p></section>
        </div>
        <div className="discovery-source-tags">{detail.risk_tags.map(tag => <span key={tag} className="discovery-source-tag">{riskLabels[tag] ?? label(tag)}</span>)}</div>
        <div className="discovery-source-detail-grid">
          <section><h4>Source calculation and selected control</h4><dl>
            <div><dt>Target / control T<sub>c</sub> · Eliashberg, μ* = 0.1</dt><dd>{number(detail.source_tc.target_K)} / {number(detail.source_tc.control_K)} K · Δ {difference(detail.source_tc.delta_K)} K</dd></div>
            <div><dt>λ difference across ten source smearing rows · target minus control</dt><dd>{detail.lambda_difference.range ? `${difference(detail.lambda_difference.range[0])} to ${difference(detail.lambda_difference.range[1])}` : "Unknown"}</dd></div>
            <div><dt>Source phase / prototype context</dt><dd>{detail.prototype || "Unknown"}</dd></div>
            <div><dt>Ambient-pressure scope</dt><dd>{copyText("bottleneck.ambient_scope", detail.ambient_scope)}</dd></div>
          </dl></section>
        </div>
        {Object.keys(readerCopy).length > 0 && <details className="discovery-source-original-notes"><summary>Original source notes</summary>
          <dl>{(Object.keys(readerCopy) as ReadableEvidenceField[]).map(field => <div key={field}><dt>{readableFieldLabels[field]}</dt><dd>{readerCopy[field]!.original}</dd></div>)}</dl>
        </details>}
        <details><summary>Seven criteria and case-specific reasoning</summary><dl className="discovery-source-criteria">
          {Object.entries(detail.seven_criteria).map(([key, text]) => <div key={key}><dt>{label(key)}</dt><dd>{text}</dd></div>)}
        </dl></details>
        <details><summary>All frozen controls, physical observations and source metadata</summary>
          <p>Original source values, unknowns and comparison directions are retained below. This evidence contains no RPS score or experimental confirmation.</p>
          <pre className="discovery-source-evidence-json">{JSON.stringify(detail, null, 2)}</pre>
        </details>
        </>}
      </div>
    </td></tr>}
  </>;
}
