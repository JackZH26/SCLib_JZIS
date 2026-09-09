"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AVAILABILITY_LABELS, SCIENTIFIC_DISCLAIMER, SCIENTIFIC_FAILURE, SCIENTIFIC_FIELDS, SCIENTIFIC_GROUPS,
  SCIENTIFIC_KEYS, getScientificCatalog, getScientificProjection, scientificNumber, scientificQuantity,
  type ScientificAssessment, type ScientificCatalog, type ScientificCell, type ScientificMaterial,
  type ScientificObservation, type ScientificReceipt,
} from "@/lib/discovery-scientific";

const label = (value: string) => value.replaceAll("_", " ");
const score = (value: number | null) => value === null ? "Unranked" : value.toLocaleString("en-US");
const short = (value: string) => value.slice(0, 12);
const inputStyle = "min-h-11 rounded-lg border border-sage-border bg-white px-3 py-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent";
const groupLabels = { stability: "Stability", electronic: "Electronic", pairing: "Pairing", coherence: "Coherence", geometry: "Geometry", competing_order: "Competing order" };
type RoleGroup = "discovery" | "mechanism" | "controls";
function roleGroup(row: ScientificMaterial): RoleGroup {
  if (["reference_anchor", "benchmark_control", "negative_control"].includes(row.assessment.role)) return "controls";
  return row.assessment.result.rank_group === "mechanism" || row.assessment.role === "mechanism_anchor" ? "mechanism" : "discovery";
}
function pressure(state: Pick<ScientificMaterial["state_context"], "pressure_status" | "pressure_gpa">) {
  return state.pressure_status === "explicit_ambient" ? "Explicit ambient · 0 GPa" : state.pressure_status === "reported"
    ? `${scientificNumber(state.pressure_gpa)} GPa` : `Pressure ${label(state.pressure_status)}`;
}
function Term({ name, children }: { name: string; children: React.ReactNode }) {
  return <div className="min-w-0"><dt className="text-xs text-sage-muted">{name}</dt><dd className="mt-1 break-words [overflow-wrap:anywhere]">{children}</dd></div>;
}
function Pins({ title, value }: { title: string; value: unknown }) {
  return <details className="rounded-lg border border-sage-border px-3 py-2">
    <summary className="cursor-pointer text-sm">{title}</summary>
    <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(value, null, 2)}</pre>
  </details>;
}
function CellValue({ cell }: { cell: ScientificCell }) {
  return <>
    <span className="block font-medium">{cell.observations.length === 1 && cell.availability === "reported"
      ? scientificQuantity(cell.observations[0].quantity) : AVAILABILITY_LABELS[cell.availability]}</span>
    <span className="mt-1 block text-xs text-sage-muted">{cell.observations.length > 1
      ? `${cell.observations.length} recorded results · expand to inspect all` : cell.availability === "reported" ? "Recorded value · review in details" : label(cell.reason_code)}</span>
  </>;
}

