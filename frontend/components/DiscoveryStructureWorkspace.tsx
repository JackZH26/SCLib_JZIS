"use client";

import { useState } from "react";
import Link from "next/link";
import { StructureReferenceOptions } from "@/components/StructureReferenceOptions";
import { fractionalToCartesian, latticeBasis, latticeProposal, latticeProposalCif, parseLatticeChange,
  occupancyDescription, projectAlongAxis, structureHostContext, structureAssetPath, structureCoordinatesFilename, structureReferences, unitCellVolume,
  type StructureReference, type Vector3 } from "@/lib/discovery-structures";

const controls = "w-full min-h-11 rounded-lg border border-sage-border bg-white px-3 py-2 text-sm";
const views = ["Isometric", "Along a", "Along b", "Along c"] as const;
type View = typeof views[number];
const corners: Vector3[] = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1], [1, 1, 1]];
const edges = [[0, 1], [0, 2], [0, 4], [1, 3], [1, 5], [2, 3], [2, 6], [3, 7], [4, 5], [4, 6], [5, 7], [6, 7]];
const formatted = (value: number) => value.toLocaleString("en-US", { maximumFractionDigits: 5 });

function CrystalFigure({ reference, factor, view }: { reference: StructureReference; factor: number; view: View }) {
  const basis = latticeBasis(reference);
  // Orthographic directions follow the crystallographic axes, including hexagonal b.
  const project = ([x, y, z]: Vector3): [number, number] => {
    if (view === "Along a") return projectAlongAxis(reference, [x, y, z], 0);
    if (view === "Along b") return projectAlongAxis(reference, [x, y, z], 1);
    if (view === "Along c") return projectAlongAxis(reference, [x, y, z], 2);
    return [(x - y) / Math.sqrt(2), (x + y) / Math.sqrt(6) - z * Math.sqrt(2 / 3)];
  };
  const raw = (point: number[], scale: number) => project(fractionalToCartesian(point, basis).map(x => x * scale) as Vector3);
  // Fixed limits across the allowed ±10% preview, so changing size is visible.
  const bounds = corners.map(point => raw(point, 1.1));
  const xs = bounds.map(point => point[0]), ys = bounds.map(point => point[1]);
  const xmin = Math.min(...xs), xmax = Math.max(...xs), ymin = Math.min(...ys), ymax = Math.max(...ys);
  const zoom = Math.min(310 / (xmax - xmin), 240 / (ymax - ymin));
  const display = (point: number[], scale: number): [number, number] => {
    const [x, y] = raw(point, scale);
    return [210 + (x - (xmin + xmax) / 2) * zoom, 160 + (y - (ymin + ymax) / 2) * zoom];
  };
  const outline = (scale: number, original: boolean) => edges.map(([from, to], i) => {
    const a = display(corners[from], scale), b = display(corners[to], scale);
    return <line key={`${original}-${i}`} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={original ? "#6b7c6b" : "#24503A"} strokeWidth={original ? 1 : 1.6} strokeDasharray={original ? "4 4" : undefined} />;
  });
  const elements = [...new Set(reference.sites.map(site => site.element))];
  const fills = ["#24503A", "#ffffff", "#99b39e"];
  return <figure className="min-w-0 rounded-lg border border-sage-border bg-white p-3">
    <svg className="h-auto w-full" viewBox="0 0 420 330" role="img" aria-label={`${reference.formula} unit cell, ${view.toLowerCase()}, ${reference.display_unit_cell_sites.length} symmetry-expanded sites`}>
      <title>{`${reference.formula} coordinate model`}</title>
      <desc>Dashed source cell and solid preview cell. Sites are points, not atomic radii. No bonds are inferred; projected sites can overlap.</desc>
      {outline(1, true)}{outline(factor, false)}
      {reference.display_unit_cell_sites.map((site, i) => {
        const [x, y] = display(site.fractional, factor);
        return <g key={i} data-source-site={site.source_site_label}><circle cx={x} cy={y} r={5.5} fill={fills[elements.indexOf(site.element)]} stroke="#24503A" strokeWidth={2}><title>{`${site.source_site_label} (${site.element}): ${site.fractional.map(formatted).join(", ")}; occupancy ${site.occupancy.raw ?? "1 (CIF default)"}`}</title></circle>{reference.display_unit_cell_sites.length <= 12 && <text x={x + 9} y={y - 9} fontSize={13} fill="#2d3b2d">{site.source_site_label}</text>}</g>;
      })}
      {[1, 2, 4].map((corner, index) => { const [x, y] = display(corners[corner], factor); return <text key={corner} x={x - 16} y={y + 20} fontSize={13} fill="#5a6b5a">{["a", "b", "c"][index]}</text>; })}
    </svg>
    <ul aria-label="Element legend" className="mb-2 flex flex-wrap gap-4 text-xs">{elements.map((element, index) => <li className="inline-flex items-center gap-2" key={element}><span aria-hidden="true" className="h-3 w-3 rounded-full border border-accent-deep" style={{ backgroundColor: fills[index] }} />{element}</li>)}</ul>
    <figcaption className="text-xs leading-5 text-sage-muted">Dashed: source cell. Solid: preview. Site markers have arbitrary size; projections can overlap. Symmetry expansion uses the source operations and a 0.001 Å periodic merge tolerance.</figcaption>
  </figure>;
}

