"use client";

import { useRef, useState } from "react";
import { FormulaDisplay } from "@/components/FormulaDisplay";
import type { ResearchCatalogue, ResearchGroup, ResearchState } from "@/lib/discovery-research-catalogue";
import type { DiscoveryNumericalPilotSummary } from "@/lib/discovery-numerical-pilot";

const number = (n: number) => n.toLocaleString("en-US", { maximumFractionDigits: 8 });
const changes = (s: ResearchState) => s.edits.map(e => e.kind === "vacancy" ? `${e.original_element} vacancy` : `${e.original_element} → ${e.element}`).join(" + ") || "Strain reference";
const anchor = (s: ResearchState) => `research-state-${s.id.split(":")[1]}`;

export function ResearchCatalogueBoard({ catalog, pilot = null }: { catalog: ResearchCatalogue; pilot?: DiscoveryNumericalPilotSummary | null }) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [status, setStatus] = useState("");
  const search = query.trim().toLowerCase().replace(/[₀₁₂₃₄₅₆₇₈₉]/g, d => String("₀₁₂₃₄₅₆₇₈₉".indexOf(d)));
  const visible = catalog.groups.filter(g => {
    const states = catalog.states.filter(s => s.group_id === g.id);
    return [g.formula, g.reduced_formula, g.host_formula, ...states.map(changes)].some(v => v.toLowerCase().includes(search))
      && (filter === "all" || states.some(s => filter === "strain" ? s.strain_micro_percent !== 0 : s.edits.some(e => e.kind === filter)));
  });
  function download(s: ResearchState, kind: "cif" | "json") {
    const parent = catalog.parents.find(p => p.id === s.parent_id)!;
    const source = catalog.sources.find(p => p.id === parent.source_id)!;
    const occurrences = catalog.occurrences.filter(o => s.occurrence_ids.includes(o.id));
    const selected = occurrences.find(o => o.id === s.primary_occurrence_id)!;
    let url: string | undefined;
    try {
      const content = kind === "cif" ? selected.cif_text : JSON.stringify({ schema_version: "research-state-export/2.0.0", catalog_version: catalog.version,
        source, parent, state: s, occurrences, scientific_acceptance: false, rps_score: null, rank: null }, null, 2) + "\n";
      url = URL.createObjectURL(new Blob([content], { type: kind === "cif" ? "chemical/x-cif" : "application/json" }));
      const link = document.createElement("a"); link.href = url; link.download = `${s.formula}-${s.strain_micro_percent}-${selected.cif_sha256.slice(0, 12)}.${kind}`;
      link.click(); setStatus(`Prepared ${s.formula} ${kind.toUpperCase()} download.`);
    } catch { setStatus("The download could not be prepared. Try again."); }
    finally { if (url) { const completed = url; setTimeout(() => URL.revokeObjectURL(completed), 1000); } }
  }
  return <section className="min-w-0 space-y-3" aria-labelledby="proposal-candidates-heading">
    <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
      <h2 id="proposal-candidates-heading" className="text-xl font-semibold">Candidate materials</h2>
      <p className="text-sm text-sage-muted">{catalog.counts.composition_groups} composition groups · {catalog.counts.coordinate_states} coordinate states · Unranked</p>
      <details className="max-w-3xl text-sm text-sage-muted"><summary className="cursor-pointer">Selection and evidence</summary>
        <div className="mt-2 space-y-2 leading-6"><p>{catalog.selection_basis}</p>
          <p>Rows group composition variants of captured host coordinates. Expand a row to inspect each modification and strain state. These are reproducible, unrelaxed proposals; no potential score or candidate Tc has been evaluated.</p>
          <p>{catalog.counts.source_entries} retained entries represent {catalog.counts.coordinate_states} distinct coordinate states. Duplicate occurrences retain their original IDs and CIF files. Counts are not independent experiments.</p>
          <p>RPS assessments use an explicit research action, evidence and campaign budget. Ranked, formally published assessments appear separately when available.</p>
          <p className="break-words [overflow-wrap:anywhere]">Catalogue: {catalog.version}</p></div>
      </details>
    </div>
    <div className="grid gap-3 sm:grid-cols-2 lg:max-w-2xl">
      <label className="min-w-0 text-sm font-medium">Find a proposal<input type="search" className="mt-1 block min-h-11 w-full rounded-lg border border-sage-border bg-white px-3" placeholder="Formula, host or modification" value={query} onChange={e => setQuery(e.target.value)} /></label>
      <label className="min-w-0 text-sm font-medium">Modification<select className="mt-1 block min-h-11 w-full rounded-lg border border-sage-border bg-white px-3" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">All modifications</option><option value="substitution">Substitution</option><option value="vacancy">Vacancy</option><option value="strain">Strain</option></select></label>
    </div>
    <div className="relative max-w-full overflow-x-auto rounded-xl border border-sage-border focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent" role="region" tabIndex={0} aria-label="Structure proposal table, scroll horizontally for all columns">
      <table className="w-full min-w-[720px] border-collapse text-left text-sm"><caption className="sr-only">Unranked proposals grouped by composition. Expand a material to inspect its states.</caption>
        <thead className="bg-sage-surface text-sage-muted"><tr>{["Material", "Host / modification", "States", "Research priority", "Next step"].map(h => <th key={h} scope="col" className="p-3">{h}</th>)}</tr></thead>
        <tbody>{visible.map(g => <GroupRow key={g.id} group={g} catalog={catalog} pilot={pilot} download={download} />)}</tbody>
      </table>
    </div>
    {!visible.length && <p className="text-sm text-sage-muted">No proposals match these filters.</p>}
    {status && <p role="status" className="text-sm text-sage-muted">{status}</p>}
  </section>;
}

