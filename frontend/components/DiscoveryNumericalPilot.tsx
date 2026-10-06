"use client";

import { useId, useRef, useState } from "react";
import { FormulaDisplay } from "@/components/FormulaDisplay";
import type { DiscoveryNumericalPilotSummary, NumericalPilotCaseExport, NumericalPilotFailure, NumericalPilotState } from "@/lib/discovery-numerical-pilot";

const number = (n: number) => n.toLocaleString("en-US", { maximumSignificantDigits: 7, notation: n !== 0 && Math.abs(n) < 0.0001 ? "scientific" : "standard" });
const wall = (seconds: number | null) => seconds === null ? "Not captured" : `${seconds.toLocaleString("en-US", { maximumFractionDigits: 2 })} s`;
const signed = (n: number) => `${n > 0 ? "+" : ""}${number(n)}%`;
const hashes = /^[a-f0-9]{64}$/;
const assessment: Record<NumericalPilotState["assessment"], string> = {
  sampled_window_within_tolerance: "Within the sampled tolerance",
  sampled_window_outside_tolerance: "Exceeds the sampled tolerance",
  scf_precision_insufficient: "SCF precision insufficient",
  not_assessed: "Not assessed",
};
const failures: Record<NumericalPilotFailure, string> = {
  not_captured: "Files not captured", not_executed: "Execution not captured", native_xml_missing: "Native XML missing",
  native_read_rejected: "Native reading rejected", initialization_rejected: "Initialization rejected", execution_failed: "Execution failed",
  timed_out: "Execution timed out", scf_not_converged: "Electronic SCF not converged", incomplete: "Incomplete result",
};
const caseNames = { prepared: "Prepared", returned: "Returned", decided: "Decided", child: "Follow-up" } as const;
const fileNames = { input: "Input", preparation_manifest: "Preparation manifest", xml: "Native XML", stdout: "Native stdout",
  initialization_xml: "Initialization XML", initialization_stdout: "Initialization stdout", execution_receipt: "Execution receipt", reading: "Native reading" } as const;

function caseUrl(value: NumericalPilotCaseExport | null): string | null {
  // Only root-reviewed copies in the same-origin public research-pilots directory can become links.
  return value && hashes.test(value.sha256) && typeof value.download_url === "string"
    && /^\/research-pilots\/(?:[A-Za-z0-9][A-Za-z0-9_-]*\/)*[A-Za-z0-9][A-Za-z0-9._-]*\.json$/.test(value.download_url)
    ? value.download_url : null;
}
function sourceUrl(state: NumericalPilotState): string | null {
  const source = state.source;
  if (!/^\d+$/.test(source.record_id) || !/^\d+$/.test(source.revision)) return null;
  const exact = `https://www.crystallography.net/cod/${source.record_id}.cif@${source.revision}`;
  return source.cif_url === exact ? exact : null;
}
function Hash({ label, value }: { label: string; value: string | null }) {
  return <div className="min-w-0"><dt className="text-sage-muted">{label}</dt><dd className="break-all text-xs">{value === null ? "Not captured" : <code>{value}</code>}</dd></div>;
}

