"use client";

import { useEffect, useRef, useState } from "react";
import { inspectQeResultContext, QE_RESULT_LIMITS, type QeResultContext, type QeResultReading } from "@/lib/discovery-qe-result";
import { UPF_BYTE_LIMIT } from "@/lib/discovery-qe-input";
import { canPrepareQeFollowUp } from "@/lib/discovery-qe-follow-up";
import { DiscoveryQeInput } from "@/components/DiscoveryQeInput";
import { DiscoveryQeConvergence } from "@/components/DiscoveryQeConvergence";

const fileFields = [
  ["manifest", "Preparation manifest", ".json", "Original SCLib QE manifest, up to 1 MiB."],
  ["input", "Executed input", ".in,.txt", "Exact calculation or initialization input, up to 1 MiB."],
  ["xml", "QE XML output", ".xml", "data-file-schema.xml from the run's .save directory, up to 8 MiB."],
  ["stdout", "QE stdout log", ".out,.log,.txt", "Complete pw.x console output from the same run, up to 8 MiB."],
] as const;
type Role = typeof fileFields[number][0];
const emptyFiles = (): Record<Role, File | null> => ({ manifest: null, input: null, xml: null, stdout: null });
const statusLabels: Record<QeResultReading["report"]["status"], string> = {
  initialization_only: "Initialization only",
  incomplete: "Run reports an incomplete exit",
  scf_not_converged: "Electronic convergence not reached",
  ionic_not_converged: "Ionic convergence not reached",
  relaxation_reported_converged: "QE reports ionic convergence",
  scf_reported_converged: "QE reports electronic convergence",
};
const readable = (value: number) => value.toLocaleString("en-US", {
  maximumSignificantDigits: 10,
  notation: value !== 0 && (Math.abs(value) < 0.0001 || Math.abs(value) >= 1e8) ? "scientific" : "standard",
});
const control = "mt-2 block min-h-11 w-full min-w-0 rounded-md border border-sage-border bg-white p-2 text-sm";

