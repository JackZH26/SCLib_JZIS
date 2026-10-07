"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { FormulaDisplay } from "@/components/FormulaDisplay";
import type { SourceHypothesis, SourceHypothesisBrowseCatalogue } from "@/lib/discovery-source-hypotheses";
import { verifySourceHypothesisDetail } from "@/lib/discovery-source-hypothesis-detail";

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

/** Formula order is a browsing order. This directory never computes or implies an RPS ranking. */
export function DiscoverySourceCandidates({ catalogue }: { catalogue: SourceHypothesisBrowseCatalogue }) {
  const [query, setQuery] = useState("");
  const [risk, setRisk] = useState("all");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(24);
  const ordered = useMemo(() => [...catalogue.candidates].sort((left, right) => formulaOrder.compare(left.formula, right.formula)
    || formulaOrder.compare(left.source_state, right.source_state)), [catalogue]);
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
      <p id="discovery-source-tc-scope">Eliashberg T<sub>c</sub> at μ* = 0.1. Unscored research hypotheses; experimental and room-temperature superconductivity are unknown.</p>
    </header>
    <div className="discovery-source-filters">
      <label className="discovery-source-field">Find a source candidate
        <input type="search" value={query} placeholder="Formula, element or source state ID" onChange={event => { setQuery(event.target.value); setPage(1); }} />
      </label>
      <label className="discovery-source-field">Composition or model concern
        <select value={risk} onChange={event => { setRisk(event.target.value); setPage(1); }}>
          <option value="all">All concern tags</option>
          {riskOptions.map(([key, text]) => <option key={key} value={key}>{text}</option>)}
          {ordered.some(candidate => candidate.risk_tags.length === 0) && <option value="none">No additional listed tag</option>}
        </select>
      </label>
      <label className="discovery-source-field">Rows per page
        <select value={pageSize} onChange={event => { setPageSize(Number(event.target.value)); setPage(1); }}>
          <option value={24}>24</option><option value={48}>48</option><option value={catalogue.candidates.length}>All {catalogue.candidates.length}</option>
        </select>
      </label>
      <button type="button" disabled={!query && risk === "all"} onClick={clear}>Clear filters</button>
    </div>
    <div className="discovery-source-toolbar">
      <p role="status" aria-live="polite"><strong>{filtered.length.toLocaleString("en-US")}</strong> / {catalogue.candidates.length.toLocaleString("en-US")} materials
        {filtered.length > 0 && <> · Showing {start + 1}–{Math.min(start + pageSize, filtered.length)}</>} · Formula A–Z</p>
      <a href={catalogue.download_url} download>Download catalogue JSON</a>
    </div>
    <details className="discovery-source-scope">
      <summary>Scope, evidence and how to read this catalogue</summary>
      <div>
        <p>These materials are research hypotheses based on published source calculations and source-selected comparisons. T<sub>c</sub> belongs to the listed source state and model, not to every phase of a chemical composition. Method and sampling differences remain attached to each comparison.</p>
        <p>The displayed value uses the source Eliashberg result at μ* = 0.1. It is not assigned to an individual Gaussian-smearing row. A source-computed transition does not establish an experimental transition or approximately 300 K superconductivity at ambient pressure.</p>
        <p>Rows are ordered by chemical formula, not potential, T<sub>c</sub> or an RPS score. Formal RPS assessments require their own published research action, campaign and budget. They remain separate in <a href="#discovery-formal-assessments">Research &amp; tools</a>.</p>
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
        <caption className="sr-only">Unscored source-computed material hypotheses in chemical formula order. Open details to inspect evidence and limitations.</caption>
        <thead><tr>
          <th scope="col" aria-sort="ascending">Material</th><th scope="col">Research route</th><th scope="col">Source T<sub>c</sub> (K)</th>
          <th scope="col">Status / key concerns</th><th scope="col">Evidence</th>
        </tr></thead>
        <tbody>{visible.map(candidate => <CandidateRow key={candidate.id} candidate={candidate} riskLabels={catalogue.risk_tag_labels} />)}</tbody>
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

function CandidateRow({ candidate, riskLabels }: { candidate: Candidate; riskLabels: SourceHypothesisBrowseCatalogue["risk_tag_labels"] }) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<SourceHypothesis | null>(null);
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
      const result = await readSourceHypothesisDetail(candidate, controller.signal);
      if (current !== generation.current) return;
      setDetail(result); setStatus("ready");
    } catch {
      if (current === generation.current) { setDetail(null); setStatus("error"); }
    } finally { clearTimeout(timeout); }
  };
  const close = () => { generation.current++; request.current?.abort(); setOpen(false); if (!detail) setStatus("idle"); trigger.current?.focus(); };
  const toggle = () => { if (open) close(); else { setOpen(true); if (!detail) void load(); } };
  const concerns = candidate.risk_tags.slice(0, 2);
  return <>
    <tr data-source-candidate={candidate.id} data-formula={candidate.formula}>
      <th scope="row" className="discovery-source-formula"><FormulaDisplay formula={candidate.formula} />
        {sourcePhaseCaptions[candidate.source_state] && <span className="discovery-source-phase">{sourcePhaseCaptions[candidate.source_state]}</span>}
      </th>
      <td className="discovery-source-route">Geometry construction</td>
      <td className="discovery-source-tc">{number(candidate.source_tc.target_K)}</td>
      <td className="discovery-source-status"><span className="discovery-source-unscored">Unscored</span>
        {concerns.length > 0 && <div className="discovery-source-tags">{concerns.map(tag => <span key={tag} className="discovery-source-tag">{riskLabels[tag] ?? label(tag)}</span>)}
          {candidate.risk_tags.length > concerns.length && <span className="discovery-source-more-tags">+{candidate.risk_tags.length - concerns.length} in details</span>}
        </div>}
      </td>
      <td><button ref={trigger} type="button" aria-expanded={open} aria-controls={open ? detailsId : undefined}
        aria-label={`${open ? "Hide" : "Show"} details for ${candidate.formula}`} onClick={toggle}>{open ? "Hide details" : "Details"}</button></td>
    </tr>
    {open && <tr id={detailsId} className="discovery-source-detail-row"><td colSpan={5}>
      <div className="discovery-source-detail">
        <header><div><h3><FormulaDisplay formula={candidate.formula} /> · Source evidence</h3><p>Target {candidate.source_state} · Control {candidate.control_state}</p></div>
          <button type="button" onClick={close} aria-label={`Close details for ${candidate.formula}`}>Close</button></header>
        {status === "loading" && <p role="status">Loading and verifying source evidence…</p>}
        {status === "error" && <div><p role="alert">This material's source evidence could not be verified. No detail values are shown.</p><button type="button" onClick={() => void load()}>Retry source evidence</button></div>}
        {detail && <>
        <div className="discovery-source-tags">{detail.risk_tags.map(tag => <span key={tag} className="discovery-source-tag">{riskLabels[tag] ?? label(tag)}</span>)}</div>
        <div className="discovery-source-detail-grid">
          <section><h4>Source calculation and selected control</h4><dl>
            <div><dt>Target / control T<sub>c</sub> · Eliashberg, μ* = 0.1</dt><dd>{number(detail.source_tc.target_K)} / {number(detail.source_tc.control_K)} K · Δ {difference(detail.source_tc.delta_K)} K</dd></div>
            <div><dt>λ difference across ten source smearing rows · target minus control</dt><dd>{detail.lambda_difference.range ? `${difference(detail.lambda_difference.range[0])} to ${difference(detail.lambda_difference.range[1])}` : "Unknown"}</dd></div>
            <div><dt>Source phase / prototype context</dt><dd>{detail.prototype || "Unknown"}</dd></div>
            <div><dt>Ambient-pressure scope</dt><dd>{detail.ambient_scope}</dd></div>
          </dl></section>
          <section><h4>Research interpretation</h4><dl>
            <div><dt>Quantified route response</dt><dd>{detail.route_response}</dd></div>
            <div><dt>Competing explanations and limitations</dt><dd>{detail.risk_summary}</dd></div>
            <div><dt>Next discriminating action</dt><dd>{detail.next_action}</dd></div>
          </dl></section>
        </div>
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