/** The parent supplies a reviewed projection of real captured files; this component computes no result. */
export function DiscoveryNumericalPilot({ summary }: { summary: DiscoveryNumericalPilotSummary }) {
  return <details id="discovery-numerical-pilot" className="min-w-0 scroll-mt-24 rounded-lg border border-sage-border bg-white p-4">
    <summary className="cursor-pointer font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4">Numerical pilot · <FormulaDisplay formula={summary.formula} /> · {summary.states.length} coordinate states</summary>
    <div className="mt-4 min-w-0 space-y-4">
      <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
        <p>Energy tolerance: <strong className="font-medium">{number(summary.protocol.tolerance_hartree_per_atom)} Hartree/atom</strong></p>
        <p>Actual total wall time: {wall(summary.elapsed_wall_seconds)}</p>
        <p>RPS: unassigned</p>
      </div>
      <p className="max-w-3xl text-sm text-sage-muted">Fixed, unrelaxed {summary.atom_count}-atom models from <FormulaDisplay formula={summary.host_formula} />. Each state is compared separately; lattice order is not a potential ranking.</p>
      <div tabIndex={0} role="region" aria-label="Numerical pilot states, scroll horizontally for all columns" className="relative max-w-full overflow-x-auto rounded-lg border border-sage-border focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
        <table className="w-full min-w-[680px] text-left text-sm">
          <caption className="sr-only">Finite k-mesh energy sensitivity for separate coordinate states. Expand a state for its original artifact hashes.</caption>
          <thead className="bg-sage-surface text-sage-muted"><tr>{["Coordinate state", "k-point meshes", "Finite-window assessment", "Actual wall time"].map(label => <th key={label} scope="col" className="p-3 font-medium">{label}</th>)}</tr></thead>
          <tbody>{summary.states.map(state => <StateRow key={`${summary.pilot_id}:${state.catalogue_state_id}`} state={state} formula={summary.formula} />)}</tbody>
        </table>
      </div>
      <details className="min-w-0 text-sm"><summary className="cursor-pointer py-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4">Method, limits and capture hashes</summary><div className="mt-3 min-w-0 space-y-3">
        <p>{summary.protocol.engine} · {summary.protocol.functional} · {summary.protocol.pseudopotential_type}. Cutoffs: {number(summary.protocol.cutoffs_ry.wavefunction)} / {number(summary.protocol.cutoffs_ry.density)} Ry. Smearing: {summary.protocol.smearing.kind}, {number(summary.protocol.smearing.width_ry)} Ry. Charge {number(summary.protocol.conditions.charge)}; spin-unpolarized model.</p>
        <p>Each comparison requires {summary.protocol.required_points} eligible SCF readings with identical remaining settings. The energy range per atom must be at most the stated tolerance, and the largest reported SCF error per atom must be strictly smaller. Missing or rejected results remain unassessed.</p>
        <p>A finite mesh window does not establish the dense-mesh, cutoff or zero-smearing limit. Strain does not assign pressure, and smearing does not assign temperature. Bandwidth, mobile-carrier density, stability, pairing and Tc were not determined by this check.</p>
        <p>Native QE etot includes the numerical smearing contribution. It is not a measured thermodynamic free energy, formation or hull energy, or a cross-state ranking.</p>
        <p>State wall time sums captured initialization and execution steps; total wall time also includes orchestration overhead. Capture status: {summary.execution_capture_status === "execution_files_captured" ? "Execution files captured" : "Partial or failed capture"}. File capture and a zero exit code alone do not establish electronic convergence.</p>
        <p>Research summaries retain exact-source custody. Formal scientific approval and a published RPS assessment are not assigned by this pilot.</p>
        <dl className="grid min-w-0 gap-3 sm:grid-cols-2">
          <Hash label="Frozen plan SHA-256" value={summary.protocol.plan_sha256} />
          <Hash label="Reader summary SHA-256" value={summary.reader_summary_sha256} />
          <Hash label="PW runtime SHA-256" value={summary.runtime_pw_sha256} />
          <Hash label="Execution-finished receipt SHA-256" value={summary.execution_finished_sha256} />
          {summary.pseudopotentials.map(p => <Hash key={p.element} label={`${p.element} UPF SHA-256`} value={p.sha256} />)}
        </dl>
        <p className="break-all text-xs text-sage-muted">Pilot {summary.pilot_id} · Catalogue {summary.catalogue_version}</p>
      </div></details>
    </div>
  </details>;
}

