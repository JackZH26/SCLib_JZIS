"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { prepareQeFollowUp, type QeFollowUp } from "@/lib/discovery-qe-follow-up";
import type { QeResultContext } from "@/lib/discovery-qe-result";
import type { CombinedBatch } from "@/lib/discovery-combined-candidates";
import { inspectQeUpf, prepareQeInput, UPF_BYTE_LIMIT, type PreparedQe, type QeFile, type QePseudo, type QeSettings } from "@/lib/discovery-qe-input";

const control = "mt-2 min-h-11 w-full min-w-0 rounded-md border border-sage-border bg-white px-3 py-2 text-sm";
const initial = { ecutwfc: "", ecutrho: "", charge: "0", degauss: "0.02", conv_thr: "1e-8", electron_maxstep: "100", mixing_beta: "0.3", max_seconds: "600", ionic_steps: "50", etot_conv_thr: "1e-5", forc_conv_thr: "1e-4" };
type NumericKey = keyof typeof initial;
const numericFields: Array<[NumericKey, string]> = [["ecutwfc", "Wavefunction cutoff (Ry)"], ["ecutrho", "Charge-density cutoff (Ry)"], ["charge", "Cell charge (electrons removed)"], ["degauss", "Smearing width (Ry)"], ["conv_thr", "Electronic threshold (Ry)"], ["electron_maxstep", "Electronic iteration limit"], ["mixing_beta", "Mixing beta"], ["max_seconds", "CPU time limit (s)"]];

