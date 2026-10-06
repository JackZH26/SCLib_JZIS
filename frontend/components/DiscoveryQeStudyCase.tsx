"use client";

import { useEffect, useRef, useState } from "react";
import { attachResearchReturn, deriveResearchCase, prepareQeStudyReturn, prepareResearchCase, recordResearchDecision,
  unknownResearchEvidence, verifyResearchCase, type ResearchAction, type ResearchCase, type ResearchReturnInput } from "@/lib/discovery-research-cycle";
import type { QeResultReading } from "@/lib/discovery-qe-result";

type StudyKind = "mesh" | "mesh_smearing";
type Assessment = Exclude<ResearchReturnInput["numerical_assessment"], "not_assessed">;
type Session = { record: ResearchCase; readings: QeResultReading[]; assessment: Assessment | null };
const control = "mt-1 block min-h-11 w-full min-w-0 rounded-lg border border-sage-border bg-white px-3 py-2 text-sm";
const branches: ResearchAction["branches"] = [
  { id: "within_window", observable: "The supplied finite numerical window is within the selected tolerance.", decision: "continue", next_direction: "refine_method" },
  { id: "unresolved_window", observable: "The window exceeds tolerance, reported SCF precision is insufficient, or the parameter grid is incomplete.", decision: "redirect", next_direction: "refine_method" },
  { id: "insufficient_samples", observable: "The complete supplied grid has too few distinct samples on an axis to assess the joint window.", decision: "stop", next_direction: "pause" },
];
const labels: Record<Assessment, string> = {
  sampled_window_within_tolerance: "Sampled energy window is within tolerance",
  sampled_window_outside_tolerance: "Sampled energy window exceeds tolerance",
  scf_precision_insufficient: "Reported SCF precision is insufficient",
  incomplete_grid: "The supplied mesh–smearing grid is incomplete",
  insufficient_axis_samples: "Too few distinct samples to assess the joint window",
};
const branchFor = (assessment: Assessment) => branches[assessment === "sampled_window_within_tolerance" ? 0 : assessment === "insufficient_axis_samples" ? 2 : 1];
const digest = async (value: string) => Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)))).map(n => n.toString(16).padStart(2, "0")).join("");