function Observation({ value: o }: { value: ScientificObservation }) {
  const [fidelity, science] = o.review.scopes;
  return <article className="space-y-3 rounded-lg border border-sage-border bg-white p-4">
    <h5 className="font-medium">{o.property.component_key} · {scientificQuantity(o.quantity)}</h5>
    <dl className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
      <Term name="Quantity relation">{o.quantity.relation}</Term>
      <Term name="Registry version">{o.property.registry_version}</Term>
      <Term name="Event revision">{o.event.revision.toLocaleString("en-US")}</Term>
      <Term name="Recorded origin / event type">{o.event.knowledge_origin} / {label(o.event.event_type)}</Term>
      <Term name="Pressure">{pressure(o.state)}</Term>
      <Term name="Temperature / role">{scientificNumber(o.state.temperature_k)}{o.state.temperature_k === null ? "" : " K"} / {label(o.state.temperature_role)}</Term>
      <Term name="State resolution">{label(o.state.resolution)}</Term>
      <Term name="Structure">{o.structure ? label(o.structure.structure_kind) : "Not linked"}</Term>
      <Term name="Recorded run / status">{o.run ? `${label(o.run.run_kind)} / ${label(o.run.status)}` : "Not linked"}</Term>
      <Term name="Extraction fidelity">{label(fidelity.effective_status)}{fidelity.profile_version ? ` · ${fidelity.profile_version}` : ""}</Term>
      <Term name="Scientific review">{o.scientific_scope_accepted ? "Accepted · sampled phonon minimum only" : "Unreviewed scientific result"}{science.profile_version ? ` · ${science.profile_version}` : ""}</Term>
      <Term name="Normalization">Not asserted; the registry unit does not establish normalization.</Term>
    </dl>
    <p className="text-xs leading-5 text-sage-muted">An exact value does not mean zero uncertainty; an interval is not automatically a confidence interval. Recorded run labels do not establish upstream execution or convergence. A sampled phonon review does not establish full-zone dynamical stability or superconductivity. ML training is not approved by this record.</p>
    <Pins title="Exact property, event and state / sample / structure / run pins" value={{ property: o.property, event: o.event, material: o.material,
      state: o.state, sample: o.sample, structure: o.structure, run: o.run }} />
    <Pins title="Scientific subject and scope-specific review pins" value={o.review} />
    <section aria-label="Source evidence" className="space-y-2">
      <h6 className="text-sm font-medium">Source evidence ({o.sources.length.toLocaleString("en-US")})</h6>
      {o.sources.length === 0 && <p className="text-xs text-sage-muted">No event-evidence links in this projection.</p>}
      {o.sources.map(s => <Pins key={s.id} title={`${label(s.relation_scope)} · ${label(s.link_type)} · ${s.id}`} value={s} />)}
    </section>
    <section aria-label="Source occurrences" className="space-y-2">
      <h6 className="text-sm font-medium">Source occurrences ({o.source_occurrences.length.toLocaleString("en-US")})</h6>
      <p className="text-xs text-sage-muted">Snapshot membership and forward claim occurrences are provenance relations, not independent supporting experiments.</p>
      {o.source_occurrences.map(s => <Pins key={`${s.table}:${s.id}`} title={`${label(s.relation_scope)} · ${s.id}`} value={s} />)}
    </section>
  </article>;
}
export function PolicyDetails({ assessment: a }: { assessment: ScientificAssessment }) {
  const s = a.result;
  return <details className="space-y-3 rounded-lg border border-sage-border p-4">
    <summary className="cursor-pointer font-medium">Frozen policy assessment · {a.id} · RPS {score(s.score_display)}</summary>
    <dl className="grid gap-3 pt-3 text-sm sm:grid-cols-3">
      <Term name="State descriptor / summary">{a.state_id} · {a.state_summary}</Term>
      <Term name="Action / summary">{a.action_id} · {a.action_summary}</Term>
      <Term name="Role / eligibility">{label(a.role)} / {label(s.eligibility)}</Term>
      <Term name="Frozen assessment rank">{a.rank === null ? "Unranked" : a.rank.toLocaleString("en-US")} (not a material rank)</Term>
      <Term name="Physical support (P)">{scientificNumber(s.p_lower)}–{scientificNumber(s.p_upper)}</Term>
      <Term name="Information gain (G)">{scientificNumber(s.g_lower)}–{scientificNumber(s.g_upper)}</Term>
      <Term name="Action feasibility (A)">{s.a_lower === null ? "Unknown" : `${scientificNumber(s.a_lower)}–${scientificNumber(s.a_upper)}`}</Term>
      <Term name="Raw / upper policy score">{scientificNumber(s.score_raw)} / {scientificNumber(s.score_upper)}</Term>
      <Term name="Execution constraints">{s.execution_constraint_reasons.length ? s.execution_constraint_reasons.join(" · ") : "No execution constraints declared"}</Term>
    </dl>
    <p className="text-xs text-sage-muted">P / G / A are policy dimensions on a 0–100 scale, not probabilities. Point contributions below explain the frozen policy score, not measured positive or negative physical effects. Missing support is not evidence against superconductivity. No score or weight is recomputed here.</p>
    <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Frozen policy contributions">
      <table className="min-w-[650px] w-full text-left text-xs">
        <caption className="sr-only">Frozen dimension weights and policy-point contributions</caption>
        <thead><tr>{["Dimension", "Weight", "Evidence polarity", "Point contribution", "Reason"].map(h => <th key={h} scope="col" className="p-2">{h}</th>)}</tr></thead>
        <tbody>{SCIENTIFIC_GROUPS.map(k => <tr key={k} className="border-t border-sage-border">
          <th scope="row" className="p-2 font-medium">{groupLabels[k]}</th><td className="p-2">{scientificNumber(s.effective_weights[k])}</td>
          <td className="p-2">{a.dimensions[k].evidence_polarity}</td><td className="p-2">{scientificNumber(s.contributions.dimensions[k])}</td>
          <td className="p-2">{label(s.contributions.dimension_reasons[k])}</td>
        </tr>)}</tbody>
      </table>
    </div>
    <Pins title="Complete frozen assessment and contribution record" value={a} />
  </details>;
}
export function MaterialDetails({ row: r, close, prepared = false }: { row: ScientificMaterial; close: () => void; prepared?: boolean }) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
    heading.current?.scrollIntoView?.({ block: "start", behavior: "auto" });
  }, [r.material.row_id, r.representative.id]);
  return <section id={prepared ? "prepared-material-details" : "scientific-material-details"} aria-label={`${r.assessment.formula} scientific details`} className="space-y-4 rounded-xl border border-sage-border bg-sage-surface p-4 sm:p-5">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h3 ref={heading} tabIndex={-1} className="scroll-mt-24 text-lg font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">{r.assessment.formula} · scientific record</h3><p className="text-sm text-sage-muted">Selected state and action only; alternatives do not change these scientific cells.</p></div>
      <button type="button" onClick={close} className={inputStyle}>Close details</button>
    </div>
    <dl className="grid gap-3 text-sm sm:grid-cols-2">
      <Term name="Actual material ID">{r.material.row_id}</Term>
      <Term name="RPS material descriptor">{r.assessment.material_id}</Term>
      <Term name="Selected state ID">{r.state.row_id}</Term>
      <Term name="Selected structure ID">{r.structure?.row_id ?? "Not selected"}</Term>
      <Term name={prepared ? "Prepared representative" : "Frozen representative"}>{r.representative.id} · revision {r.representative.revision.toLocaleString("en-US")}</Term>
      <Term name="Selection rationale">{r.selection_rationale}</Term>
      <Term name="Main barrier">Main barrier not separately declared</Term>
      <Term name="Assessment reasons">{r.assessment.result.reason_codes.join(" · ") || "No assessment reasons declared"}</Term>
    </dl>
    <Pins title="Representative, original RPS review and selected context pins" value={{ representative: r.representative, assessment_review: r.assessment_review,
      material: r.material, state: r.state, structure: r.structure, state_context: r.state_context, profile_assignment: r.profile_assignment }} />
    <p className="text-xs text-sage-muted">The original RPS review concerns the policy assessment. It is not scientific acceptance of each property.</p>
    <PolicyDetails assessment={r.assessment} />
    <section className="space-y-3" aria-label="Alternative research actions">
      <h4 className="font-semibold">Alternative research actions ({r.alternatives.length.toLocaleString("en-US")})</h4>
      <p className="text-sm text-sage-muted">The {prepared ? "prepared" : "published"} representative is explicit, not the highest-scoring action. Alternative states and actions retain their original roles and scores; they are not additional materials.</p>
      {r.alternatives.length === 0 && <p className="text-sm">No alternative assessments in this frozen release.</p>}
      {r.alternatives.map(a => <div key={a.reference.id} className="space-y-2"><PolicyDetails assessment={a.assessment} /><Pins title={`Alternative reference · ${a.reference.id}`} value={a.reference} /></div>)}
    </section>
    {SCIENTIFIC_GROUPS.map(group => <section key={group} className="space-y-3" aria-label={`${groupLabels[group]} scientific fields`}>
      <h4 className="font-semibold">{groupLabels[group]}</h4>
      {r.cells.filter(c => c.group === group).map(c => <details key={c.property_key} className="rounded-lg border border-sage-border p-4">
        <summary className="cursor-pointer text-sm font-medium">{SCIENTIFIC_FIELDS[c.property_key].label} · {AVAILABILITY_LABELS[c.availability]} · {c.observations.length.toLocaleString("en-US")} recorded results</summary>
        <div className="mt-3 space-y-3">
          <p className="text-sm">{c.property_key} · {c.unit} · {label(c.reason_code)}</p>
          <p className="text-xs text-sage-muted">Availability basis: {label(c.availability_basis)}. Missing, not computed, not applicable and conflicted are distinct; none becomes zero.</p>
          <Pins title="Selected result and availability-evidence references" value={{ result_refs: c.result_refs, evidence_refs: c.evidence_refs }} />
          {c.observations.map(o => <Observation key={o.property.id} value={o} />)}
          {c.observations.length === 0 && <p className="text-sm">No registered observation for this selected material / state / structure.</p>}
        </div>
      </details>)}
      {["geometry", "competing_order"].includes(group) && <p className="text-sm text-sage-muted">Planned · no native scientific properties in rv2/1. A policy dimension is not a populated scientific measurement.</p>}
    </section>)}
  </section>;
}

