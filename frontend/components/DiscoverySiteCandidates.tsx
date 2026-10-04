"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { StructureReferenceOptions } from "@/components/StructureReferenceOptions";
import { initialSupercellRepeats, occupancyDescription, structureHostContext, fractionalToCartesian, latticeBasis, structureReferences, type Vector3 } from "@/lib/discovery-structures";
import { compositionLabel, compositionOf, coordinateSha256, generateSiteCandidates, siteOperations, supercellModel,
  type SiteCandidate, type SiteCandidateBatch } from "@/lib/discovery-site-candidates";

const control = "mt-2 min-h-11 w-full rounded-lg border border-sage-border bg-white px-3 py-2 text-sm";
const percent = (value: number) => (value * 100).toLocaleString("en-US", { maximumFractionDigits: 4 });
const positions: Vector3[] = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1], [1, 1, 1]];
const edges = [[0, 1], [0, 2], [0, 4], [1, 3], [1, 5], [2, 3], [2, 6], [3, 7], [4, 5], [4, 6], [5, 7], [6, 7]];

function SiteFigure({ batch, candidate }: { batch: SiteCandidateBatch; candidate: SiteCandidate }) {
  const basis = latticeBasis(batch.source_reference).map((vector, index) => vector.map(value => value * batch.baseline.repeats[index]) as Vector3);
  const project = (point: number[]): [number, number] => {
    const [x, y, z] = fractionalToCartesian(point, basis);
    return [(x - y) / Math.sqrt(2), (x + y) / Math.sqrt(6) - z * Math.sqrt(2 / 3)];
  };
  const bounds = positions.map(project);
  const xs = bounds.map(point => point[0]), ys = bounds.map(point => point[1]);
  const xmin = Math.min(...xs), xmax = Math.max(...xs), ymin = Math.min(...ys), ymax = Math.max(...ys);
  const zoom = Math.min(300 / (xmax - xmin), 210 / (ymax - ymin));
  const display = (point: number[]) => { const [x, y] = project(point); return [200 + (x - (xmin + xmax) / 2) * zoom, 140 + (y - (ymin + ymax) / 2) * zoom]; };
  const changed = display(candidate.target_atom.fractional);
  return <figure className="min-w-0 rounded-lg border border-sage-border bg-white p-3">
    <svg viewBox="0 0 400 285" className="h-auto w-full" role="img" aria-label={`${candidate.operation.kind} at ${candidate.target_atom.label} in a ${batch.baseline.repeats.join(" by ")} supercell`}>
      <title>{`Selected ${candidate.operation.kind} coordinate proposal`}</title>
      <desc>Green ring marks the one changed site. Other sites are open circles. The cell is periodically repeated, projections can overlap, and no bonds are inferred.</desc>
      {edges.map(([from, to], index) => { const a = display(positions[from]), b = display(positions[to]); return <line key={index} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke="#6b7c6b" strokeWidth={1} />; })}
      {candidate.atoms.map(atom => { const [x, y] = display(atom.fractional); return <circle key={atom.id} data-atom-id={atom.id} cx={x} cy={y} r={3.5} fill={atom.id === candidate.target_atom.id ? "#24503A" : "white"} stroke="#5a6b5a"><title>{`${atom.label} ${atom.element}; fractional ${atom.fractional.map(value => value.toPrecision(6)).join(", ")}`}</title></circle>; })}
      <circle cx={changed[0]} cy={changed[1]} r={9} fill="none" stroke="#24503A" strokeWidth={2.5} strokeDasharray={candidate.operation.kind === "vacancy" ? "3 3" : undefined} />
    </svg>
    <figcaption className="text-xs leading-5 text-sage-muted">Green ring: selected site {candidate.target_atom.label}. {candidate.operation.kind === "vacancy" ? "Dashed ring marks the removed atom." : `${candidate.target_atom.element} is replaced by ${candidate.operation.element}.`} Markers have arbitrary size; projected atoms can overlap.</figcaption>
  </figure>;
}

type Generated = { batch: SiteCandidateBatch; json: string; sha256: string };

