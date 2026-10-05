"use client";

import { useEffect, useRef, useState } from "react";
import { FormulaDisplay } from "@/components/FormulaDisplay";
import type { ResearchProposal, ResearchProposalCatalog } from "@/lib/discovery-proposals";

const axisLabels = [
  ["stability", "Stability"], ["electronic", "Electronic state"], ["pairing", "Pairing"],
  ["coherence", "Coherence"], ["geometry", "Geometry"], ["competing_order", "Competing order"],
] as const;
const number = (value: number) => value.toLocaleString("en-US", { maximumFractionDigits: 8 });
const change = (proposal: ResearchProposal) => proposal.operation.kind === "vacancy" ? "Mg vacancy" : `${proposal.operation.element} substitution`;

/** This separate proposal catalogue supplies no RPS scores or scientific result cells. */
export function ResearchProposalBoard({ catalog }: { catalog: ResearchProposalCatalog }) {
  const [query, setQuery] = useState("");
  const [operation, setOperation] = useState("all");
  const [message, setMessage] = useState("");
  const downloads = useRef(new Set<string>());
  useEffect(() => () => {
    for (const url of downloads.current) URL.revokeObjectURL(url);
    downloads.current.clear();
  }, []);
  const search = query.trim().toLowerCase().replace(/[₀₁₂₃₄₅₆₇₈₉]/g, digit => String("₀₁₂₃₄₅₆₇₈₉".indexOf(digit)));
  const visible = catalog.proposals.filter(proposal =>
    (operation === "all" || proposal.operation.kind === operation)
    && [proposal.formula, proposal.host_formula, change(proposal)].some(value => value.toLowerCase().includes(search)));
  function download(proposal: ResearchProposal, kind: "cif" | "json") {
    let url: string | undefined;
    let link: HTMLAnchorElement | undefined;
    try {
      const content = kind === "cif" ? proposal.structure.cif_text : JSON.stringify({
        schema_version: "research-proposal-export/1.0.0", catalog_schema_version: catalog.schema_version, catalog_version: catalog.version,
        formal_scientific_release: catalog.formal_scientific_release, rps_release: catalog.rps_release,
        human_scientific_review: catalog.human_scientific_review, source: catalog.source, reference: catalog.reference, proposal,
      }, null, 2) + "\n";
      url = URL.createObjectURL(new Blob([content], { type: kind === "cif" ? "chemical/x-cif;charset=utf-8" : "application/json;charset=utf-8" }));
      downloads.current.add(url);
      link = document.createElement("a"); link.href = url;
      link.download = `${proposal.formula}-unrelaxed-${proposal.structure.cif_sha256.slice(0, 12)}.${kind}`;
      document.body.appendChild(link); link.click();
      setMessage(`Prepared ${proposal.formula} ${kind.toUpperCase()} download. This is an unrelaxed structure proposal.`);
    } catch {
      setMessage("The proposal download could not be prepared. Retry the download.");
    } finally {
      link?.remove();
      if (url) {
        const completedUrl = url;
        setTimeout(() => { URL.revokeObjectURL(completedUrl); downloads.current.delete(completedUrl); }, 1000);
      }
    }
  }
  return <section className="min-w-0 space-y-3" aria-labelledby="proposal-candidates-heading">
    <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
      <h2 id="proposal-candidates-heading" className="text-xl font-semibold">Candidate materials</h2>
      <p className="text-sm text-sage-muted">{catalog.proposals.length} structure proposals · Unranked</p>
      <details className="min-w-0 max-w-3xl text-sm text-sage-muted">
        <summary className="cursor-pointer">Status and evidence</summary>
        <div className="mt-2 space-y-2 leading-6">
          <p>Ordered site modifications of the MgB₂ reference. Structure bytes and composition have been checked; physical stability, electronic state, pairing, coherence and Tc have not been established for these proposals.</p>
          <p>No RPS score or potential ranking is assigned. Rows retain catalogue order. Research-priority assessment requires a defined state, action, evidence and an actual resource budget.</p>
          <p>These proposals form a separate catalogue from published RPS assessments and accepted scientific properties. No human scientific review is recorded. Host properties and other calculations are not inherited.</p>
          <p className="break-words [overflow-wrap:anywhere]">Catalogue: {catalog.version}. MgB₂ is the parent reference and is not counted as a proposal.</p>
        </div>
      </details>
    </div>
    <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:max-w-2xl">
      <label className="min-w-0 text-sm font-medium">Find a proposal
        <input type="search" value={query} placeholder="Formula, host or modification" onChange={event => setQuery(event.target.value)} className="mt-1 block min-h-11 w-full min-w-0 rounded-lg border border-sage-border bg-white px-3" />
      </label>
      <label className="min-w-0 text-sm font-medium">Modification
        <select value={operation} onChange={event => setOperation(event.target.value)} className="mt-1 block min-h-11 w-full min-w-0 rounded-lg border border-sage-border bg-white px-3">
          <option value="all">All modifications</option><option value="substitution">Substitution</option><option value="vacancy">Vacancy</option>
        </select>
      </label>
    </div>
    <div className="max-w-full overflow-x-auto rounded-xl border border-sage-border focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent" tabIndex={0} role="region" aria-label="Structure proposal table, scroll horizontally for all columns">
      <table className="w-full min-w-[760px] border-collapse text-left text-sm">
        <caption className="sr-only">Unranked structure proposals. Click a material for its full state, source and coordinates.</caption>
        <thead className="bg-sage-surface text-sage-muted"><tr>
          <th scope="col" className="p-3">Material</th><th scope="col" className="p-3">Host / modification</th>
          <th scope="col" className="p-3">Research priority</th><th scope="col" className="p-3">State</th><th scope="col" className="p-3">Next step</th>
        </tr></thead>
        <tbody>{visible.map(proposal => <ProposalRow key={proposal.id} proposal={proposal} catalog={catalog} download={download} />)}</tbody>
      </table>
    </div>
    {!visible.length && <p className="text-sm text-sage-muted">No proposals match these filters.</p>}
    {message && <p role="status" className="text-sm text-sage-muted">{message}</p>}
  </section>;
}

