"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { StructureReferenceOptions } from "@/components/StructureReferenceOptions";
import { initialSupercellRepeats, occupancyDescription, structureHostContext, structureReferences } from "@/lib/discovery-structures";
import { compositionLabel, compositionOf, coordinateSha256, supercellModel } from "@/lib/discovery-site-candidates";
import { combinedPlan, generateCombinedCandidates, type CombinedBatch, type SiteChoices } from "@/lib/discovery-combined-candidates";
import { DiscoveryQeInput } from "@/components/DiscoveryQeInput";

const control = "mt-2 min-h-11 w-full min-w-0 rounded-md border border-sage-border bg-white px-3 py-2 text-sm";
const fmt = (value: number) => value.toLocaleString("en-US", { maximumFractionDigits: 6 });
const freshSite = (targetId = ""): SiteChoices => ({ targetId, replacements: "", vacancy: false, unchanged: false });
type Generated = { batch: CombinedBatch; json: string; hash: string };

export function DiscoveryCombinedCandidates({ initialReferenceId }: { initialReferenceId?: string }) {
  const [references] = useState(structureReferences);
  const [referenceId, setReferenceId] = useState(initialReferenceId ?? references[0].id);
  const [repeats, setRepeats] = useState(() => initialSupercellRepeats(references.find(ref => ref.id === (initialReferenceId ?? references[0].id))!));
  const [sites, setSites] = useState<SiteChoices[]>([freshSite()]);
  const [strain, setStrain] = useState("0");
  const [result, setResult] = useState<Generated | null>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [page, setPage] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [downloadStatus, setDownloadStatus] = useState("");
  const sequence = useRef(0);
  useEffect(() => () => { sequence.current++; }, []);
  const invalidate = () => { sequence.current++; setResult(null); setBusy(false); setError(""); setDownloadStatus(""); setPage(0); setSelectedIndex(0); };
  let model: ReturnType<typeof supercellModel> | null = null, modelError = "";
  try { model = supercellModel(referenceId, repeats.map(Number)); } catch (issue) { modelError = issue instanceof Error ? issue.message : "Check the source structure and supercell."; }
  const chosenSites = sites.map(site => ({ ...site, targetId: site.targetId || model?.atoms[0]?.id || "" }));
  const request = { referenceId, repeats: repeats.map(Number), sites: chosenSites, strain };
  let plan: ReturnType<typeof combinedPlan> | null = null, planError = "";
  if (model) { try { plan = combinedPlan(request); } catch (issue) { planError = issue instanceof Error ? issue.message : "Check the combination choices."; } }
  const updateSite = (index: number, change: Partial<SiteChoices>) => { invalidate(); setSites(chosenSites.map((site, i) => i === index ? { ...site, ...change } : site)); };
  const generate = async () => {
    if (!plan?.accepted.length) return;
    const run = ++sequence.current;
    setBusy(true); setError(""); setResult(null); setDownloadStatus("");
    try {
      const batch = await generateCombinedCandidates(request);
      const json = JSON.stringify(batch, null, 2) + "\n";
      const hash = await coordinateSha256(json);
      if (run === sequence.current) { setResult({ batch, json, hash }); setPage(0); setSelectedIndex(0); }
    } catch (issue) { if (run === sequence.current) setError(issue instanceof Error ? issue.message : "Candidate preparation failed."); }
    finally { if (run === sequence.current) setBusy(false); }
  };
  const selected = result?.batch.candidates[selectedIndex];
  const download = (kind: "json" | "sha256" | "cif") => {
    if (!result || !selected) return;
    let url: string | undefined;
    try {
      const name = `sclib-combined-${result.hash.slice(0, 12)}.json`;
      const content = kind === "json" ? result.json : kind === "sha256" ? `${result.hash}  ${name}\n` : selected.cif;
      url = URL.createObjectURL(new Blob([content], { type: kind === "json" ? "application/json" : kind === "cif" ? "chemical/x-cif" : "text/plain" }));
      const a = document.createElement("a"); a.href = url;
      a.download = kind === "cif" ? `sclib-combined-${selected.cif_sha256.slice(0, 12)}-unrelaxed.cif` : name + (kind === "sha256" ? ".sha256" : "");
      a.click(); setDownloadStatus(`${kind.toUpperCase()} download requested${kind === "json" ? ` for all ${result.batch.candidates.length} candidates` : ""}.`);
    } catch { setDownloadStatus("The browser could not start the download. Try again."); }
    finally { if (url) setTimeout(() => URL.revokeObjectURL(url!), 1000); }
  };

  return <div className="min-w-0 space-y-6">
    <section className="min-w-0 space-y-4" aria-labelledby="combined-source-title">
      <h2 id="combined-source-title" className="text-xl font-semibold">Source and supercell</h2>
      <div className="grid min-w-0 items-end gap-5 md:grid-cols-2">
        <label className="min-w-0 text-sm font-medium">Source structure<select className={control} value={referenceId} onChange={event => { invalidate(); setReferenceId(event.target.value); setRepeats(initialSupercellRepeats(references.find(ref => ref.id === event.target.value)!)); setSites([freshSite()]); }}><StructureReferenceOptions references={references} /></select></label>
        <fieldset className="min-w-0"><legend className="text-sm font-medium">Supercell repeats</legend><div className="grid grid-cols-3 gap-3">{["a", "b", "c"].map((axis, index) => <label className="min-w-0 text-xs text-sage-muted" key={axis}>Along {axis}<input className={control} type="number" min="1" max="4" step="1" value={repeats[index]} onChange={event => { invalidate(); setSites([freshSite()]); setRepeats(repeats.map((value, i) => index === i ? event.target.value : value)); }} /></label>)}</div></fieldset>
      </div>
      <p className="text-xs leading-5 text-sage-muted">{structureHostContext(references.find(ref => ref.id === referenceId)!).phase}. {occupancyDescription(references.find(ref => ref.id === referenceId)!)} <Link className="site-text-link" href={`/discovery/structures?reference=${referenceId}`}>Inspect source and conditions</Link></p>
      {modelError ? <p role="alert" className="border-l-2 border-accent pl-3 text-sm">{modelError}</p> : <p className="text-sm text-sage-muted">{compositionLabel(compositionOf(model!.atoms))} · {model!.atoms.length} original sites. Choose up to three distinct sites below.</p>}
    </section>

    {model && <section className="min-w-0 space-y-4 border-t border-sage-border pt-5" aria-labelledby="combined-sites-title">
      <h2 id="combined-sites-title" className="text-xl font-semibold">Site choices</h2>
      <p className="max-w-3xl text-sm leading-6 text-sage-muted">Each combination chooses one option at every listed site. Include an unchanged option to compare single changes with combined modifications.</p>
      {chosenSites.map((site, index) => <fieldset key={index} className="min-w-0 rounded-lg border border-sage-border bg-white p-4">
        <legend className="px-2 text-sm font-semibold">Modification {index + 1}</legend>
        <div className="grid min-w-0 gap-4 md:grid-cols-2">
          <label className="min-w-0 text-sm">Atomic site<select aria-label={`Modification ${index + 1} atomic site`} className={control} value={site.targetId} onChange={event => updateSite(index, { targetId: event.target.value, replacements: "" })}>{model!.atoms.map(atom => <option value={atom.id} key={atom.id}>{atom.label}: {atom.element} · cell [{atom.cell_translation.join(", ")}] · image {atom.source_expanded_index + 1}</option>)}</select></label>
          <label className="min-w-0 text-sm">Replacement elements<input aria-label={`Modification ${index + 1} replacement elements`} className={control} maxLength={128} placeholder="e.g. Al, Ca" value={site.replacements} onChange={event => updateSite(index, { replacements: event.target.value })} /></label>
          <label className="min-w-0 text-sm">Vacancy option<select aria-label={`Modification ${index + 1} vacancy option`} className={control} value={site.vacancy ? "yes" : "no"} onChange={event => updateSite(index, { vacancy: event.target.value === "yes" })}><option value="no">Exclude vacancy</option><option value="yes">Include vacancy</option></select></label>
          <label className="min-w-0 text-sm">Unchanged option<select aria-label={`Modification ${index + 1} unchanged option`} className={control} value={site.unchanged ? "yes" : "no"} onChange={event => updateSite(index, { unchanged: event.target.value === "yes" })}><option value="no">Require a change</option><option value="yes">Also keep original atom</option></select></label>
        </div>
        {sites.length > 1 && <button type="button" className="site-text-link mt-3 min-h-11 text-sm" onClick={() => { invalidate(); setSites(chosenSites.filter((_, i) => i !== index)); }}>Remove modification {index + 1}</button>}
      </fieldset>)}
      <button type="button" className="btn-outline disabled:opacity-50" disabled={sites.length >= 3} onClick={() => { const next = model!.atoms.find(atom => !chosenSites.some(site => site.targetId === atom.id)); if (next) { invalidate(); setSites([...chosenSites, freshSite(next.id)]); } }}>Add another site</button>
    </section>}

    <section className="min-w-0 space-y-4 border-t border-sage-border pt-5" aria-labelledby="combined-strain-title">
      <h2 id="combined-strain-title" className="text-xl font-semibold">Lattice changes and combination count</h2>
      <label className="block min-w-0 max-w-lg text-sm font-medium">Uniform linear changes (%)<input className={control} value={strain} maxLength={256} placeholder="e.g. -2, 0, 2" onChange={event => { invalidate(); setStrain(event.target.value); }} aria-describedby="combined-strain-help" /></label>
      <p id="combined-strain-help" className="max-w-3xl text-xs leading-5 text-sage-muted">Up to 8 comma-separated values from −10 to +10, with at most 6 decimal places. All lattice vectors scale by 1 + change / 100. Angles and fractional positions stay fixed. These choices do not specify pressure or a stable strain range.</p>
      <div aria-live="polite" className="space-y-2 text-sm">{plan ? <><p>{plan.counts.raw_combinations} raw combinations → {plan.counts.distinct_combinations} distinct combinations → <strong>{plan.counts.generated_candidates} coordinate candidates</strong>.</p>{plan.excluded.length > 0 && <p className="text-sage-muted">Excluded: {plan.counts.unchanged_baselines} unchanged baseline, {plan.counts.empty_cells} empty cells.</p>}</> : <p className="text-sage-muted">{model ? planError : "Choose an available ordered source model to estimate combinations."}</p>}</div>
      <button type="button" className="btn-primary disabled:opacity-50" disabled={busy || !plan?.accepted.length} onClick={generate}>{busy ? "Preparing combinations…" : "Generate combined candidates"}</button>
      <p className="max-w-3xl text-xs leading-5 text-sage-muted">At most 64 distinct combinations and 96 original atom sites. Duplicated choices are removed; site arrangements are not reduced by symmetry. Size limits do not establish defect convergence.</p>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    </section>

    {result && selected && <section className="min-w-0 space-y-5 border-t border-sage-border pt-5" aria-labelledby="combined-results-title">
      <h2 id="combined-results-title" className="text-xl font-semibold">{result.batch.candidates.length} combined coordinate candidates</h2>
      <div role="region" aria-label="Scrollable combined candidate table" tabIndex={0} className="overflow-x-auto rounded-lg border border-sage-border bg-white"><table className="w-full min-w-[620px] text-left text-sm"><caption className="sr-only">Combined site modifications and uniform lattice proposals</caption><thead className="bg-sage-surface text-xs text-sage-muted"><tr>{["Inspect", "Site changes", "Lattice change", "Composition", "Sites"].map(label => <th key={label} scope="col" className="p-3">{label}</th>)}</tr></thead><tbody>{result.batch.candidates.slice(page * 8, page * 8 + 8).map((candidate, i) => <tr key={candidate.id} className="border-t border-sage-border"><td className="p-3"><button className="min-h-11 rounded-md border border-sage-border px-3 aria-pressed:bg-sage-surface" aria-pressed={selectedIndex === page * 8 + i} aria-label={`Inspect combination ${page * 8 + i + 1}`} onClick={() => { setSelectedIndex(page * 8 + i); setDownloadStatus(""); }}>{page * 8 + i + 1}</button></td><th scope="row" className="p-3 font-medium">{candidate.edits.map(edit => `${edit.target.label}: ${edit.target.element} → ${edit.operation.element ?? "vacancy"}`).join("; ") || "Lattice only"}</th><td className="p-3 tabular-nums">{fmt(candidate.strain_percent)}%</td><td className="whitespace-nowrap p-3">{compositionLabel(candidate.composition)}</td><td className="p-3">{candidate.atoms.length}</td></tr>)}</tbody></table></div>
      <nav aria-label="Combination pages" className="flex flex-wrap items-center gap-4 text-sm"><button className="btn-outline disabled:opacity-50" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous combinations</button><span>Page {page + 1} of {Math.ceil(result.batch.candidates.length / 8)}</span><button className="btn-outline disabled:opacity-50" disabled={(page + 1) * 8 >= result.batch.candidates.length} onClick={() => setPage(page + 1)}>Next combinations</button></nav>
      <div className="grid min-w-0 gap-5 md:grid-cols-2">
        <div className="min-w-0 space-y-3"><h3 className="text-lg font-semibold">Selected combination {selectedIndex + 1}</h3><p className="text-sm">{compositionLabel(compositionOf(result.batch.baseline.atoms))} → {compositionLabel(selected.composition)}</p><p className="text-sm">Linear change: {fmt(selected.strain_percent)}%. Geometric volume change: {fmt((selected.volume_ratio - 1) * 100)}%.</p><p className="text-sm">Changed original sites: {selected.nominal_change.changed_sites} / {selected.nominal_change.original_total_sites} ({fmt(selected.nominal_change.original_total_site_fraction * 100)}%).</p>{selected.nominal_change.by_original_species.map(item => <p className="text-sm" key={item.element}>{item.element} sites changed: {item.changed_sites} / {item.original_species_sites} ({fmt(item.fraction * 100)}%).</p>)}<p className="text-xs leading-5 text-sage-muted">Fractions describe nominal changes to the original cell, including vacancies. They are not measured doping or carrier concentrations.</p></div>
        <div className="min-w-0 space-y-3"><h3 className="text-lg font-semibold">Unrelaxed coordinates</h3><p className="text-sm leading-6">The exported CIF contains every resulting atom in P1. Charge, magnetic state and target temperature/pressure remain to be chosen; energies and superconducting properties have not been calculated.</p><button className="btn-outline" onClick={() => download("cif")}>Download selected combined CIF</button><p className="text-xs leading-5 text-sage-muted">Choose electronic settings, relax the intended state and check size/numerical convergence before evaluating stability, pairing or coherence.</p></div>
      </div>
      <div className="flex flex-wrap gap-3"><button className="btn-outline" onClick={() => download("json")}>Download all candidates JSON</button><button className="btn-outline" onClick={() => download("sha256")}>Download JSON SHA-256</button></div><p role="status" className="text-xs text-sage-muted">{downloadStatus}</p>
      <DiscoveryQeInput key={selected.id} batch={result.batch} candidateId={selected.id} />
      <details className="min-w-0 text-xs leading-5 text-sage-muted"><summary className="w-fit cursor-pointer font-medium text-accent-deep">Inspect coordinates and lineage</summary><div className="mt-3 min-w-0 space-y-3"><p>Parent: <code className="break-all">{result.batch.parent_id}</code></p><p>Candidate: <code className="break-all">{selected.id}</code></p><p>CIF SHA-256: <code className="break-all">{selected.cif_sha256}</code></p><p>The full JSON retains original source coordinates, cell, metadata, requested choices, discarded combinations and all candidate coordinates. No catalogue association, execution result or training permission is created.</p><div role="region" aria-label="Scrollable combined coordinates" tabIndex={0} className="overflow-x-auto"><table className="w-full min-w-[540px] text-left tabular-nums"><caption className="sr-only">Selected combination fractional coordinates</caption><thead><tr>{["Site", "Element", "x", "y", "z"].map(label => <th scope="col" key={label} className="p-2">{label}</th>)}</tr></thead><tbody>{selected.atoms.map(atom => <tr key={atom.id}><th scope="row" className="p-2">{atom.label}</th><td className="p-2">{atom.element}</td>{atom.fractional.map((value, i) => <td key={i} className="p-2">{fmt(value)}</td>)}</tr>)}</tbody></table></div></div></details>
    </section>}
  </div>;
}