function GroupRow({ group, catalog, pilot, download }: { group: ResearchGroup; catalog: ResearchCatalogue; pilot: DiscoveryNumericalPilotSummary | null; download: (s: ResearchState, kind: "cif" | "json") => void }) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const states = group.state_ids.map(id => catalog.states.find(s => s.id === id)!);
  const detailsId = `proposal-group-${group.id.split(":")[1]}`;
  const studied = pilot?.states.filter(s => s.catalogue_group_id === group.id && group.state_ids.includes(s.catalogue_state_id)) ?? [];
  return <>
    <tr className="border-t border-sage-border bg-white align-top">
      <th scope="row" className="p-3 font-normal"><button ref={trigger} className="min-h-8 text-left font-semibold text-accent underline decoration-dotted underline-offset-4" aria-label={group.formula} aria-expanded={open} aria-controls={open ? detailsId : undefined} onClick={() => setOpen(v => !v)}><FormulaDisplay formula={group.formula} /></button></th>
      <td className="p-3"><FormulaDisplay formula={group.host_formula} /><p className="text-xs text-sage-muted">{changes(states[0])}</p></td>
      <td className="p-3">{states.length} unrelaxed</td><td className="p-3">Unranked</td><td className="p-3">{studied.length ? <a href="#discovery-numerical-pilot" className="site-text-link">{studied.some(s => s.decision?.outcome === "redirect") ? "Refine k-mesh sampling" : "Review numerical pilot"}</a> : "Review state, methods and inputs"}</td>
    </tr>
    {open && <tr id={detailsId} className="border-t border-sage-border bg-sage-surface"><td colSpan={5} className="p-4"><div className="max-w-[calc(100vw-4rem)] space-y-4 md:max-w-none">
      <div className="flex items-start justify-between gap-3"><h3 className="font-semibold">{group.formula} · Proposed states</h3><button className="min-h-9 rounded-lg border border-sage-border bg-white px-3" onClick={() => { setOpen(false); trigger.current?.focus(); }}>Close</button></div>
      <p>Stability, electronic state, pairing, coherence, geometry response and competing order: unknown. Pressure, temperature, charge and magnetic state are unassigned.</p>
      {states.map(s => {
        const parent = catalog.parents.find(p => p.id === s.parent_id)!;
        const source = catalog.sources.find(p => p.id === parent.source_id)!;
        const occurrence = catalog.occurrences.find(o => o.id === s.primary_occurrence_id)!;
        const observation = studied.find(p => p.catalogue_state_id === s.id);
        return <section key={s.id} className="min-w-0 space-y-2 border-t border-sage-border pt-3" aria-label={`${s.formula}, lattice change ${number(s.strain_micro_percent / 1e6)} percent`}>
          <h4 className="font-semibold">Lattice change {number(s.strain_micro_percent / 1e6)}% · {s.atoms.length} atoms</h4>
          <p>{changes(s)}{s.edits.length ? ` at ${s.edits.map(e => `${e.target_id} (source ${e.source_site_label})`).join("; ")}` : ""}. Uniform lattice-length change; fractional coordinates fixed. Strain does not assign pressure.</p>
          {observation && <p className="text-sm">Numerical pilot: {observation.assessment === "sampled_window_outside_tolerance" ? "the sampled mesh window exceeds tolerance" : observation.assessment === "sampled_window_within_tolerance" ? "the sampled mesh window is within tolerance" : "numerical review remains incomplete"}. <a className="site-text-link" href="#discovery-numerical-pilot">Inspect original readings and the next research case</a>.</p>}
          <div className="flex flex-wrap gap-3"><a href={`#${anchor(s)}`} className="site-text-link inline-flex min-h-11 items-center">Start a research case</a><button className="btn-outline" onClick={() => download(s, "cif")}>Download unrelaxed CIF</button><button className="btn-outline" onClick={() => download(s, "json")}>Download state JSON</button></div>
          <details><summary className="cursor-pointer py-2">Source, coordinates and occurrence aliases</summary><div className="space-y-2">
            <p><a className="site-text-link" href={source.entry_url}>COD {source.record_id}</a>, revision {source.revision} · <a className="site-text-link" href={source.license_url}>{source.license}</a></p>
            <p>Cell: {(["a", "b", "c", "alpha", "beta", "gamma"] as const).map(k => `${k} = ${number(s.cell[k])}${k.length === 1 ? " Å" : "°"}`).join("; ")}.</p>
            <p className="break-all text-xs">State: {s.id}</p><p className="break-all text-xs">CIF SHA-256: {occurrence.cif_sha256}</p>
            <ul className="space-y-1 text-xs">{catalog.occurrences.filter(o => s.occurrence_ids.includes(o.id)).map(o => <li key={o.id} className="break-all">{o.legacy_candidate_id} · retained CIF {o.cif_sha256}</li>)}</ul>
            <pre tabIndex={0} role="region" aria-label={`${s.formula} full CIF coordinates at ${number(s.strain_micro_percent / 1e6)} percent`} className="max-w-full overflow-x-auto rounded-lg border border-sage-border bg-white p-3 text-xs focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">{occurrence.cif_text}</pre>
          </div></details>
        </section>;
      })}
    </div></td></tr>}
  </>;
}