export function ScientificDiscoveryMatrix() {
  const [catalog, setCatalog] = useState<ScientificCatalog | null>(null);
  const [selected, setSelected] = useState("");
  const [data, setData] = useState<ScientificReceipt | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [role, setRole] = useState<RoleGroup>("discovery");
  const [group, setGroup] = useState<string>("stability");
  const [expanded, setExpanded] = useState<string | null>(null);
  const epoch = useRef(0);
  const pending = useRef<AbortController | null>(null);
  const detailTrigger = useRef<HTMLButtonElement | null>(null);
  const begin = useCallback(() => {
    pending.current?.abort(); pending.current = new AbortController(); epoch.current++;
    setData(null); setExpanded(null); setError("");
    return { generation: epoch.current, signal: pending.current.signal };
  }, []);
  const refresh = useCallback(async () => {
    const current = begin(); setSelected(""); setCatalog(null); setBusy(true);
    try { const next = await getScientificCatalog(current.signal); if (epoch.current === current.generation && !current.signal.aborted) setCatalog(next); }
    catch { if (epoch.current === current.generation && !current.signal.aborted) setError(SCIENTIFIC_FAILURE); }
    finally { if (epoch.current === current.generation) setBusy(false); }
  }, [begin]);
  useEffect(() => {
    void refresh();
    const hide = () => { begin(); setCatalog(null); setSelected(""); setBusy(false); };
    const visibility = () => { if (document.visibilityState === "hidden") hide(); else void refresh(); };
    const restore = (event: PageTransitionEvent) => { if (event.persisted) void refresh(); };
    document.addEventListener("visibilitychange", visibility); window.addEventListener("pagehide", hide); window.addEventListener("pageshow", restore);
    return () => { epoch.current++; pending.current?.abort(); document.removeEventListener("visibilitychange", visibility); window.removeEventListener("pagehide", hide); window.removeEventListener("pageshow", restore); };
  }, [begin, refresh]);
  async function select(id: string) {
    const current = begin(); setSelected(id); setBusy(!!id); setQuery(""); setRole("discovery");
    const pin = catalog?.items.find(item => item.package_id === id);
    if (!pin) { setBusy(false); return; }
    try {
      const next = await getScientificProjection(pin, current.signal);
      // The generation guard is AFTER all hashing awaits, not just fetch.
      if (epoch.current === current.generation && !current.signal.aborted) setData(next);
    } catch { if (epoch.current === current.generation && !current.signal.aborted) setError(SCIENTIFIC_FAILURE); }
    finally { if (epoch.current === current.generation) setBusy(false); }
  }
  const rows = data?.payload.rows ?? [];
  const visible = rows.filter(r => roleGroup(r) === role && [r.assessment.formula, r.assessment.family, ...Object.keys(r.profile_assignment.mix)]
    .join(" ").toLocaleLowerCase("en-US").includes(query.trim().toLocaleLowerCase("en-US")));
  const fields = SCIENTIFIC_KEYS.filter(k => group === "all" || SCIENTIFIC_FIELDS[k].group === group);
  const active = visible.find(r => r.material.row_id === expanded);
  return <section aria-labelledby="scientific-matrix-heading" className="space-y-4 rounded-xl border border-sage-border bg-white p-4 sm:p-5">
    <div><h2 id="scientific-matrix-heading" className="text-xl font-semibold">Scientific material matrix</h2>
      <p className="mt-1 text-sm font-medium text-accent">{SCIENTIFIC_DISCLAIMER}</p>
      <p className="mt-2 text-sm leading-6 text-sage-muted">One material per row, with an explicitly reviewed representative state and next action. RPS 1,000–10,000 is research priority, not superconductivity probability. Compare only within the same frozen campaign, budget, policy and release. <a href="https://github.com/JackZH26/SCLib_JZIS/issues/78" className="underline">Evaluation and calibration limits</a>.</p>
    </div>
    <div className="flex flex-wrap items-end gap-3">
      <label className="min-w-0 flex-1 text-sm">Published scientific version
        <select className={`${inputStyle} mt-1 block w-full`} value={selected} disabled={!catalog?.items.length} onChange={e => void select(e.target.value)}>
          <option value="">Choose a published version explicitly</option>
          {catalog?.items.map(p => <option key={p.package_id} value={p.package_id}>{p.package_id} · payload {short(p.payload_sha256)}</option>)}
        </select>
      </label>
      <button type="button" className={inputStyle} onClick={() => void refresh()}>Refresh catalog</button>
    </div>
    {busy && <p role="status" className="text-sm text-sage-muted">{selected ? "Checking the selected publication and exact scientific payload…" : "Loading scientific publication catalog…"}</p>}
    {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</p>}
    {catalog?.status === "not_published" && <p role="status" className="rounded-lg bg-sage-surface p-4 text-sm">No scientific companion published yet. Native fields are supported, but no approved public version is available. No example materials or legacy scores have been substituted.</p>}
    {catalog && catalog.unavailable_count > 0 && <p role="status" className="text-sm text-sage-muted">{catalog.unavailable_count.toLocaleString("en-US")} configured publication(s) unavailable at this read point. They are not displayed.</p>}
    {catalog && catalog.items.length > 0 && !selected && <p className="text-sm text-sage-muted">Select a version to inspect its materials. No latest or highest-scoring version is selected automatically.</p>}
    {data && <>
      <div className="rounded-lg bg-sage-surface p-4 text-sm">
        <p className="font-medium">{data.payload.campaign.id} · version {data.payload.campaign.version} · release {data.payload.base.release_id}</p>
        <p className="mt-1">{data.payload.campaign.objective}</p>
        <p className="mt-2 text-xs leading-5 text-sage-muted">The browser matched original payload, selection and campaign bytes to their pins. Server checks describe a read point, not permanent approval. Refresh to recheck; leaving this page clears the matrix. This publication does not approve ML training or all scientific results.</p>
      </div>
      <Pins title="Frozen campaign, budget, publication and release pins" value={{ campaign: data.payload.campaign, base: data.payload.base,
        package_id: data.package_id, payload_sha256: data.payload_sha256, selection_sha256: data.selection_sha256,
        publication_sha256: data.publication_sha256, review_sha256: data.review_sha256, campaign_sha256: data.payload.campaign_sha256, policy_sha256: data.payload.policy_sha256 }} />
      <details className="rounded-lg border border-sage-border p-3"><summary className="cursor-pointer text-sm">Supported, populated and planned scientific fields</summary>
        <ul className="mt-3 grid gap-2 text-xs sm:grid-cols-2">{data.payload.capabilities.scientific_properties.map(c => <li key={c.property_key}>
          {SCIENTIFIC_FIELDS[c.property_key].label} ({c.unit}): storage / quantity supported · {c.populated_observations.toLocaleString("en-US")} observations · {c.exact_scientific_review_supported ? "exact sampled-phonon review supported" : "scientific review profile not implemented"}
        </li>)}</ul><p className="mt-3 text-xs text-sage-muted">Geometry and competing order: planned scientific properties. Other draft dictionary fields are not implemented native database properties.</p>
      </details>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="text-sm">Search material, family or profile<input className={`${inputStyle} mt-1 block w-full`} value={query} onChange={e => { setQuery(e.target.value); setExpanded(null); }} placeholder="Formula, family or profile" /></label>
        <label className="text-sm">Research role<select className={`${inputStyle} mt-1 block w-full`} value={role} onChange={e => { setRole(e.target.value as RoleGroup); setExpanded(null); }}>
          <option value="discovery">Discovery candidates ({rows.filter(r => roleGroup(r) === "discovery").length})</option>
          <option value="mechanism">Mechanism research ({rows.filter(r => roleGroup(r) === "mechanism").length})</option>
          <option value="controls">Reference / control materials ({rows.filter(r => roleGroup(r) === "controls").length})</option>
        </select></label>
        <label className="text-sm">Scientific columns<select className={`${inputStyle} mt-1 block w-full`} value={group} onChange={e => setGroup(e.target.value)}>
          <option value="all">All eight native fields</option>{SCIENTIFIC_GROUPS.map(g => <option key={g} value={g}>{groupLabels[g]}{["geometry", "competing_order"].includes(g) ? " · planned" : ""}</option>)}
        </select></label>
      </div>
      <p className="text-xs text-sage-muted">{visible.length.toLocaleString("en-US")} of {rows.length.toLocaleString("en-US")} materials shown. Frozen material order, not a new ranking. Controls are separate; “negative control” does not mean experimentally nonsuperconducting. Filters never change representatives, weights or scores.</p>
      {["geometry", "competing_order"].includes(group) && <p role="status" className="text-sm">Planned group: no native scientific columns to display. Policy dimensions remain separate.</p>}
      {visible.length === 0 ? <p role="status" className="rounded-lg bg-sage-surface p-4 text-sm">No materials match this role and search. Other roles may contain materials.</p> : <div className="overflow-x-auto rounded-lg border border-sage-border focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent" tabIndex={0} role="region" aria-label="Scrollable scientific material matrix">
        <table className="w-full min-w-[1400px] border-collapse text-left text-xs">
          <caption className="sr-only">One material per row in the selected frozen scientific publication. Scroll horizontally for scientific columns and review context.</caption>
          <thead className="bg-sage-surface"><tr>
            <th scope="col" className="sticky left-0 z-10 min-w-52 bg-sage-surface p-3">Material / family / profile</th>
            <th scope="col" className="p-3">RPS</th><th scope="col" className="min-w-28 p-3">P / G / A</th>
            <th scope="col" className="min-w-44 p-3">Selected state / pressure</th><th scope="col" className="min-w-44 p-3">Next action / role</th>
            {fields.map(k => <th scope="col" key={k} className="min-w-40 p-3">{SCIENTIFIC_FIELDS[k].label}{" "}<span className="block font-normal text-sage-muted">{SCIENTIFIC_FIELDS[k].unit === "1" ? "dimensionless" : SCIENTIFIC_FIELDS[k].unit}</span></th>)}
            <th scope="col" className="min-w-40 p-3">Evidence / review</th><th scope="col" className="min-w-52 p-3">Main barrier / constraints</th>
          </tr></thead>
          <tbody>{visible.map(r => {
            const a = r.assessment, s = a.result, observations = r.cells.flatMap(c => c.observations);
            return <tr key={r.material.row_id} className="border-t border-sage-border align-top">
              <th scope="row" className="sticky left-0 z-10 bg-white p-3 font-normal">
                <button type="button" aria-expanded={active?.material.row_id === r.material.row_id} aria-controls={active?.material.row_id === r.material.row_id ? "scientific-material-details" : undefined} className="min-h-11 text-left text-sm font-semibold text-accent underline underline-offset-4" onClick={event => { detailTrigger.current = event.currentTarget; setExpanded(expanded === r.material.row_id ? null : r.material.row_id); }}>{a.formula}</button>
                <span className="block">{a.family}</span><span className="mt-1 block text-sage-muted">{Object.entries(r.profile_assignment.mix).map(([k, v]) => `${label(k)}: ${scientificNumber(v)}`).join(" · ")}</span>
              </th>
              <td className="p-3"><strong className="text-base tabular-nums">{score(s.score_display)}</strong><span className="mt-1 block text-sage-muted">{label(s.eligibility)}</span></td>
              <td className="p-3 tabular-nums">{scientificNumber(s.p_lower)} / {scientificNumber(s.g_lower)} / {scientificNumber(s.a_lower)}<span className="mt-1 block text-sage-muted">Lower policy bounds</span></td>
              <td className="p-3">{a.state_summary}<span className="mt-1 block text-sage-muted">{pressure(r.state_context)}</span></td>
              <td className="p-3">{a.action_summary}<span className="mt-1 block text-sage-muted">{label(a.role)}</span></td>
              {fields.map(k => <td key={k} className="p-3"><CellValue cell={r.cells.find(c => c.property_key === k)!} /></td>)}
              <td className="p-3">{observations.length.toLocaleString("en-US")} recorded results<span className="mt-1 block text-sage-muted">{observations.filter(o => o.scientific_scope_accepted).length.toLocaleString("en-US")} accepted sampled-phonon reviews</span></td>
              <td className="p-3">Main barrier not separately declared<span className="mt-1 block text-sage-muted">{s.execution_constraint_reasons.join(" · ") || "No execution constraints declared"}</span></td>
            </tr>;
          })}</tbody>
        </table>
      </div>}
      {active && <MaterialDetails key={active.material.row_id} row={active} close={() => { setExpanded(null); detailTrigger.current?.focus(); }} />}
    </>}
  </section>;
}