export function DiscoverySiteCandidates({ initialReferenceId }: { initialReferenceId?: string }) {
  const [references] = useState(structureReferences);
  const [referenceId, setReferenceId] = useState(initialReferenceId ?? references[0].id);
  const [repeats, setRepeats] = useState(() => initialSupercellRepeats(references.find(ref => ref.id === (initialReferenceId ?? references[0].id))!));
  const [targetId, setTargetId] = useState("");
  const [replacements, setReplacements] = useState("");
  const [vacancy, setVacancy] = useState(false);
  const [generated, setGenerated] = useState<Generated | null>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [downloadStatus, setDownloadStatus] = useState("");
  const sequence = useRef(0);
  useEffect(() => () => { sequence.current++; }, []);
  const invalidate = () => { sequence.current++; setGenerated(null); setSelectedIndex(0); setBusy(false); setError(""); setDownloadStatus(""); };
  let model: ReturnType<typeof supercellModel> | null = null;
  let modelError = "";
  try { model = supercellModel(referenceId, repeats.map(Number)); } catch (issue) { modelError = issue instanceof Error ? issue.message : "The source model is unavailable."; }
  const target = model?.atoms.find(atom => atom.id === targetId) ?? model?.atoms[0];
  let estimatedCount = 0;
  let operationError = "";
  if (target) { try { estimatedCount = siteOperations(replacements, vacancy, target.element).length; } catch (issue) { operationError = issue instanceof Error ? issue.message : "Check the proposed operation."; } }
  const generate = async () => {
    if (!model || !target || !estimatedCount) return;
    const run = ++sequence.current;
    setBusy(true); setError(""); setGenerated(null); setDownloadStatus("");
    try {
      const batch = await generateSiteCandidates(referenceId, repeats.map(Number), target.id, replacements, vacancy);
      const json = JSON.stringify(batch, null, 2) + "\n";
      const sha256 = await coordinateSha256(json);
      if (run === sequence.current) { setGenerated({ batch, json, sha256 }); setSelectedIndex(0); }
    } catch (issue) { if (run === sequence.current) setError(issue instanceof Error ? issue.message : "The browser could not prepare coordinate proposals."); }
    finally { if (run === sequence.current) setBusy(false); }
  };
  const selected = generated?.batch.candidates[selectedIndex];
  const download = (kind: "json" | "sha256" | "cif") => {
    if (!generated || !selected) return;
    let url: string | undefined;
    try {
      const base = `sclib-site-candidates-${generated.sha256.slice(0, 12)}.json`;
      const content = kind === "json" ? generated.json : kind === "sha256" ? `${generated.sha256}  ${base}\n` : selected.cif;
      url = URL.createObjectURL(new Blob([content], { type: kind === "json" ? "application/json" : kind === "cif" ? "chemical/x-cif" : "text/plain" }));
      const a = document.createElement("a"); a.href = url;
      a.download = kind === "cif" ? `sclib-site-${selected.cif_sha256.slice(0, 12)}-unrelaxed.cif` : base + (kind === "sha256" ? ".sha256" : "");
      a.click(); setDownloadStatus(`${kind.toUpperCase()} download requested.`);
    } catch { setDownloadStatus("The browser could not start the download. Try again."); }
    finally { if (url) setTimeout(() => URL.revokeObjectURL(url!), 1000); }
  };

  return <div className="min-w-0 space-y-7">
    <section aria-labelledby="candidate-input-title" className="min-w-0 space-y-5">
      <h2 id="candidate-input-title" className="text-xl font-semibold">Choose a source and one atomic site</h2>
      <div className="grid min-w-0 items-end gap-5 md:grid-cols-2">
        <label className="min-w-0 text-sm font-medium">Source structure<select className={control} value={referenceId} onChange={event => { invalidate(); setReferenceId(event.target.value); setRepeats(initialSupercellRepeats(references.find(ref => ref.id === event.target.value)!)); setTargetId(""); }}><StructureReferenceOptions references={references} /></select></label>
        <fieldset className="min-w-0"><legend className="text-sm font-medium">Supercell repeats</legend><div className="grid grid-cols-3 gap-3">{["a", "b", "c"].map((axis, index) => <label key={axis} className="text-xs text-sage-muted">Along {axis}<input className={control} type="number" min="1" max="4" step="1" value={repeats[index]} onChange={event => { invalidate(); setTargetId(""); setRepeats(repeats.map((value, i) => i === index ? event.target.value : value)); }} /></label>)}</div></fieldset>
      </div>
      <p className="text-xs leading-5 text-sage-muted">{structureHostContext(references.find(ref => ref.id === referenceId)!).phase}. {occupancyDescription(references.find(ref => ref.id === referenceId)!)} <Link className="site-text-link" href={`/discovery/structures?reference=${referenceId}`}>Inspect source and conditions</Link></p>
      {modelError ? <p role="alert" className="border-l-2 border-accent pl-3 text-sm leading-6">{modelError}</p> : <>
        <p className="text-sm text-sage-muted">{model!.atoms.length} original atom sites · {compositionLabel(compositionOf(model!.atoms))} per supercell. Source sites use the captured 0.001 Å symmetry merge tolerance.</p>
        <label className="block text-sm font-medium">Atomic site to modify<select className={control} value={target?.id ?? ""} onChange={event => { invalidate(); setTargetId(event.target.value); }}>{model!.atoms.map(atom => <option key={atom.id} value={atom.id}>{atom.label}: {atom.element} · {atom.source_site_label} · cell [{atom.cell_translation.join(", ")}] · image {atom.source_expanded_index + 1}</option>)}</select></label>
      </>}
      <div className="grid min-w-0 gap-5 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <label className="min-w-0 text-sm font-medium">Replacement elements<input className={control} type="text" maxLength={128} placeholder="e.g. Al, Ca" value={replacements} onChange={event => { invalidate(); setReplacements(event.target.value); }} aria-describedby="replacement-help" /></label>
        <label className="min-w-0 text-sm font-medium">Vacancy candidate<select className={control} value={vacancy ? "yes" : "no"} onChange={event => { invalidate(); setVacancy(event.target.value === "yes"); }}><option value="no">Do not include</option><option value="yes">Include one vacancy</option></select></label>
      </div>
      <p id="replacement-help" className="text-xs leading-5 text-sage-muted">One candidate per distinct replacement element, optionally one vacancy, all at the selected site. Repeated symbols are deduplicated. Up to 8 candidates and 96 original sites; no energy ranking or equivalence between different sites is inferred.</p>
      <div className="flex flex-wrap items-center gap-4"><button type="button" className="btn-primary disabled:opacity-50" disabled={busy || !model || !estimatedCount} onClick={generate}>{busy ? "Preparing coordinates…" : "Generate coordinate proposals"}</button><p className="text-sm text-sage-muted" aria-live="polite">{model ? estimatedCount ? `${estimatedCount} candidate${estimatedCount === 1 ? "" : "s"} will be generated.` : operationError : "Ordered candidate generation is unavailable for this source or size."}</p></div>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    </section>

    {generated && selected && <section className="min-w-0 space-y-5 border-t border-sage-border pt-6" aria-labelledby="candidate-results-title">
      <h2 id="candidate-results-title" className="text-xl font-semibold">{generated.batch.candidates.length} unrelaxed coordinate proposals</h2>
      <p className="max-w-3xl text-sm leading-6 text-sage-muted">Each proposal changes one site in the same periodic supercell. These are nominal ordered models; charge, magnetic state and target temperature/pressure remain unspecified.</p>
      <div role="region" aria-label="Scrollable candidate comparison" tabIndex={0} className="overflow-x-auto"><table className="w-full text-left text-sm"><caption className="sr-only">Generated site candidate inventory</caption><thead><tr className="border-b border-sage-border text-xs text-sage-muted">{["Inspect", "Change", "Cell composition", "Atom sites"].map(label => <th key={label} scope="col" className="px-2 py-2 first:pl-0">{label}</th>)}</tr></thead><tbody>{generated.batch.candidates.map((candidate, index) => <tr key={candidate.id} className="border-b border-sage-border"><td className="py-2 pr-2"><button className="min-h-11 rounded-lg border border-sage-border px-3 py-2 text-sm aria-pressed:bg-sage-surface" aria-pressed={selectedIndex === index} aria-label={`Inspect ${candidate.operation.kind === "vacancy" ? "vacancy" : candidate.operation.element} candidate`} onClick={() => { setSelectedIndex(index); setDownloadStatus(""); }}>{index + 1}</button></td><th scope="row" className="px-2 py-2 font-medium">{candidate.target_atom.element} → {candidate.operation.element ?? "vacancy"}</th><td className="px-2 py-2 whitespace-nowrap">{compositionLabel(candidate.composition)}</td><td className="px-2 py-2 tabular-nums">{candidate.atoms.length}</td></tr>)}</tbody></table></div>
      <div className="grid min-w-0 gap-6 md:grid-cols-2"><SiteFigure batch={generated.batch} candidate={selected} /><div className="min-w-0 space-y-4">
        <h3 className="text-lg font-semibold">{selected.target_atom.label}: {selected.target_atom.element} → {selected.operation.element ?? "vacancy"}</h3>
        <dl className="space-y-3 text-sm">
          <div><dt className="text-xs text-sage-muted">Before → after, atoms per cell</dt><dd>{compositionLabel(compositionOf(generated.batch.baseline.atoms))} → {compositionLabel(selected.composition)}</dd></div>
          <div><dt className="text-xs text-sage-muted">Nominal change, original {selected.target_atom.element} sites</dt><dd>1 / {selected.nominal_change.original_species_sites} = {percent(selected.nominal_change.species_site_fraction)}%</dd></div>
          <div><dt className="text-xs text-sage-muted">Nominal change, all original sites</dt><dd>1 / {selected.nominal_change.original_total_sites} = {percent(selected.nominal_change.original_total_site_fraction)}%</dd></div>
          <div><dt className="text-xs text-sage-muted">Selected source site</dt><dd>{selected.target_atom.source_site_label} · source image {selected.target_atom.source_expanded_index + 1} · unit-cell translation [{selected.target_atom.cell_translation.join(", ")}]</dd></div>
          <div><dt className="text-xs text-sage-muted">Selected fractional position in supercell</dt><dd className="break-words tabular-nums">{selected.target_atom.fractional.map(value => Number(value.toPrecision(8))).join(", ")}</dd></div>
        </dl>
        <p className="text-sm leading-6">Export uses P1 and explicit atom positions. The source space group is not assigned to the modified structure. Lattice vectors and all other sites remain fixed.</p>
        <button className="btn-outline" onClick={() => download("cif")}>Download selected CIF</button>
      </div></div>
      <div className="flex flex-wrap gap-3"><button className="btn-outline" onClick={() => download("json")}>Download batch JSON</button><button className="btn-outline" onClick={() => download("sha256")}>Download batch SHA-256</button></div>
      <p role="status" aria-live="polite" className="text-xs text-sage-muted">{downloadStatus}</p>
      <details className="min-w-0 text-xs leading-5 text-sage-muted"><summary className="w-fit cursor-pointer font-medium text-accent-deep">Lineage, coordinates and next calculations</summary><div className="mt-3 min-w-0 space-y-3">
        <p>Parent supercell: <code className="break-all">{generated.batch.parent_id}</code></p><p>Selected candidate: <code className="break-all">{selected.id}</code></p><p>Selected CIF SHA-256: <code className="break-all">{selected.cif_sha256}</code></p>
        <p>The JSON retains the original reference, both coordinate sets, site identity, transformation and content hashes. Source measurement conditions and uncertainties remain reference metadata, not proposed-state results. No catalogue write or training permission is created.</p>
        <p>Before evaluating superconductivity: select charge and magnetic states, pseudopotentials and a suitable electronic method; converge the cell and sampling, relax the intended structure, then test thermodynamic/dynamic stability and the relevant pairing/coherence quantities. Periodic defect interactions require supercell-size checks.</p>
        <div role="region" aria-label="Scrollable proposed coordinates" tabIndex={0} className="overflow-x-auto"><table className="w-full text-left tabular-nums"><caption className="sr-only">Selected proposal fractional coordinates</caption><thead><tr>{["Site", "Element", "x", "y", "z"].map(label => <th key={label} className="px-2 py-2" scope="col">{label}</th>)}</tr></thead><tbody>{selected.atoms.map(atom => <tr key={atom.id}><th className="px-2 py-1" scope="row">{atom.label}</th><td className="px-2 py-1">{atom.element}</td>{atom.fractional.map((value, index) => <td className="px-2 py-1" key={index}>{Number(value.toPrecision(8))}</td>)}</tr>)}</tbody></table></div>
      </div></details>
    </section>}
  </div>;
}