function StateRow({ state, formula }: { state: NumericalPilotState; formula: string }) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const detailsId = useId();
  const source = sourceUrl(state);
  return <>
    <tr className="border-t border-sage-border align-top">
      <th scope="row" className="p-3 font-normal"><button ref={button} type="button" aria-expanded={open} aria-controls={open ? detailsId : undefined} aria-label={`${formula}, lattice change ${signed(state.strain_percent)}`}
        className="min-h-11 text-left font-medium text-accent underline decoration-dotted underline-offset-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4" onClick={() => setOpen(value => !value)}><FormulaDisplay formula={formula} /><span className="block text-xs font-normal">Lattice change {signed(state.strain_percent)}</span></button></th>
      <td className="p-3 tabular-nums">{state.points.map(p => p.mesh.join(" × ")).join("; ")}<span className="block text-xs text-sage-muted">{state.points.filter(p => p.comparison_eligible).length} / {state.points.length} eligible readings</span></td>
      <td className="p-3">{assessment[state.assessment]}</td>
      <td className="whitespace-nowrap p-3 tabular-nums">{wall(state.elapsed_wall_seconds)}</td>
    </tr>
    {open && <tr id={detailsId} className="border-t border-sage-border bg-sage-surface"><td colSpan={4} className="p-4"><div className="max-w-[calc(100vw-4rem)] space-y-4 md:max-w-none">
      <div className="flex items-start justify-between gap-3"><h3 className="font-medium">{formula} · Lattice change {signed(state.strain_percent)}</h3><button type="button" className="min-h-11 rounded-lg border border-sage-border bg-white px-3" onClick={() => { setOpen(false); button.current?.focus(); }}>Close</button></div>
      <dl className="grid min-w-0 gap-3 sm:grid-cols-2">
        <div><dt className="text-sage-muted">Sampled energy range</dt><dd>{state.energy_spread_hartree_per_atom === null ? "Not assessed" : `${number(state.energy_spread_hartree_per_atom)} Hartree/atom`}</dd></div>
        <div><dt className="text-sage-muted">Largest reported SCF error</dt><dd>{state.maximum_scf_error_hartree_per_atom === null ? "Not assessed" : `${number(state.maximum_scf_error_hartree_per_atom)} Hartree/atom`}</dd></div>
      </dl>
      <p>Decision: {state.decision === null ? "Not recorded" : state.decision.outcome === "continue" ? "Continue with method refinement" : "Redirect to method refinement"}.</p>
      {state.comparison_download_url && caseUrl({ sha256: state.comparison_sha256 ?? "", download_url: state.comparison_download_url }) && <a className="site-text-link inline-flex min-h-11 items-center" href={state.comparison_download_url} download>Download original mesh comparison JSON</a>}
      <details className="min-w-0"><summary className="cursor-pointer py-1">Original coordinates and reading hashes</summary><div className="mt-3 min-w-0 space-y-4">
        <p>{source ? <a className="site-text-link" href={source}>COD {state.source.record_id}</a> : `COD ${state.source.record_id}`} · revision {state.source.revision}. Original occurrence CIFs are preserved; the regenerated QE model is linked by coordinate replay.</p>
        <dl className="grid min-w-0 gap-3 sm:grid-cols-2">
          <Hash label="Source CIF SHA-256" value={state.source.cif_sha256} />
          {state.original_cif_sha256.map((sha, i) => <Hash key={`${i}:${sha}`} label={`Original occurrence CIF ${i + 1} SHA-256`} value={sha} />)}
          <Hash label="Regenerated model CIF SHA-256" value={state.generated_cif_sha256} />
          <Hash label="Comparison JSON SHA-256" value={state.comparison_sha256} />
          <Hash label="Retained return SHA-256" value={state.decision?.return_sha256 ?? null} />
          <Hash label="Decision SHA-256" value={state.decision?.decision_sha256 ?? null} />
        </dl>
        {state.points.map(point => <details key={point.mesh.join("-")} className="min-w-0 border-t border-sage-border pt-2"><summary className="cursor-pointer py-1">Mesh {point.mesh.join(" × ")} · {point.failure_code ? failures[point.failure_code] : point.status === "scf_reported_converged" ? "Electronic SCF reported converged" : "Not eligible for comparison"}</summary><div className="mt-2 min-w-0 space-y-3">
          <p>Initialization: {point.initialization_status === "initialization_only" ? "Native initialization read" : "Not read"}. Execution exit: {point.exit_code === null ? "Not captured" : point.exit_code}; timeout: {point.timed_out === null ? "Not captured" : point.timed_out ? "Yes" : "No"}.</p>
          <p>Initialization wall: {wall(point.elapsed_wall_seconds.initialization)}; SCF execution wall: {wall(point.elapsed_wall_seconds.execution)}.</p>
          <p>Native energy: {point.energy_hartree_per_cell === null ? "Not read" : `${number(point.energy_hartree_per_cell)} Hartree/cell`}; SCF error: {point.scf_error_hartree_per_cell === null ? "Not read" : `${number(point.scf_error_hartree_per_cell)} Hartree/cell`}; iterations: {point.scf_iterations === null ? "Not read" : point.scf_iterations}.</p>
          <dl className="grid min-w-0 gap-3 sm:grid-cols-2">{(Object.keys(fileNames) as (keyof typeof fileNames)[]).map(key => <Hash key={key} label={`${fileNames[key]} SHA-256`} value={point.file_hashes[key]} />)}</dl>
        </div></details>)}
        <p className="break-all text-xs text-sage-muted">State {state.catalogue_state_id}<br />Group {state.catalogue_group_id}<br />Regenerated model {state.generated_candidate_id}</p>
      </div></details>
      <details className="min-w-0"><summary className="cursor-pointer py-1">Research-case exports</summary><dl className="mt-3 grid min-w-0 gap-3 sm:grid-cols-2">{(Object.keys(caseNames) as (keyof typeof caseNames)[]).map(key => {
        const pin = state.case_exports[key], url = caseUrl(pin);
        return <div key={key} className="min-w-0"><dt>{caseNames[key]} case</dt><dd className="mt-1 break-all text-xs">{pin ? <code>SHA-256 {pin.sha256}</code> : "Not created"}</dd>{url && <dd><a className="site-text-link inline-flex min-h-11 items-center" href={url} download>Download {caseNames[key].toLowerCase()} case</a></dd>}</div>;
      })}</dl></details>
    </div></td></tr>}
  </>;
}