function ProposalRow({ proposal, catalog, download }: {
  proposal: ResearchProposal; catalog: ResearchProposalCatalog; download: (proposal: ResearchProposal, kind: "cif" | "json") => void;
}) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const detailsId = `proposal-${proposal.id.slice("site-candidate:".length)}`;
  const cell = proposal.structure.cell;
  return <>
    <tr className="border-t border-sage-border bg-white align-top">
      <th scope="row" className="p-3 font-normal"><button ref={trigger} type="button" aria-label={proposal.formula} aria-expanded={open} aria-controls={open ? detailsId : undefined} onClick={() => setOpen(value => !value)} className="min-h-8 break-words text-left font-semibold text-accent underline decoration-dotted underline-offset-4"><FormulaDisplay formula={proposal.formula} /></button></th>
      <td className="p-3"><p><FormulaDisplay formula={proposal.host_formula} /></p><p className="text-xs text-sage-muted">{change(proposal)}</p></td>
      <td className="p-3">Unranked</td><td className="p-3">Unrelaxed</td><td className="p-3">Review state, methods and inputs</td>
    </tr>
    {open && <tr id={detailsId} className="border-t border-sage-border bg-sage-surface"><td colSpan={5} className="p-4"><div className="max-w-[calc(100vw-4rem)] md:max-w-none">
      <div className="flex items-start justify-between gap-3">
        <h3 className="font-semibold">{proposal.formula} · Structure proposal</h3>
        <button type="button" onClick={() => { setOpen(false); trigger.current?.focus(); }} className="min-h-9 rounded-lg border border-sage-border bg-white px-3">Close</button>
      </div>
      <div className="mt-3 grid min-w-0 gap-5 md:grid-cols-2">
        <section className="min-w-0 space-y-2" aria-label="Proposed state">
          <h4 className="font-semibold">Host, change and state</h4>
          <p>{proposal.host_formula} · {proposal.operation.repeats.join(" × ")} ordered supercell · {number(proposal.structure.atom_count)} atoms after modification.</p>
          <p>{change(proposal)} at {proposal.operation.target.label} (source site {proposal.operation.target.source_label}), fractional position ({proposal.operation.target.fractional.map(number).join(", ")}). One of eight Mg sites changed: 12.5% of the original Mg sites, not a measured concentration.</p>
          <p>Unrelaxed coordinates. Pressure, temperature, charge and magnetic state have not been assigned.</p>
          <p>Cell: a = {number(cell.a)} Å, b = {number(cell.b)} Å, c = {number(cell.c)} Å; α = {number(cell.alpha)}°, β = {number(cell.beta)}°, γ = {number(cell.gamma)}°.</p>
          <p>Composition: {Object.entries(proposal.structure.composition).map(([element, count]) => `${element}: ${number(count)}`).join(" · ")}.</p>
          <p className="break-all text-xs text-sage-muted">Proposal ID: {proposal.id}</p>
        </section>
        <section className="min-w-0 space-y-2" aria-label="Research evidence and next step">
          <h4 className="font-semibold">Evidence and next step</h4>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1">{axisLabels.map(([key, label]) => <div key={key} className="min-w-0"><dt className="text-sage-muted">{label}</dt><dd>Unknown</dd></div>)}</dl>
          <p>{proposal.next_action.summary}</p>
          <p>No RPS score, rank or formal scientific approval is assigned. No candidate Tc or inherited host results are supplied.</p>
          <a href="#discovery-tools" className="site-text-link inline-flex min-h-11 items-center">Open research tools</a>
        </section>
      </div>
      <section className="mt-4 min-w-0 space-y-2 border-t border-sage-border pt-3" aria-label="Proposal source and files">
        <h4 className="font-semibold">Source and retained structure</h4>
        <p><a className="site-text-link" href={catalog.source.entry_url}>COD {catalog.source.record_id}</a>, revision {catalog.source.revision}. <a className="site-text-link" href={catalog.source.cif_url}>Parent CIF</a> · <a className="site-text-link" href={catalog.source.license_url}>{catalog.source.license}</a></p>
        <p className="text-xs text-sage-muted">{catalog.source.license_basis}</p>
        <p className="break-all text-xs text-sage-muted">Parent CIF SHA-256: {catalog.source.cif_sha256}</p>
        <p className="break-all text-xs text-sage-muted">Proposal CIF SHA-256: {proposal.structure.cif_sha256}</p>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="min-h-11 rounded-lg border border-sage-border bg-white px-3" onClick={() => download(proposal, "cif")}>Download unrelaxed CIF</button>
          <button type="button" className="min-h-11 rounded-lg border border-sage-border bg-white px-3" onClick={() => download(proposal, "json")}>Download proposal JSON</button>
        </div>
        <details><summary className="cursor-pointer py-2">Full CIF coordinates</summary><pre tabIndex={0} role="region" aria-label={`${proposal.formula} full CIF coordinates`} className="max-w-full overflow-x-auto rounded-lg border border-sage-border bg-white p-3 text-xs focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">{proposal.structure.cif_text}</pre></details>
      </section>
    </div></td></tr>}
  </>;
}