/** Pin existing native-file readings before comparison; never submit a run or infer a physical property. */
export function DiscoveryQeStudyCase({ record, readings, onCase }: {
  record: ResearchCase; readings: QeResultReading[]; onCase: (record: ResearchCase) => void;
}) {
  const [kind, setKind] = useState<StudyKind>("mesh");
  const [tolerance, setTolerance] = useState("1e-4");
  const [session, setSession] = useState<Session | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const sequence = useRef(0), running = useRef(false);
  const latest = useRef({ record, readings, onCase });
  latest.current = { record, readings, onCase };
  const previous = useRef({ record, readings });
  const emitted = useRef<ResearchCase | null>(null);
  const invalidate = () => {
    sequence.current++; running.current = false;
    setSession(null); setBusy(false); setError(""); setStatus("");
  };
  useEffect(() => {
    if (previous.current.readings !== readings || previous.current.record !== record && emitted.current !== record) invalidate();
    previous.current = { record, readings };
    if (emitted.current === record) emitted.current = null;
  }, [record, readings]);
  useEffect(() => () => { sequence.current++; running.current = false; }, []);

  async function perform(work: (current: () => boolean) => Promise<void>) {
    if (running.current) return;
    const generation = ++sequence.current, source = latest.current;
    const current = () => generation === sequence.current && latest.current.record === source.record && latest.current.readings === source.readings;
    running.current = true; setBusy(true); setError(""); setStatus("");
    try { await work(current); }
    catch (issue) { if (current()) setError(issue instanceof Error ? issue.message : "The numerical study could not be prepared."); }
    finally { if (generation === sequence.current) { running.current = false; setBusy(false); } }
  }
  function publish(next: Session, message: string) {
    setSession(next); setStatus(message); emitted.current = next.record;
    latest.current.onCase(next.record);
  }
  const prepare = () => perform(async current => {
    const originals = structuredClone(readings), chosenKind = kind;
    const value = /^\s*(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\s*$/.test(tolerance) ? Number(tolerance) : NaN;
    if (!Number.isFinite(value) || value <= 0) throw new Error("Enter a positive energy tolerance in Hartree per atom.");
    if (originals.length < 3 || originals.length > 16) throw new Error("Choose 3 to 16 original native-file readings for this study.");
    const parent = await verifyResearchCase(record), state = parent.definition.state;
    if (parent.returns.length && !parent.decision) throw new Error("Record a decision for the current return before preparing another study case.");
    if (!state.structure || originals.some(r => r.report.candidate_cif_sha256 !== state.structure!.sha256)) throw new Error("Every reading must match this case's exact coordinate-model SHA-256.");
    if (originals.some(r => state.conditions.charge_state !== r.report.settings.charge || state.conditions.magnetic_state !== (r.report.settings.nspin === 1 ? "nonmagnetic" : "spin_polarized"))) throw new Error("The case must explicitly match every reading's charge and magnetic model.");
    if (new Set(originals.map(r => r.sha256)).size !== originals.length) throw new Error("Choose distinct original readings; repeated bytes are not additional evidence.");
    for (const reading of originals) {
      if (reading.json !== JSON.stringify(reading.report, null, 2) + "\n" || await digest(reading.json) !== reading.sha256) throw new Error("A reading has changed. Read its original native files again.");
    }
    const definition = structuredClone(parent.definition);
    definition.title = `${state.formula}: retained ${chosenKind === "mesh" ? "mesh" : "mesh–smearing"} study`;
    definition.evidence = unknownResearchEvidence();
    definition.hypothesis = {
      statement: "The supplied numerical window may meet the chosen energy tolerance and justify planning further numerical checks.",
      competing_explanations: ["The sampled energies remain sensitive to the numerical settings.", "Electronic precision or missing parameter combinations prevent assessment.", "A finite apparent plateau does not persist beyond the supplied window."],
      critical_unknown: "Whether the exact retained readings support a finite-window assessment; physical stability, pairing and Tc remain unresolved.",
    };
    definition.action = {
      kind: "computational_review", question: "Reassess existing native QE readings with a fixed comparison and tolerance before choosing the next numerical action.",
      input_artifacts: originals.map(r => ({ artifact_id: r.filename, version: r.report.version, sha256: r.sha256 })),
      prerequisites: [{ description: "Original reading JSON bytes, coordinate model, charge and magnetic model match this case.", status: "met" },
        { description: "The existing comparator must check all fixed numerical settings and source identities.", status: "unknown" }],
      resources: { access: "unconfirmed", cpu_hours: null, gpu_hours: null, memory_gib: null, storage_gib: null, human_hours: null },
      branches: structuredClone(branches), numerical_protocol: { kind: chosenKind, tolerance_hartree_per_atom: value }, ml: null,
    };
    const next = parent.decision ? await deriveResearchCase(parent, definition) : await prepareResearchCase(definition);
    if (current()) publish({ record: next, readings: originals, assessment: null }, `${parent.decision ? "Linked follow-up" : "Separate study case"} prepared. Original reading hashes and numerical settings are fixed before this comparison.`);
  });
  const evaluate = () => perform(async current => {
    if (!session || session.assessment || session.record.decision) return;
    const protocol = session.record.definition.action.numerical_protocol!;
    const result = await prepareQeStudyReturn(session.record, session.readings, { kind: protocol.kind, tolerance: protocol.tolerance_hartree_per_atom },
      "Reassessment of existing native QE readings using this case's pinned numerical protocol. The action was prepared after these runs existed; it is not execution preregistration.");
    const next = await attachResearchReturn(session.record, result);
    if (current()) publish({ ...session, record: next, assessment: result.numerical_assessment as Assessment }, "Study return attached to this exact case. Review the outcome before recording its decision.");
  });
  const decide = () => perform(async current => {
    if (!session?.assessment || session.record.decision) return;
    const branch = branchFor(session.assessment), returned = session.record.returns.at(-1)!;
    const next = await recordResearchDecision(session.record, { return_sha256: returned.return_sha256, branch_id: branch.id,
      decision: branch.decision, next_direction: branch.next_direction,
      reason: `${labels[session.assessment]}. ${branch.decision === "stop" ? "Pause until sufficient distinct samples are available." : "Plan further numerical checks before physical interpretation."} This finite sample does not establish stability, pairing or Tc.` });
    if (current()) publish({ ...session, record: next }, "Decision recorded. Export the case to retain this return and decision; revised settings require a new follow-up case.");
  });
  const outcome = session?.assessment ? branchFor(session.assessment) : null;
  const awaitingDecision = record.returns.length > 0 && !record.decision;
  return <details className="min-w-0 rounded-lg border border-sage-border bg-white p-4">
    <summary className="cursor-pointer font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4">Review QE numerical study</summary>
    <div className="mt-4 min-w-0 space-y-4">
      <p className="text-sm leading-6 text-sage-muted">Prepare a comparison of existing readings, then evaluate its fixed inputs. This is a retrospective review, not preregistration before execution.</p>
      <div className="grid min-w-0 gap-4 sm:grid-cols-2">
        <label className="min-w-0 text-sm font-medium">Numerical study<select className={control} disabled={awaitingDecision} value={kind} onChange={event => { invalidate(); setKind(event.target.value as StudyKind); }}><option value="mesh">k-point mesh</option><option value="mesh_smearing">Mesh and smearing</option></select></label>
        <label className="min-w-0 text-sm font-medium">Energy tolerance (Hartree/atom)<input className={control} disabled={awaitingDecision} value={tolerance} inputMode="decimal" onChange={event => { invalidate(); setTolerance(event.target.value); }} /></label>
      </div>
      <p className="text-sm text-sage-muted">{readings.length.toLocaleString("en-US")} original readings supplied. The case must already specify the matching coordinates, charge and spin.</p>
      {awaitingDecision && <p className="text-sm text-sage-muted">Record the current return's decision before revising the study settings.</p>}
      <button type="button" className="btn-outline disabled:opacity-50" disabled={busy || !!session && !session.record.decision} onClick={() => void prepare()}>{record.decision ? "Prepare follow-up study action" : "Prepare study action"}</button>
      {session && <div className="min-w-0 space-y-3 border-t border-sage-border pt-4">
        <p className="break-words text-sm">Pinned: {session.readings.length.toLocaleString("en-US")} readings · {session.record.definition.action.numerical_protocol!.kind === "mesh" ? "k-point mesh" : "mesh and smearing"} · {session.record.definition.action.numerical_protocol!.tolerance_hartree_per_atom.toLocaleString("en-US", { maximumSignificantDigits: 8 })} Hartree/atom.</p>
        <details className="text-sm"><summary className="cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4">Original reading hashes and outcome rules</summary>
          <ul className="mt-2 space-y-2">{session.record.definition.action.input_artifacts.map(pin => <li key={pin.sha256} className="break-all"><span>{pin.artifact_id}</span><br /><code className="text-xs">SHA-256 {pin.sha256}</code></li>)}</ul>
          <ul className="mt-3 list-disc space-y-2 pl-5">{branches.map(branch => <li key={branch.id}>{branch.observable} {branch.decision === "continue" ? "Continue with method refinement." : branch.decision === "redirect" ? "Redirect to method refinement." : "Stop and pause."}</li>)}</ul>
        </details>
        {!session.assessment && <button type="button" className="btn-primary disabled:opacity-50" disabled={busy} onClick={() => void evaluate()}>Evaluate pinned readings</button>}
        {session.assessment && <div className="space-y-2">
          <p className="font-medium">{labels[session.assessment]}</p>
          <p className="text-sm">{outcome?.decision === "continue" ? "Continue with method refinement." : outcome?.decision === "redirect" ? "Redirect to method refinement." : "Stop and pause until sufficient samples are available."}</p>
          {!session.record.decision && <button type="button" className="btn-outline disabled:opacity-50" disabled={busy} onClick={() => void decide()}>Record study decision</button>}
        </div>}
      </div>}
      <p className="text-xs leading-5 text-sage-muted">Changing the comparison or tolerance creates a new case. A decided case becomes its parent; physical evidence is not inherited. Resource estimates and RPS remain unknown. This finite study does not establish stability, pairing or Tc.</p>
      {busy && <p role="status" className="text-sm text-sage-muted">Checking the local study…</p>}
      {status && <p role="status" className="text-sm text-sage-muted">{status}</p>}
      {error && <p role="alert" className="break-words text-sm text-red-700">{error}</p>}
    </div>
  </details>;
}