export function DiscoveryQeResult({ onContext }: { onContext?: (value: QeResultContext | null) => void } = {}) {
  const [files, setFiles] = useState(emptyFiles);
  const [pseudos, setPseudos] = useState<File[]>([]);
  const [context, setContext] = useState<QeResultContext | null>(null);
  const result = context?.reading ?? null;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [downloadStatus, setDownloadStatus] = useState("");
  const [reset, setReset] = useState(0);
  const sequence = useRef(0);
  useEffect(() => () => { sequence.current++; }, []);
  const invalidate = () => { sequence.current++; setContext(null); onContext?.(null); setError(""); setBusy(false); setDownloadStatus(""); };
  const choose = (role: Role, file: File | null) => {
    invalidate();
    if (file && (!file.size || file.size > QE_RESULT_LIMITS[role])) {
      setFiles(previous => ({ ...previous, [role]: null }));
      setError(`${fileFields.find(item => item[0] === role)![1]} must be nonempty and within the stated size limit.`);
      return;
    }
    setFiles(previous => ({ ...previous, [role]: file }));
  };
  const read = async () => {
    invalidate(); const run = sequence.current; setBusy(true);
    try {
      const local = async (file: File) => ({ name: file.name, bytes: new Uint8Array(await file.arrayBuffer()) });
      const [manifest, input, xml, stdout, upfs] = await Promise.all([
        local(files.manifest!), local(files.input!), local(files.xml!), local(files.stdout!), Promise.all(pseudos.map(local)),
      ]);
      const reading = await inspectQeResultContext({ manifest, input, xml, stdout, pseudos: upfs });
      if (run === sequence.current) { setContext(reading); onContext?.(reading); }
    } catch (issue) { if (run === sequence.current) setError(issue instanceof Error ? issue.message : "The local output could not be read."); }
    finally { if (run === sequence.current) setBusy(false); }
  };
  const download = (checksum: boolean) => {
    if (!result) return;
    let url: string | undefined;
    try {
      url = URL.createObjectURL(new Blob([checksum ? `${result.sha256}  ${result.filename}\n` : result.json], { type: checksum ? "text/plain" : "application/json" }));
      const link = document.createElement("a"); link.href = url; link.download = result.filename + (checksum ? ".sha256" : ""); link.click();
      setDownloadStatus("Download requested. Keep the original files with this reading.");
    } catch { setDownloadStatus("The browser could not start the download. Try again."); }
    finally { if (url) setTimeout(() => URL.revokeObjectURL(url!), 1000); }
  };
  const report = result?.report;
  return <div className="min-w-0 space-y-8">
    <section aria-labelledby="qe-files-title" className="min-w-0 rounded-lg border border-sage-border bg-white p-4 sm:p-6">
      <h2 id="qe-files-title" className="text-xl font-semibold">Select files from one run</h2>
      <p className="mt-2 max-w-3xl text-sm leading-6 text-sage-muted">Files are read in this browser only. This reader supports PWSCF 7.5 and QEXSD 25.05.21 outputs from SCLib-prepared inputs.</p>
      <div key={reset} className="mt-5 grid min-w-0 gap-5 md:grid-cols-2">
        {fileFields.map(([role, label, accept, help]) => <div key={role} className="min-w-0 text-sm font-medium"><label htmlFor={`qe-${role}`}>{label}</label>
          <input id={`qe-${role}`} type="file" accept={accept} className={control} aria-describedby={`qe-${role}-help`} onChange={event => choose(role, event.target.files?.[0] ?? null)} />
          <span id={`qe-${role}-help`} className="mt-2 block text-xs font-normal leading-5 text-sage-muted">{help}</span>
        </div>)}
        <div className="min-w-0 text-sm font-medium md:col-span-2"><label htmlFor="qe-upf">Original UPF files</label>
          <input id="qe-upf" type="file" accept=".upf,.UPF" multiple className={control} aria-describedby="qe-upf-help" onChange={event => {
            invalidate(); const chosen = Array.from(event.target.files ?? []);
            if (chosen.length > 8 || chosen.some(file => !file.size || file.size > UPF_BYTE_LIMIT)) { setPseudos([]); setError("Choose 1 to 8 nonempty UPF files, each up to 8 MiB."); }
            else setPseudos(chosen);
          }} />
          <span id="qe-upf-help" className="mt-2 block text-xs font-normal leading-5 text-sage-muted">Select the same pseudopotentials used to prepare the input, up to 8 files of 8 MiB each.</span>
        </div>
      </div>
      <div className="mt-5 flex flex-wrap gap-3"><button className="btn-primary disabled:opacity-50" disabled={busy || !Object.values(files).every(Boolean) || !pseudos.length} onClick={() => void read()}>{busy ? "Reading files…" : "Read QE output"}</button><button className="btn-outline" onClick={() => { invalidate(); setFiles(emptyFiles()); setPseudos([]); setReset(value => value + 1); }}>Clear files</button></div>
      {busy && <p role="status" className="mt-3 text-sm">Reconstructing the candidate and checking local file consistency…</p>}
      {error && <p role="alert" className="mt-3 break-words text-sm text-red-700">{error}</p>}
    </section>
    {report && result && <section aria-labelledby="qe-reading-title" className="min-w-0 space-y-5 border-t border-sage-border pt-6">
      <header className="space-y-2"><h2 id="qe-reading-title" className="text-xl font-semibold">{statusLabels[report.status]}</h2><p className="text-sm text-sage-muted">{Object.entries(report.composition).map(([element, count]) => `${element}${count === 1 ? "" : count}`).join("")} · {report.settings.calculation === "scf" ? "Single-point SCF" : "Fixed-cell ionic relaxation"} · PWSCF {report.engine.version}</p></header>
      <p className="text-sm">Parent coordinate reference: <a className="site-text-link" href={report.source_reference.source.entry_url}>{report.source_reference.formula} · {report.source_reference.id.toUpperCase()}</a>.</p>
      {report.status === "initialization_only" ? <p className="max-w-3xl text-sm leading-6">The input was initialized with nstep=0. No self-consistent energy or relaxed structure is reported.</p> : <>
        <p className="max-w-3xl text-sm leading-6">The final electronic cycle reports {report.convergence.scf_steps.toLocaleString("en-US")} iterations, with an estimated error of {readable(report.convergence.scf_error_hartree!)} Hartree against {readable(report.convergence.electronic_threshold_hartree)} Hartree.</p>
        {report.convergence.ionic_steps !== null && <p className="text-sm">Optimization steps: {report.convergence.ionic_steps.toLocaleString("en-US")}.{report.convergence.ionic_steps === 0 && " The engine made no ionic geometry step."}</p>}
        {!["scf_reported_converged", "relaxation_reported_converged"].includes(report.status) && <p className="text-sm font-medium text-amber-800">These final-file values are provisional; the requested calculation has not reported full convergence.</p>}
        <dl className="grid min-w-0 gap-x-8 gap-y-5 sm:grid-cols-2">
          {[
            ["Total energy", report.observations.total_energy ? `${readable(report.observations.total_energy.value)} Hartree/cell` : "Not reported"],
            ["Fermi energy", report.observations.fermi_energy ? `${readable(report.observations.fermi_energy.value)} Hartree` : "Not reported"],
            ["Valence electrons", report.observations.valence_electrons ? `${readable(report.observations.valence_electrons.value)} per cell` : "Not reported"],
            ["Maximum atomic force", report.observations.forces ? `${readable(report.observations.forces.maximum_atom_norm!)} Hartree/bohr` : "Not reported"],
          ].map(([label, value]) => <div key={label} className="min-w-0 border-l-2 border-sage-border pl-3"><dt className="text-sm text-sage-muted">{label}</dt><dd className="mt-1 break-words text-lg font-medium tabular-nums">{value}</dd></div>)}
        </dl>
        <p className="max-w-3xl text-sm leading-6 text-sage-muted">Total energy includes the selected numerical smearing contribution. Formation energy, phase stability and Tc require further calculations. Cutoff, k-point and smearing convergence have not been established.</p>
      </>}
      <details className="min-w-0 text-sm"><summary className="w-fit cursor-pointer font-medium text-accent-deep">File consistency and interpretation</summary><div className="mt-3 max-w-3xl space-y-3 leading-6">
        <p>The preparation manifest was reconstructed from the source coordinates, declared settings and selected UPF bytes. The input hash, geometry, species and supported method fields were checked against the XML. For an electronically converged result, stdout energy and iteration count were also checked.</p>
        <p>Matching local files does not authenticate execution or prove which UPF bytes the engine actually used. XML exit status: {report.engine.reported_exit_status}. Initialization may report 255 even when the console ends with JOB DONE.</p>
        <p>No target temperature or pressure is assigned. This reading does not certify a stable host, scientific acceptance or ML readiness, and does not write to the Materials catalogue.</p>
        <p className="break-all">Candidate ID: <code>{report.candidate_id}</code></p><p className="break-all">Reading SHA-256: <code>{result.sha256}</code></p>
      </div></details>
      <div className="flex flex-wrap gap-3"><button className="btn-outline" onClick={() => download(false)}>Download reading</button><button className="btn-outline" onClick={() => download(true)}>Download checksum</button></div>
      {downloadStatus && <p role="status" className="text-sm text-sage-muted">{downloadStatus}</p>}
      <details className="min-w-0 text-sm"><summary className="w-fit cursor-pointer font-medium text-accent-deep">Full values and source record</summary><pre tabIndex={0} aria-label="Scrollable QE output reading" className="mt-3 max-h-96 overflow-auto rounded border border-sage-border bg-white p-3 text-xs">{result.json}</pre></details>
    </section>}
    <DiscoveryQeConvergence current={result} />
    {context && canPrepareQeFollowUp(context) && <DiscoveryQeInput key={context.reading.sha256} batch={context.preparation.batch} candidateId={context.reading.report.candidate_id} followUp={context} />}
    {context && !canPrepareQeFollowUp(context) && <p className="text-sm text-sage-muted">Follow-up input preparation is available after a fixed-geometry SCF run. A relaxation needs an explicit final-coordinate model before preparing another run.</p>}
  </div>;
}