export function DiscoveryStructureWorkspace({ initialReferenceId }: { initialReferenceId?: string }) {
  const [references] = useState(structureReferences);
  const [referenceId, setReferenceId] = useState(initialReferenceId ?? references[0].id);
  const [family, setFamily] = useState("All families");
  const [search, setSearch] = useState("");
  const [change, setChange] = useState("0");
  const [view, setView] = useState<View>("Isometric");
  const [downloadStatus, setDownloadStatus] = useState("");
  const reference = references.find(item => item.id === referenceId)!;
  const context = structureHostContext(reference);
  const visibleReferences = references.filter(item => (family === "All families" || structureHostContext(item).family === family)
    && `${item.formula} ${structureHostContext(item).phase} ${item.id}`.toLowerCase().includes(search.trim().toLowerCase()));
  const filteredOut = !visibleReferences.some(item => item.id === referenceId);
  const percentage = parseLatticeChange(change);
  const proposal = percentage === null ? null : latticeProposal(referenceId, percentage);
  const factor = proposal?.transformation.scale_factor ?? 1;
  const partial = reference.sites.some(site => site.occupancy.value !== 1);
  const download = (kind: "json" | "cif") => {
    if (!proposal || percentage === null) return;
    let url: string | undefined;
    try {
      const content = kind === "json" ? JSON.stringify(proposal, null, 2) + "\n" : latticeProposalCif(referenceId, percentage);
      url = URL.createObjectURL(new Blob([content], { type: kind === "json" ? "application/json" : "chemical/x-cif" }));
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `sclib-${referenceId}-scale-${formatted(percentage).replaceAll(",", "")}-unrelaxed.${kind}`;
      anchor.click();
      setDownloadStatus(`${kind.toUpperCase()} download requested for ${reference.formula}, ${percentage}% lattice change.`);
    } catch { setDownloadStatus("The browser could not start the download. Try again."); }
    finally { if (url) setTimeout(() => URL.revokeObjectURL(url!), 1000); }
  };
  const conditions = reference.structure_conditions;
  return <div className="min-w-0 space-y-7">
    <section aria-label="Find a structure reference" className="space-y-3">
      <div className="grid min-w-0 gap-5 sm:grid-cols-2">
        <label className="min-w-0 space-y-2 text-sm font-medium"><span>Host family</span><select className={controls} value={family} onChange={event => setFamily(event.target.value)}><option>All families</option>{[...new Set(references.map(item => structureHostContext(item).family))].map(name => <option key={name}>{name}</option>)}</select></label>
        <label className="min-w-0 space-y-2 text-sm font-medium"><span>Find formula, phase or COD ID</span><input className={controls} value={search} onChange={event => setSearch(event.target.value)} placeholder="e.g. Al2O3, monoclinic or 9007634" /></label>
      </div>
      <p className="text-xs text-sage-muted" aria-live="polite">{visibleReferences.length} matching references. {filteredOut ? `Current selection ${reference.formula} remains selected until you choose another reference.` : ""}</p>
    </section>
    <div className="grid min-w-0 gap-5 sm:grid-cols-2 lg:grid-cols-3">
      <label className="min-w-0 space-y-2 text-sm font-medium"><span>Structure reference</span><select className={controls} value={referenceId} onChange={event => { setReferenceId(event.target.value); setChange("0"); setDownloadStatus(""); }}>{filteredOut && <option value={reference.id}>{reference.formula} · current selection</option>}<StructureReferenceOptions references={visibleReferences} /></select></label>
      <label className="min-w-0 space-y-2 text-sm font-medium"><span>View direction</span><select className={controls} value={view} onChange={event => setView(event.target.value as View)}>{views.map(direction => <option key={direction}>{direction}</option>)}</select></label>
      <div className="min-w-0 text-sm"><p className="font-medium">Reference conditions</p><dl className="mt-2 space-y-1 text-xs text-sage-muted">{([["Cell temperature", conditions.celltemp], ["Diffraction temperature", conditions.diffrtemp], ["Cell pressure", conditions.cellpressure], ["Diffraction pressure", conditions.diffrpressure]] as const).map(([label, condition]) => <div key={label}><dt className="inline">{label}: </dt><dd className="inline">{condition.value === null ? "not supplied" : `${condition.raw} ${condition.unit}`}</dd></div>)}</dl></div>
    </div>

    <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div className="min-w-0 space-y-3"><h2 className="text-lg font-semibold">{reference.formula} · {context.phase}</h2><CrystalFigure reference={reference} factor={factor} view={view} /><p className="text-sm text-sage-muted">Declared space group: {reference.space_group} ({reference.space_group_number}). {reference.sites.length} listed sites; {reference.display_unit_cell_sites.length} positions in the displayed cell.</p><div className="flex flex-wrap gap-x-5 text-sm"><Link className="site-text-link inline-flex min-h-11 items-center" href={`/discovery/structures/candidates?reference=${reference.id}`}>Modify one site</Link><Link className="site-text-link inline-flex min-h-11 items-center" href={`/discovery/structures/combinations?reference=${reference.id}`}>Combine site and lattice changes</Link></div></div>
      <section className="min-w-0 space-y-4" aria-labelledby="lattice-preview-title">
        <h2 id="lattice-preview-title" className="text-lg font-semibold">Try a uniform lattice change</h2>
        <p className="text-sm leading-6 text-sage-muted">Change all three lengths by the same percentage. Fractional coordinates, angles and occupancies remain fixed.</p>
        <label className="block max-w-xs space-y-2 text-sm font-medium"><span>Linear lattice change (%)</span><input className={controls} type="text" inputMode="decimal" value={change} aria-invalid={percentage === null} aria-describedby="lattice-input-help" onChange={event => { setChange(event.target.value); setDownloadStatus(""); }} /></label>
        <p id="lattice-input-help" className={`text-xs leading-5 ${percentage === null ? "text-red-700" : "text-sage-muted"}`}>{percentage === null ? "Enter a number from −10 to +10. Export is unavailable until the value is valid; the figure shows the source cell." : "Preview range: −10% to +10%. This interface limit is not a physical stability range."}</p>
        <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Scrollable lattice comparison">
          <table className="w-full text-left text-sm tabular-nums"><caption className="sr-only">Source lattice and geometric preview</caption><thead><tr className="border-b border-sage-border text-xs text-sage-muted"><th scope="col" className="py-2 pr-3">Quantity</th><th scope="col" className="py-2 pr-3">Source</th><th scope="col" className="py-2">Preview ≈</th></tr></thead><tbody>
            {(["a", "b", "c"] as const).map(axis => <tr key={axis}><th scope="row" className="py-2 pr-3 font-medium">{axis} (Å)</th><td className="py-2 pr-3">{reference.lattice[axis].raw}</td><td className="py-2">{proposal ? formatted(reference.lattice[axis].value * factor) : "Unavailable"}</td></tr>)}
            <tr><th scope="row" className="py-2 pr-3 font-medium">V (Å³)</th><td className="py-2 pr-3">≈ {formatted(unitCellVolume(reference))}</td><td className="py-2">{proposal ? formatted(proposal.proposed_cell.geometric_volume_angstrom_cubed) : "Unavailable"}</td></tr>
          </tbody></table>
        </div>
        <p className="text-xs leading-5 text-sage-muted">α = {reference.lattice.alpha.raw}° · β = {reference.lattice.beta.raw}° · γ = {reference.lattice.gamma.raw}°. Volume is derived from the lattice. Source uncertainty tokens are preserved; proposal uncertainties are not estimated.</p>
        <p className="text-sm"><strong>Unrelaxed geometry.</strong> Pressure, stability and Tc have not been calculated. {proposal ? `Volume change: ${formatted(proposal.proposed_cell.volume_change_percent)}%.` : ""}</p>
        {partial && <p className="border-l-2 border-accent pl-3 text-sm leading-6">{reference.sites.filter(site => site.occupancy.value !== 1).map(site => `${site.element} occupancy is ${site.occupancy.raw}`).join("; ")}. This is an average refined site model. It does not specify a vacancy arrangement; choose a disorder model before atomistic calculation.</p>}
        <div className="flex flex-wrap gap-3"><button className="btn-outline disabled:opacity-50" disabled={!proposal} onClick={() => download("json")}>Export proposal JSON</button><button className="btn-outline disabled:opacity-50" disabled={!proposal} onClick={() => download("cif")}>Export unrelaxed CIF</button></div>
        <p role="status" aria-live="polite" className="text-xs text-sage-muted">{downloadStatus}</p>
      </section>
    </div>

    <section className="min-w-0 space-y-3" aria-labelledby="listed-sites-title">
      <h2 id="listed-sites-title" className="text-lg font-semibold">Sites listed in the source CIF</h2>
      <p className="text-sm text-sage-muted">Fractional coordinates and explicit occupancy tokens are shown as reported. Parentheses retain the source standard uncertainties. {occupancyDescription(reference)}</p>
      <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Scrollable source site table"><table className="w-full text-left text-sm tabular-nums"><caption className="sr-only">Original asymmetric-unit site tokens</caption><thead><tr className="border-b border-sage-border text-xs text-sage-muted">{["Site", "Element", "x", "y", "z", "Occupancy"].map(label => <th key={label} scope="col" className="px-2 py-2 first:pl-0">{label}</th>)}</tr></thead><tbody>{reference.sites.map(site => <tr key={site.label} className="border-b border-sage-border"><th scope="row" className="py-3 pr-2 font-medium">{site.label}</th><td className="px-2 py-3">{site.element}</td>{site.fractional.map((value, i) => <td key={i} className="px-2 py-3">{value.raw}</td>)}<td className="px-2 py-3">{site.occupancy.raw ?? "1 (CIF default)"}</td></tr>)}</tbody></table></div>
      <p className="text-xs leading-5 text-sage-muted">{reference.rounding_notes.join(" ")}</p>
    </section>

    <section className="min-w-0 space-y-3 border-t border-sage-border pt-5" aria-labelledby="coordinate-source-title">
      <h2 id="coordinate-source-title" className="text-lg font-semibold">Source and downloads</h2>
      <p className="max-w-3xl text-sm leading-6">{reference.source.bibliography.authors}. {reference.source.bibliography.title}. {reference.source.bibliography.journal} ({reference.source.year}).</p>
      <p className="max-w-3xl text-sm leading-6 text-sage-muted">{context.selection_reason}</p>
      <div className="flex flex-wrap gap-x-5 gap-y-3 text-sm"><a className="site-text-link min-h-11 content-center" href={structureAssetPath(`structure-cifs/${reference.original_cif_filename}`)} download>Download captured source CIF</a><a className="site-text-link min-h-11 content-center" href={reference.source.entry_url}>COD entry</a>{reference.source.doi && <a className="site-text-link min-h-11 content-center" href={`https://doi.org/${reference.source.doi}`}>Original publication</a>}{!("host_context" in reference) && <Link className="site-text-link min-h-11 content-center" href={`/materials/source-references#${reference.id}`}>Reference context</Link>}</div>
      <details className="min-w-0 text-xs leading-5 text-sage-muted"><summary className="w-fit cursor-pointer font-medium text-accent-deep">Provenance, symmetry operations and scope</summary><div className="mt-3 min-w-0 space-y-3">
        <p>Captured {reference.source.captured_at_utc}; header revision {reference.source.captured_revision}. {reference.source.download_is_mutable_current_file ? "The provider URL was mutable at capture; this local copy preserves the captured bytes." : "The provider revision URL succeeded at capture."} Original file: {reference.source.bytes.toLocaleString("en-US")} bytes.</p>
        <p>Original SHA-256: <code className="break-all">{reference.source.file_sha256}</code>.</p>
        <p>The display expands declared operations in source order and keeps the first image within each 0.001 Å periodic group for each listed site. It does not snap or average rounded coordinates. No independent symmetry determination, refinement or stability calculation has been performed.</p>
        <p>These independent COD references are not associated with a catalogue sample or superconducting result. MgB₂ and FeSe appeared in disputed or archive scope in the checked historical catalogue snapshot; displaying their separate crystallographic references does not release those records. Current publication status has not been checked.</p>
        <p>COD data: <a className="site-text-link" href={reference.source.license_url}>CC0</a>. Acknowledge the original authors. Source measurement conditions belong to the reference only; no conditions or scientific results are inherited by the proposed cell.</p>
        <div className="flex flex-wrap gap-4"><a className="site-text-link min-h-11 content-center" href={structureAssetPath(structureCoordinatesFilename)} download>Download coordinate inventory (JSON)</a><a className="site-text-link min-h-11 content-center" href={structureAssetPath(`${structureCoordinatesFilename}.sha256`)} download>Download inventory SHA-256</a></div>
        <p>Declared symmetry operations ({reference.declared_symmetry_operations.length}):</p><ol className="grid grid-cols-1 gap-x-5 gap-y-1 font-mono sm:grid-cols-2 lg:grid-cols-3">{reference.declared_symmetry_operations.map((operation, index) => <li key={index}>{index + 1}. {operation}</li>)}</ol>
      </div></details>
    </section>
  </div>;
}