/** Remount on candidate identity change so settings and local files never silently follow another geometry. */
export function DiscoveryQeInput({ batch, candidateId, followUp }: { batch: CombinedBatch; candidateId: string; followUp?: QeResultContext }) {
  const candidate = batch.candidates.find(item => item.id === candidateId)!;
  const elements = Object.keys(candidate.composition).sort();
  const previous = followUp?.preparation.prepared.manifest.settings;
  const [values, setValues] = useState(() => previous ? Object.fromEntries(Object.keys(initial).map(key => [key, String(previous[key as NumericKey])])) as typeof initial : initial);
  const [calculation, setCalculation] = useState<QeSettings["calculation"]>(previous?.calculation ?? "scf");
  const [spin, setSpin] = useState<1 | 2>(previous?.nspin ?? 1);
  const [smearing, setSmearing] = useState<QeSettings["smearing"]>(previous?.smearing ?? "mv");
  const [mesh, setMesh] = useState(previous?.mesh.map(String) ?? ["", "", ""]);
  const [shifts, setShifts] = useState(previous?.shifts.map(String) ?? ["0", "0", "0"]);
  const [masses, setMasses] = useState<Record<string, string>>(() => Object.fromEntries(previous?.species.map(item => [item.element, String(item.mass_amu)]) ?? []));
  const [seeds, setSeeds] = useState<Record<string, string>>(() => Object.fromEntries(previous?.species.map(item => [item.element, item.starting_magnetization === null ? "" : String(item.starting_magnetization)]) ?? []));
  const [files, setFiles] = useState<QeFile[]>(() => structuredClone(followUp?.preparation.pseudos ?? []));
  const [pseudos, setPseudos] = useState<QePseudo[]>(() => structuredClone(followUp?.preparation.prepared.manifest.pseudopotentials ?? []));
  const [reading, setReading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<PreparedQe | null>(null);
  const [lineage, setLineage] = useState<QeFollowUp["lineage"] | null>(null);
  const [rationale, setRationale] = useState("");
  const [status, setStatus] = useState("");
  const sequence = useRef(0);
  useEffect(() => () => { sequence.current++; }, []);
  const invalidate = () => { sequence.current++; setResult(null); setLineage(null); setBusy(false); setReading(false); setError(""); setStatus(""); };
  const readFiles = async (chosen: File[]) => {
    invalidate(); setFiles([]); setPseudos([]);
    const run = sequence.current;
    if (!chosen.length) return;
    if (chosen.length > 8 || chosen.some(file => !file.size || file.size > UPF_BYTE_LIMIT)) { setError("Choose at most 8 UPF files, each between 1 byte and 8 MiB."); return; }
    setReading(true);
    try {
      const local = await Promise.all(chosen.map(async file => ({ name: file.name, bytes: new Uint8Array(await file.arrayBuffer()) })));
      const inspected = await Promise.all(local.map(inspectQeUpf));
      if (run === sequence.current) { setFiles(local); setPseudos(inspected); }
    } catch (issue) { if (run === sequence.current) setError(issue instanceof Error ? issue.message : "The local files could not be read."); }
    finally { if (run === sequence.current) setReading(false); }
  };
  const number = (raw: string | undefined) => raw?.trim() ? Number(raw) : NaN;
  const prepare = async () => {
    invalidate(); const run = sequence.current; setBusy(true);
    try {
      const settings: QeSettings = { ...Object.fromEntries(Object.entries(values).map(([key, value]) => [key, number(value)])) as Record<NumericKey, number>,
        calculation, nspin: spin, smearing, mesh: mesh.map(number), shifts: shifts.map(number),
        species: elements.map(element => ({ element, mass_amu: number(masses[element]), starting_magnetization: spin === 1 ? null : number(seeds[element]) })) };
      if (followUp) {
        const next = await prepareQeFollowUp(followUp, settings, rationale);
        if (run === sequence.current) { setResult(next.prepared); setLineage(next.lineage); }
      } else {
        const prepared = await prepareQeInput(batch, candidateId, settings, files);
        if (run === sequence.current) setResult(prepared);
      }
    } catch (issue) { if (run === sequence.current) setError(issue instanceof Error ? issue.message : "Check the calculation settings."); }
    finally { if (run === sequence.current) setBusy(false); }
  };
  const download = (kind: "execution" | "initialization" | "manifest" | "sha256" | "lineage" | "lineage_checksum") => {
    if (!result) return;
    let url: string | undefined;
    try {
      if ((kind === "lineage" || kind === "lineage_checksum") && !lineage) return;
      const text = kind === "lineage" ? lineage!.json : kind === "lineage_checksum" ? `${lineage!.sha256}  ${lineage!.filename}\n` : kind === "execution" ? result.executionInput : kind === "initialization" ? result.initializationInput : kind === "manifest" ? result.json : [
        `${result.sha256}  ${result.filename}`, `${result.manifest.files.execution.sha256}  ${result.manifest.files.execution.filename}`,
        `${result.manifest.files.initialization.sha256}  ${result.manifest.files.initialization.filename}`,
        ...result.manifest.pseudopotentials.map(item => `${item.sha256}  pseudo/${item.filename}`), ""].join("\n");
      url = URL.createObjectURL(new Blob([text], { type: (kind === "manifest" || kind === "lineage") ? "application/json" : "text/plain" }));
      const a = document.createElement("a"); a.href = url;
      a.download = kind === "lineage" || kind === "lineage_checksum" ? lineage!.filename + (kind === "lineage_checksum" ? ".sha256" : "") : kind === "execution" || kind === "initialization" ? result.manifest.files[kind].filename : result.filename + (kind === "sha256" ? ".sha256" : "");
      a.click(); setStatus("Download requested. Keep the exact selected UPF files alongside these inputs.");
    } catch { setStatus("The browser could not start the download. Try again."); }
    finally { if (url) setTimeout(() => URL.revokeObjectURL(url!), 1000); }
  };
  const field = (key: NumericKey, label: string) => <label key={key} className="min-w-0 text-sm">{label}<input className={control} inputMode="decimal" value={values[key]} onChange={event => { invalidate(); setValues({ ...values, [key]: event.target.value }); }} /></label>;
  return <details className="min-w-0 border-t border-sage-border pt-5">
    <summary className="w-fit cursor-pointer text-lg font-semibold text-accent-deep">{followUp ? "Prepare a follow-up calculation" : "Prepare Quantum ESPRESSO input"}</summary>
    <div className="mt-5 min-w-0 space-y-5">
      {followUp && <div className="max-w-3xl space-y-3 text-sm leading-6"><p>Settings and original UPF bytes are carried over from the reading above. This starts a new run from the same original candidate coordinates, without reusing wavefunctions or assigning previous results to the new run.</p><label className="block font-medium">Reason for this follow-up<textarea className={control} rows={3} maxLength={2000} value={rationale} onChange={event => { invalidate(); setRationale(event.target.value); }} placeholder="What should this calculation help you decide?" /></label></div>}
      <p className="max-w-3xl text-sm leading-6">Prepare a PBE calculation for the selected {candidate.atoms.length}-atom candidate. {followUp ? "Review the carried-over settings and change only what your next question requires." : "Review the settings below; numerical presets are starting choices for convergence studies."}</p>
      <div className="grid min-w-0 gap-4 md:grid-cols-2">
        <label className="min-w-0 text-sm">Calculation<select className={control} value={calculation} onChange={event => { invalidate(); setCalculation(event.target.value as QeSettings["calculation"]); }}><option value="scf">Single-point SCF</option><option value="relax">Ionic relaxation at fixed cell</option></select></label>
        <label className="min-w-0 text-sm">Spin model<select className={control} value={spin} onChange={event => { invalidate(); setSpin(Number(event.target.value) as 1 | 2); setSeeds({}); }}><option value="1">Spin-unpolarized (nspin=1)</option><option value="2">Collinear spin-polarized (nspin=2)</option></select></label>
      </div>
      <fieldset className="min-w-0 space-y-3"><legend className="mb-2 text-sm font-semibold">Local pseudopotentials and atomic masses</legend>
        <p className="text-xs leading-5 text-sage-muted">Required elements: {elements.join(", ")}. {followUp ? "Original UPFs are retained for this follow-up." : "Select one UPF 2 PBE file per element together."} Files stay in this browser; they are not uploaded. Scalar-relativistic and nonrelativistic files are supported.</p>
        {followUp ? <p className="text-sm">Reusing the exact original UPF files listed below.</p> : <label className="block min-w-0 text-sm">UPF files<input className={`${control} block`} type="file" accept=".upf,.UPF" multiple onChange={event => { void readFiles(Array.from(event.target.files ?? [])); event.target.value = ""; }} /></label>}
        {reading && <p className="text-sm" role="status">Reading local UPF files…</p>}
        {pseudos.map(item => <div key={item.filename} className="min-w-0 border-l-2 border-sage-border pl-3 text-xs leading-5"><p className="break-all"><strong>{item.element}</strong>: {item.filename}</p><p>Valence electrons: {item.valence_electrons.toLocaleString("en-US")}. Header cutoff suggestions: {item.header_cutoffs_ry.wavefunction?.toLocaleString("en-US", { maximumFractionDigits: 2 }) ?? "not supplied"} / {item.header_cutoffs_ry.charge_density?.toLocaleString("en-US", { maximumFractionDigits: 2 }) ?? "not supplied"} Ry.</p><details><summary className="w-fit cursor-pointer text-accent-deep">File SHA-256</summary><code className="break-all">{item.sha256}</code></details></div>)}
        <div className="grid min-w-0 gap-4 md:grid-cols-2">{elements.map(element => <div key={element} className="min-w-0 space-y-3"><label className="block min-w-0 text-sm">{element} atomic mass (u)<input className={control} inputMode="decimal" value={masses[element] ?? ""} onChange={event => { invalidate(); setMasses({ ...masses, [element]: event.target.value }); }} /></label>{spin === 2 && <label className="block min-w-0 text-sm">{element} starting spin fraction<input className={control} inputMode="decimal" placeholder="Between -1 and 1 (exclusive)" value={seeds[element] ?? ""} onChange={event => { invalidate(); setSeeds({ ...seeds, [element]: event.target.value }); }} /></label>}</div>)}</div>
        <p className="text-xs leading-5 text-sage-muted">Masses and magnetic seeds are explicit inputs. One atomic type per element is used; same-element antiferromagnetic sublattices and spin-orbit coupling need a different setup.</p>
      </fieldset>
      <fieldset className="min-w-0"><legend className="text-sm font-semibold">Reciprocal-space sampling</legend><div className="mt-3 grid min-w-0 gap-5 md:grid-cols-2">{[["K-point mesh", mesh, setMesh], ["K-point offset", shifts, setShifts]].map(([title, list, setter]) => <div key={title as string} className="grid min-w-0 grid-cols-3 gap-3">{["a", "b", "c"].map((axis, i) => <label key={axis} className="min-w-0 text-xs">{title as string} {axis}{title === "K-point mesh" ? <input className={control} type="number" min="1" max="64" step="1" value={(list as string[])[i]} onChange={event => { invalidate(); (setter as typeof setMesh)((list as string[]).map((v, j) => i === j ? event.target.value : v)); }} /> : <select className={control} value={(list as string[])[i]} onChange={event => { invalidate(); (setter as typeof setShifts)((list as string[]).map((v, j) => i === j ? event.target.value : v)); }}><option value="0">0</option><option value="1">1</option></select>}</label>)}</div>)}</div></fieldset>
      <div className="grid min-w-0 gap-4 md:grid-cols-2">{numericFields.map(([key, label]) => field(key, label))}<label className="min-w-0 text-sm">Smearing method<select className={control} value={smearing} onChange={event => { invalidate(); setSmearing(event.target.value as QeSettings["smearing"]); }}><option value="mv">Marzari-Vanderbilt (cold)</option><option value="gaussian">Gaussian</option><option value="fd">Fermi-Dirac</option></select></label></div>
      {calculation === "relax" && <div className="grid min-w-0 gap-4 md:grid-cols-3">{field("ionic_steps", "Ionic step limit")}{field("etot_conv_thr", "Ionic energy threshold (Ry)")}{field("forc_conv_thr", "Force threshold (Ry/bohr)")}</div>}
      <p className="max-w-3xl text-xs leading-5 text-sage-muted">Smearing is numerical broadening. Positive cell charge removes electrons and uses a compensating background. Lattice vectors remain fixed; no target temperature or pressure is assigned. Cutoffs, sampling and stopping thresholds still require convergence checks.</p>
      <button className="btn-outline disabled:opacity-50" disabled={reading || busy || files.length === 0 || (!!followUp && !rationale.trim())} onClick={() => void prepare()}>{busy ? "Preparing QE inputs…" : "Prepare QE inputs"}</button>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      {result && <div className="min-w-0 space-y-4 border-t border-sage-border pt-4"><h4 className="font-semibold">Inputs prepared</h4><p className="text-sm">{result.manifest.expected_valence_electrons.toLocaleString("en-US")} valence electrons after the declared cell charge. This new input has not been executed.</p>{result.manifest.warnings.length > 0 && <ul className="list-disc space-y-1 pl-5 text-sm text-amber-800">{result.manifest.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul>}<p className="text-sm leading-6">Place the selected UPF files in <code>pseudo/</code> next to the inputs. Run the separate initialization check first (<code>nstep=0</code>), then the calculation input with your installed <code>pw.x</code>.</p><div className="flex flex-wrap gap-3"><button className="btn-outline" onClick={() => download("execution")}>Download calculation input</button><button className="btn-outline" onClick={() => download("initialization")}>Download initialization input</button><button className="btn-outline" onClick={() => download("manifest")}>Download QE manifest</button><button className="btn-outline" onClick={() => download("sha256")}>Download QE checksums</button></div><details className="min-w-0 text-sm"><summary className="w-fit cursor-pointer text-accent-deep">Inspect calculation input</summary><pre tabIndex={0} aria-label="Scrollable Quantum ESPRESSO input" className="mt-3 max-h-96 overflow-auto rounded border border-sage-border bg-white p-3 text-xs">{result.executionInput}</pre></details></div>}
      {lineage && <section aria-label="Follow-up provenance" className="min-w-0 space-y-3 border-l-2 border-sage-border pl-3 text-sm"><h4 className="font-semibold">Changes from the previous preparation</h4>{lineage.record.settings_changes.length ? <dl className="space-y-2">{lineage.record.settings_changes.map(change => <div key={change.field} className="min-w-0"><dt className="font-medium">{change.field}</dt><dd className="break-words font-mono text-xs">{JSON.stringify(change.before)} → {JSON.stringify(change.after)}</dd></div>)}</dl> : <p>All settings are unchanged. This is an explicitly requested repeat of the original preparation.</p>}<p>Comparability depends on the changed settings. Check the completed run separately before comparing results.</p><div className="flex flex-wrap gap-3"><button className="btn-outline" onClick={() => download("lineage")}>Download follow-up record</button><button className="btn-outline" onClick={() => download("lineage_checksum")}>Download follow-up checksum</button></div></section>}
      <p className="text-sm">{followUp ? "After executing the new input, select its manifest, input and native output in the reader above. Readings already added to the comparison study stay available." : <><Link className="site-text-link" href="/discovery/calculations">Read completed QE output</Link> with the original manifest, input and UPF files.</>}</p>
      {status && <p role="status" className="text-xs text-sage-muted">{status}</p>}
    </div>
  </details>;
}
