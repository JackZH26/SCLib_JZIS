"use client";

import { useEffect, useRef, useState } from "react";
import { compareQeReadings, QE_STUDY_AXES, QE_STUDY_LIMIT, type QeStudyAxis, type QeConvergenceReading } from "@/lib/discovery-qe-convergence";
import type { QeResultReading } from "@/lib/discovery-qe-result";
import { compareQeMeshSmearing, type QeJointReading } from "@/lib/discovery-qe-joint-refinement";
import { DiscoveryQeJointResult } from "@/components/DiscoveryQeJointResult";

const number = (value: number) => value.toLocaleString("en-US", { maximumSignificantDigits: 7, notation: value !== 0 && Math.abs(value) < 0.0001 ? "scientific" : "standard" });
const labels = {
  sampled_window_within_tolerance: "Sampled energy window is within your tolerance",
  sampled_window_outside_tolerance: "Sampled energy window exceeds your tolerance",
  scf_precision_insufficient: "Tighten the electronic convergence threshold first",
};
export function DiscoveryQeConvergence({ current }: { current: QeResultReading | null }) {
  const [readings, setReadings] = useState<QeResultReading[]>([]);
  const [axis, setAxis] = useState<QeStudyAxis>("mesh");
  const [tolerance, setTolerance] = useState("");
  const [result, setResult] = useState<QeConvergenceReading | null>(null);
  const [mode, setMode] = useState("single");
  const [jointResult, setJointResult] = useState<QeJointReading | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const sequence = useRef(0);
  useEffect(() => () => { sequence.current++; }, []);
  const invalidate = () => { sequence.current++; setResult(null); setJointResult(null); setError(""); setBusy(false); setNotice(""); };
  const eligible = current?.report.status === "scf_reported_converged" && current.report.settings.nspin === 1;
  const duplicate = current && readings.some(reading => reading.sha256 === current.sha256);
  const compare = async () => {
    invalidate(); const run = sequence.current; setBusy(true);
    try {
      const value = /^\s*(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\s*$/.test(tolerance) ? Number(tolerance) : NaN;
      if (mode === "joint") {
        const comparison = await compareQeMeshSmearing(readings, value);
        if (run === sequence.current) setJointResult(comparison);
      } else {
        const comparison = await compareQeReadings(readings, axis, value);
        if (run === sequence.current) setResult(comparison);
      }
    } catch (issue) { if (run === sequence.current) setError(issue instanceof Error ? issue.message : "The readings could not be compared."); }
    finally { if (run === sequence.current) setBusy(false); }
  };
  const download = (checksum: boolean) => {
    const exported = mode === "joint" ? jointResult : result;
    if (!exported) return;
    let url: string | undefined;
    try {
      url = URL.createObjectURL(new Blob([checksum ? `${exported.sha256}  ${exported.filename}\n` : exported.json], { type: checksum ? "text/plain" : "application/json" }));
      const link = document.createElement("a"); link.href = url; link.download = exported.filename + (checksum ? ".sha256" : ""); link.click();
      setNotice("Download requested. The study includes every reading and its source-file hashes.");
    } catch { setNotice("The download could not start. Try again."); }
    finally { if (url) setTimeout(() => URL.revokeObjectURL(url!), 1000); }
  };
  return <section aria-labelledby="qe-convergence-title" className="min-w-0 space-y-5 border-t border-sage-border pt-6">
    <header className="space-y-2"><h2 id="qe-convergence-title" className="text-xl font-semibold">Compare numerical refinement</h2>
      <p className="max-w-3xl text-sm leading-6 text-sage-muted">Read each run above, then add it to this local study. Compare 3 to 16 spin-unpolarized SCF runs of the same fixed candidate. Choose one numerical parameter or examine mesh and smearing together. Added readings stay here when you change files; leaving this page clears the study.</p></header>
    <div className="flex flex-wrap items-center gap-3"><button className="btn-outline disabled:opacity-50" disabled={!eligible || !!duplicate || readings.length >= QE_STUDY_LIMIT} onClick={() => { if (current) { invalidate(); setReadings(previous => [...previous, structuredClone(current)]); } }}>{duplicate ? "Current reading added" : "Add current reading"}</button>
      <button className="btn-outline" disabled={!readings.length} onClick={() => { invalidate(); setReadings([]); }}>Clear study</button>
      <span className="text-sm text-sage-muted">{readings.length.toLocaleString("en-US")} / {QE_STUDY_LIMIT} readings</span></div>
    {current && !eligible && <p className="text-sm text-sage-muted">This study accepts electronically converged, spin-unpolarized SCF readings. Relaxation changes geometry, and magnetic runs require a separate check of the magnetic state.</p>}
    {!!readings.length && <div tabIndex={0} role="region" aria-label="Scrollable numerical refinement readings" className="relative max-w-full overflow-x-auto rounded border border-sage-border bg-white">
      <table className="w-full min-w-[680px] text-left text-sm tabular-nums"><caption className="sr-only">Local readings selected for numerical refinement comparison</caption><thead className="bg-sage-surface"><tr>{["Run", "k mesh", "Cutoffs (Ry)", "Smearing (Ry)", "Energy (Ha/cell)", ""].map((label, i) => <th key={i} scope="col" className="px-3 py-3 font-medium">{label || <span className="sr-only">Actions</span>}</th>)}</tr></thead>
        <tbody>{readings.map((reading, i) => <tr key={reading.sha256} className="border-t border-sage-border"><th scope="row" className="px-3 py-3 font-medium">{i + 1}</th><td className="px-3 py-3">{reading.report.settings.mesh.join(" × ")}</td><td className="px-3 py-3">{number(reading.report.settings.ecutwfc)} / {number(reading.report.settings.ecutrho)}</td><td className="px-3 py-3">{reading.report.settings.smearing} {number(reading.report.settings.degauss)}</td><td className="px-3 py-3">{number(reading.report.observations.total_energy!.value)}</td><td className="px-3 py-3"><button aria-label={`Remove reading ${i + 1}`} className="site-text-link" onClick={() => { invalidate(); setReadings(previous => previous.filter(item => item.sha256 !== reading.sha256)); }}>Remove</button></td></tr>)}</tbody></table>
    </div>}
    <div className="grid min-w-0 gap-4 sm:grid-cols-2">
      <label className="min-w-0 text-sm font-medium">Study mode<select value={mode} onChange={event => { invalidate(); setMode(event.target.value); }} className="mt-2 block min-h-11 w-full rounded border border-sage-border bg-white p-2 font-normal"><option value="single">Single parameter</option><option value="joint">Mesh and smearing</option></select></label>
      {mode === "single" && <label className="min-w-0 text-sm font-medium">Parameter varied<select value={axis} onChange={event => { invalidate(); setAxis(event.target.value as QeStudyAxis); }} className="mt-2 block min-h-11 w-full rounded border border-sage-border bg-white p-2 font-normal">{Object.entries(QE_STUDY_AXES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>}
      <label className="min-w-0 text-sm font-medium">Energy tolerance (Hartree/atom)<input value={tolerance} inputMode="decimal" placeholder="Enter your required tolerance" onChange={event => { invalidate(); setTolerance(event.target.value); }} className="mt-2 block min-h-11 w-full min-w-0 rounded border border-sage-border bg-white p-2 font-normal" /></label>
    </div>
    <p className="max-w-3xl text-sm leading-6 text-sage-muted">{mode === "joint" ? "Only mesh and smearing width may change; shifts, smearing method and other prepared settings stay fixed. Missing combinations remain visible. A joint window needs at least three meshes and three widths in a complete grid." : "Cutoffs are varied separately with the other cutoff fixed. Meshes must increase in every direction or retain that direction; shifts stay fixed. Smearing widths are ordered from larger to smaller. The comparison checks the energy range across the last three supplied points."}</p>
    <button className="btn-primary disabled:opacity-50" disabled={readings.length < 3 || busy} onClick={() => void compare()}>{busy ? "Comparing…" : "Compare readings"}</button>
    {error && <p role="alert" className="break-words text-sm text-red-700">{error}</p>}
    {result && <div className="min-w-0 space-y-4">
      <h3 className="text-lg font-semibold">{labels[result.report.sampled_window.assessment]}</h3>
      <dl className="grid min-w-0 gap-4 sm:grid-cols-2">{[
        ["Last-three-point energy range", `${number(result.report.sampled_window.energy_spread_hartree_per_atom)} Hartree/atom`],
        ["Largest reported SCF error in that window", `${number(result.report.sampled_window.maximum_reported_scf_error_hartree_per_atom)} Hartree/atom`],
      ].map(([label, value]) => <div key={label} className="min-w-0"><dt className="text-sm text-sage-muted">{label}</dt><dd className="mt-1 break-words font-medium tabular-nums">{value}</dd></div>)}</dl>
      <div tabIndex={0} role="region" aria-label="Scrollable energy differences" className="relative max-w-full overflow-x-auto rounded border border-sage-border bg-white"><table className="w-full min-w-[480px] text-left text-sm tabular-nums"><caption className="p-3 text-left text-xs text-sage-muted">Energy difference relative to the last refinement point; divided by {result.report.atom_count} atoms in the same computational cell.</caption><thead><tr><th scope="col" className="px-3 py-2">{QE_STUDY_AXES[axis]}</th><th scope="col" className="px-3 py-2">ΔE (Hartree/atom)</th><th scope="col" className="px-3 py-2">SCF error (Hartree/atom)</th></tr></thead><tbody>{result.report.points.map(point => <tr key={point.reading_sha256} className="border-t border-sage-border"><th scope="row" className="px-3 py-2 font-normal">{Array.isArray(point.parameter) ? point.parameter.join(" × ") : number(point.parameter)}</th><td className="px-3 py-2">{number(point.difference_from_last_hartree_per_atom)}</td><td className="px-3 py-2">{number(point.scf_error_hartree_per_atom)}</td></tr>)}</tbody></table></div>
      <p className="max-w-3xl text-sm leading-6">This describes a finite sample at your chosen tolerance. It does not establish the numerical limit, force or stress convergence, phase stability or Tc. Mesh and smearing need joint examination; numerical broadening is not a physical temperature.</p>
    </div>}
    {jointResult && <DiscoveryQeJointResult result={jointResult} />}
    {(result || jointResult) && <div className="flex flex-wrap gap-3"><button className="btn-outline" onClick={() => download(false)}>{jointResult ? "Download mesh–smearing study" : "Download convergence study"}</button><button className="btn-outline" onClick={() => download(true)}>Download study checksum</button></div>}
    {notice && <p role="status" className="text-sm text-sage-muted">{notice}</p>}
  </section>;
}
