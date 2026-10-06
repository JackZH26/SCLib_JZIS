"use client";

import { useEffect, useRef, useState } from "react";
import { DiscoveryQeInput } from "@/components/DiscoveryQeInput";
import { DiscoveryQeResult } from "@/components/DiscoveryQeResult";
import { DiscoveryQeStudyCase } from "@/components/DiscoveryQeStudyCase";
import type { ResearchCatalogue } from "@/lib/discovery-research-catalogue";
import { prepareResearchModel } from "@/lib/discovery-research-model";
import { verifyWorkspaceState } from "@/lib/discovery-research-workspace";
import { attachResearchReturn, createResearchCaseInput, deriveResearchCase, exportResearchCase, importResearchCase, prepareResearchCase,
  recordResearchDecision, researchDecisionBranches, researchCaseReadiness, researchStateFromCatalogue, RESEARCH_CYCLE_MAX_BYTES, RESEARCH_CYCLE_PILOTS, RESEARCH_STRATEGIES,
  type ResearchCase, type ResearchCaseInput, type ResearchReturnInput, type ResearchStrategy } from "@/lib/discovery-research-cycle";
import type { PreparedQe } from "@/lib/discovery-qe-input";
import type { QeResultContext, QeResultReading } from "@/lib/discovery-qe-result";

const control = "mt-1 block min-h-11 w-full min-w-0 rounded-lg border border-sage-border bg-white px-3 py-2 text-sm";
const title = (c: ResearchCatalogue, id: string) => {
  const state = c.states.find(s => s.id === id)!;
  return `${state.formula} · lattice change ${(state.strain_micro_percent / 1e6).toLocaleString("en-US")}% · ${state.id.slice(-8)}`;
};

/** Local, portable research decisions. No server writes, job submission or scientific approval. */
export function DiscoveryResearchCycle({ catalog }: { catalog: ResearchCatalogue }) {
  const [stateId, setStateId] = useState(catalog.states[0].id);
  const [strategy, setStrategy] = useState<ResearchStrategy>("high_bandwidth");
  const [record, setRecord] = useState<ResearchCase | null>(null);
  const [definition, setDefinition] = useState("");
  const [returnText, setReturnText] = useState("");
  const [model, setModel] = useState<Awaited<ReturnType<typeof prepareResearchModel>> | null>(null);
  const [prepared, setPrepared] = useState<PreparedQe | null>(null);
  const [reading, setReading] = useState<QeResultContext | null>(null);
  const [readings, setReadings] = useState<QeResultReading[]>([]);
  const [branchId, setBranchId] = useState("");
  const [reason, setReason] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const sequence = useRef(0);
  const selectedState = useRef(stateId);
  selectedState.current = stateId;
  const activeAction = useRef<symbol | null>(null);
  function invalidateSelection() { sequence.current++; activeAction.current = null; setBusy(false); setRecord(null); setDefinition(""); setModel(null); setPrepared(null); setReading(null); }
  useEffect(() => {
    const followHash = (hash: string) => {
      const selected = catalog.states.find(s => hash === `#research-state-${s.id.split(":")[1]}`);
      if (selected && selected.id !== selectedState.current) { invalidateSelection(); selectedState.current = selected.id; setStateId(selected.id); }
    };
    const follow = () => followHash(window.location.hash);
    const click = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
      const link = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>("a[href]") : null;
      if (!link || link.hasAttribute("download") || link.target && link.target !== "_self") return;
      const url = new URL(link.href, window.location.href);
      if (url.origin === window.location.origin && url.pathname === window.location.pathname && url.search === window.location.search) followHash(url.hash);
    };
    follow(); window.addEventListener("hashchange", follow); window.addEventListener("popstate", follow); document.addEventListener("click", click);
    return () => { window.removeEventListener("hashchange", follow); window.removeEventListener("popstate", follow); document.removeEventListener("click", click); };
  }, [catalog]);
  useEffect(() => {
    const run = ++sequence.current;
    activeAction.current = null; setBusy(false); setDefinition(""); setRecord(null); setModel(null); setPrepared(null); setReading(null); setReadings([]); setReturnText(""); setReason(""); setStatus(""); setError("");
    researchStateFromCatalogue(catalog, stateId).then(s => {
      if (run === sequence.current) setDefinition(JSON.stringify(createResearchCaseInput(s, strategy), null, 2));
    }).catch(e => { if (run === sequence.current) setError(e instanceof Error ? e.message : "The state could not be prepared."); });
    return () => { sequence.current++; };
  }, [catalog, stateId, strategy]);
  async function action(work: (guard: () => boolean) => Promise<void>) {
    if (busy) return;
    const run = sequence.current, token = Symbol("research-action"); activeAction.current = token;
    const guard = () => sequence.current === run && activeAction.current === token;
    setBusy(true); setError("");
    try { await work(guard); } catch (e) { if (guard()) setError(e instanceof Error ? e.message : "The research operation could not be completed."); }
    finally { if (guard()) { setBusy(false); activeAction.current = null; } }
  }
  async function save(next: ResearchCase, guard: () => boolean) {
    if (!guard()) throw new Error("The selected research state changed during preparation. Retry for the current selection.");
    setRecord(next); setDefinition(JSON.stringify(next.definition, null, 2)); setBranchId(researchDecisionBranches(next)[0]?.id ?? "");
    setReturnText(JSON.stringify({ binding: next.binding, kind: next.definition.action.kind === "source_review" ? "source_review" : "calculation_receipt_link",
      artifacts: [], model_cif_sha256: next.definition.action.kind === "source_review" ? null : next.definition.state.structure?.sha256 ?? null,
      findings: "", remaining_unknowns: ["State-specific stability, pairing and coherence remain unresolved."], numerical_assessment: "not_assessed", association: "researcher_linked_unverified" }, null, 2));
  }
  async function start(followUp: boolean, guard: () => boolean) {
    if (new TextEncoder().encode(definition).length > RESEARCH_CYCLE_MAX_BYTES) throw new Error("The case definition exceeds 512 KiB.");
    const input: ResearchCaseInput = JSON.parse(definition);
    const ref = input.state.catalogue_reference;
    if (!ref || ref.catalogue_version !== catalog.version || ref.catalog_state_id !== stateId) throw new Error("Use the currently selected catalogue state, or import a complete saved research case.");
    await verifyWorkspaceState(catalog, stateId, input.state);
    await save(followUp && record ? await deriveResearchCase(record, input) : await prepareResearchCase(input), guard);
    setStatus(followUp ? "Prepared a linked follow-up; physical evidence was not inherited." : "Prepared a source-linked research case. Export it to retain this work.");
  }
  async function calculationCase(guard: () => boolean) {
    if (!prepared || !model) return;
    const input = createResearchCaseInput(await researchStateFromCatalogue(catalog, stateId), strategy);
    input.state.structure = { artifact_id: model.candidateId, version: model.batch.version, sha256: model.lineage.generated_cif_sha256 };
    input.state.relation_to_catalogue = "proposed_conditions";
    input.state.conditions.charge_state = prepared.manifest.settings.charge;
    input.state.conditions.magnetic_state = prepared.manifest.settings.nspin === 1 ? "nonmagnetic" : "spin_polarized";
    input.action.kind = "calculation";
    input.action.question = `Check the prepared ${prepared.manifest.settings.calculation} calculation for this exact coordinate model before planning a numerical sensitivity study.`;
    input.action.input_artifacts.push({ artifact_id: prepared.filename, version: prepared.manifest.version, sha256: prepared.sha256 });
    input.action.prerequisites = [{ description: "Prepared model was replayed from the selected catalogue state.", status: "met" }, { description: "Execution environment, resource budget and numerical protocol require review.", status: "unknown" }];
    input.action.branches = [
      { id: "readable_run", observable: "Original files agree with the preparation; review numerical sensitivity next.", decision: "continue", next_direction: "refine_method" },
      { id: "incompatible_or_failed", observable: "The run is incompatible or incomplete; correct the method before interpretation.", decision: "redirect", next_direction: "refine_method" },
      { id: "execution_unavailable", observable: "The selected action cannot currently be executed.", decision: "stop", next_direction: "pause" },
    ];
    await save(record?.decision ? await deriveResearchCase(record, input) : await prepareResearchCase(input), guard);
    setStatus("Prepared a calculation case pinned to the regenerated coordinates and exact QE manifest. No job was submitted.");
  }
  async function retainReading(guard: () => boolean) {
    if (!record || !reading) return;
    const r = reading.reading;
    if (!record.definition.action.input_artifacts.some(p => p.sha256 === reading.preparation.prepared.sha256)) throw new Error("This reading uses a different preparation manifest. Prepare a separate action for it.");
    await save(await attachResearchReturn(record, { binding: record.binding, kind: "calculation_receipt_link",
      artifacts: [{ artifact_id: r.filename, version: r.report.version, sha256: r.sha256 }], model_cif_sha256: r.report.candidate_cif_sha256,
      findings: `Native reader status: ${r.report.status}. This single run does not establish numerical sensitivity, physical stability or superconductivity.`,
      remaining_unknowns: ["Cutoff, mesh and smearing sensitivity have not been established by this single run.", "Formation energy, phonons, pairing, coherence and Tc remain unresolved."],
      numerical_assessment: "not_assessed", association: "researcher_linked_unverified" }), guard);
    setStatus("Retained a source-linked reading; no scientific approval or physical result was assigned.");
  }
  async function download(guard: () => boolean) {
    if (!record) return;
    const exportFile = await exportResearchCase(record);
    if (!guard()) return;
    const url = URL.createObjectURL(new Blob([exportFile.json], { type: "application/json" }));
    try { const link = document.createElement("a"); link.href = url; link.download = exportFile.filename; link.click(); setStatus("Research-case download requested. Keep it with the original source and calculation files."); }
    finally { setTimeout(() => URL.revokeObjectURL(url), 1000); }
  }
  const profile = RESEARCH_STRATEGIES.find(s => s.id === strategy)!;
  const readiness = record ? researchCaseReadiness(record) : null;
  const decisionBranches = record ? researchDecisionBranches(record) : [];
  const selectedDecisionBranch = decisionBranches.some(b => b.id === branchId) ? branchId : decisionBranches[0]?.id ?? "";
  return <section id="discovery-research-cycle" className="min-w-0 space-y-4" aria-labelledby="research-cycle-heading">
    <div className="relative h-0" aria-hidden="true">{catalog.states.map(s => <span key={s.id} id={`research-state-${s.id.split(":")[1]}`} className="absolute top-0 scroll-mt-24" />)}</div>
    <h2 id="research-cycle-heading" className="text-lg font-semibold">Research cycle</h2>
    <p className="max-w-3xl text-sm text-sage-muted">Choose a physical question, prepare an exact-state action, retain its original evidence, then record continue, stop or redirect. Cases stay in this browser until exported.</p>
    <div className="grid min-w-0 gap-3 md:grid-cols-2">
      <label className="min-w-0 text-sm font-medium">Coordinate state<select className={control} value={stateId} onChange={e => { invalidateSelection(); setStateId(e.target.value); }}>{catalog.states.map(s => <option key={s.id} value={s.id}>{title(catalog, s.id)}</option>)}</select></label>
      <label className="min-w-0 text-sm font-medium">Research strategy<select className={control} value={strategy} onChange={e => { invalidateSelection(); setStrategy(e.target.value as ResearchStrategy); }}>{RESEARCH_STRATEGIES.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}</select></label>
    </div>
    <p className="max-w-3xl text-sm">{profile.question}</p>
    <details className="text-sm"><summary className="cursor-pointer py-2">Evidence needed, ML role and competing explanations</summary><div className="mt-2 space-y-3"><ul className="list-disc space-y-1 pl-5">{profile.needed_evidence.map(e => <li key={e}>{e}</li>)}</ul><p>{profile.ml_role}</p><p>{profile.boundary}</p><p>{profile.competing_explanations.join("; ")}.</p></div></details>
    <details><summary className="cursor-pointer py-2 text-sm font-medium">Review or edit the case definition</summary><label className="block text-sm">Case definition JSON<textarea className={`${control} font-mono text-xs`} rows={16} spellCheck={false} value={definition} onChange={e => setDefinition(e.target.value)} /></label><p className="mt-2 text-xs text-sage-muted">Review conditions, evidence, action prerequisites, resource budget and decision branches before preparation. Unknown inputs remain null.</p></details>
    <div className="flex flex-wrap gap-3"><button className="btn-primary disabled:opacity-50" disabled={busy || !definition} onClick={() => void action(guard => start(false, guard))}>Prepare research case</button><button className="btn-outline disabled:opacity-50" disabled={busy} onClick={() => void action(async guard => { const replay = await prepareResearchModel(catalog, stateId); if (!guard()) return; setModel(replay); setStatus("Replayed the exact coordinate model. Original occurrence IDs and CIF hashes remain in the catalogue."); })}>Prepare model for QE</button></div>
    <details><summary className="cursor-pointer py-2 text-sm font-medium">Import an exported case</summary><label className="block text-sm">Research case JSON file<input className={control} type="file" accept=".json" onChange={e => {
      const file = e.target.files?.[0]; e.target.value = "";
      if (file) void action(async guard => {
        if (!file.size || file.size > RESEARCH_CYCLE_MAX_BYTES) throw new Error("Choose a nonempty research-case export of at most 512 KiB.");
        const imported = await importResearchCase(await file.text());
        const reference = imported.definition.state.catalogue_reference;
        if (!reference || reference.catalogue_version !== catalog.version || reference.catalog_state_id !== stateId) throw new Error("Select the matching catalogue state before importing this case.");
        if (imported.definition.strategy !== strategy) throw new Error("Select the matching research strategy before importing this case.");
        await verifyWorkspaceState(catalog, stateId, imported.definition.state);
        await save(imported, guard); setStatus("Imported and verified the exact research-case bytes.");
      });
    }} /></label></details>
    {model && <div className="min-w-0 space-y-3"><details><summary className="cursor-pointer py-2 text-sm">Original and regenerated coordinate identities</summary><pre tabIndex={0} className="max-w-full overflow-x-auto rounded-lg border border-sage-border p-3 text-xs">{JSON.stringify(model.lineage, null, 2)}</pre></details><DiscoveryQeInput key={`${stateId}:qe`} batch={model.batch} candidateId={model.candidateId} onPrepared={setPrepared} />{prepared && <button className="btn-outline disabled:opacity-50" disabled={busy} onClick={() => void action(calculationCase)}>Prepare case for this QE manifest</button>}</div>}
    {record && <section className="min-w-0 space-y-3 border-t border-sage-border pt-4" aria-label="Current research case">
      <h3 className="font-semibold">{record.definition.title}</h3><p className="text-sm">Stage: {readiness!.stage.replaceAll("_", " ")} · {record.returns.length} retained returns · {record.decision ? `Decision: ${record.decision.decision}` : "Decision pending"}</p>
      <details className="text-sm"><summary className="cursor-pointer">Action prerequisites and resource readiness</summary><ul className="mt-2 list-disc space-y-1 pl-5">{readiness!.reasons.map(r => <li key={r}>{r}</li>)}</ul><p className="mt-2">{readiness!.research_value}</p><p>Scientific acceptance and authenticated execution are not assigned by this workspace. RPS and rank remain unassigned.</p></details>
      <p className="break-all text-xs text-sage-muted">{record.binding.case_id}</p><button className="btn-outline disabled:opacity-50" disabled={busy} onClick={() => void action(download)}>Export research case</button>
      {!record.decision && <details><summary className="cursor-pointer py-2 text-sm font-medium">Retain a pinned source or calculation return</summary><label className="block text-sm">Return JSON<textarea className={`${control} font-mono text-xs`} rows={12} spellCheck={false} value={returnText} onChange={e => setReturnText(e.target.value)} /></label><p className="my-2 text-xs text-sage-muted">Supply the exact original artifact identity, version and SHA-256, findings and remaining unknowns. A linked artifact does not authenticate its execution.</p><button className="btn-outline disabled:opacity-50" disabled={busy} onClick={() => void action(async guard => { if (new TextEncoder().encode(returnText).length > RESEARCH_CYCLE_MAX_BYTES) throw new Error("The return exceeds 512 KiB."); const next = await attachResearchReturn(record, JSON.parse(returnText) as ResearchReturnInput); await save(next, guard); setStatus("Retained a return bound to this exact state and action."); })}>Retain return</button></details>}
      {!record.decision && record.returns.length > 0 && <div className="min-w-0 space-y-3">{!decisionBranches.length && <p role="alert" className="text-sm text-red-800">No declared branch matches this numerical assessment. Export this case, then prepare a corrected action with suitable decision branches.</p>}<label className="block text-sm">Decision branch<select className={control} value={selectedDecisionBranch} onChange={e => setBranchId(e.target.value)}>{decisionBranches.map(b => <option key={b.id} value={b.id}>{b.decision}: {b.observable}</option>)}</select></label><label className="block text-sm">Decision reason<textarea className={control} rows={3} value={reason} onChange={e => setReason(e.target.value)} maxLength={2000} /></label><button className="btn-outline disabled:opacity-50" disabled={busy || !reason.trim() || !decisionBranches.length} onClick={() => void action(async guard => { const branch = decisionBranches.find(b => b.id === selectedDecisionBranch); if (!branch) throw new Error("No declared decision branch matches the retained numerical assessment. Prepare a corrected follow-up definition."); await save(await recordResearchDecision(record, { return_sha256: record.returns.at(-1)!.return_sha256, branch_id: branch.id, decision: branch.decision, next_direction: branch.next_direction, reason }), guard); setStatus("Recorded an immutable research decision. Edit a fresh definition to prepare a linked follow-up."); })}>Record research decision</button></div>}
      {record.decision && <button className="btn-outline disabled:opacity-50" disabled={busy} onClick={() => void action(async guard => { const next = createResearchCaseInput(await researchStateFromCatalogue(catalog, stateId), strategy); await save(await deriveResearchCase(record, next), guard); setStatus("Prepared a linked follow-up source review. Previous physical evidence was not inherited."); })}>Prepare linked follow-up</button>}
    </section>}
    <details className="min-w-0"><summary className="cursor-pointer py-2 text-sm font-medium">Read original QE output</summary><div className="mt-3"><DiscoveryQeResult key={`${stateId}:${strategy}`} onContext={setReading} /></div>{reading && record && <div className="mt-3 flex flex-wrap gap-3">
      {!record.decision && record.definition.action.kind === "calculation" && <button className="btn-outline disabled:opacity-50" disabled={busy} onClick={() => void action(retainReading)}>Retain reading in this case</button>}
      <button className="btn-outline disabled:opacity-50" disabled={busy} onClick={() => void action(async guard => {
        if (record.definition.state.structure?.sha256 !== reading.reading.report.candidate_cif_sha256) throw new Error("This reading belongs to another coordinate model. Prepare the matching calculation case first.");
        if (readings.some(r => r.sha256 === reading.reading.sha256)) throw new Error("This exact reading is already in the study.");
        if (readings.length >= 16) throw new Error("Keep at most 16 readings in one numerical study.");
        if (guard()) { setReadings([...readings, reading.reading]); setStatus("Added the exact original-file reading to this model's local study."); }
      })}>Add reading to numerical study</button>
    </div>}</details>
    {record && readings.length > 0 && <fieldset disabled={busy} className="min-w-0 space-y-3"><DiscoveryQeStudyCase record={record} readings={readings} onCase={next => { void action(async guard => { await verifyWorkspaceState(catalog, stateId, next.definition.state); await save(next, guard); }); }} /><button className="btn-outline" onClick={() => setReadings([])}>Clear numerical study readings</button></fieldset>}
    <details className="text-sm"><summary className="cursor-pointer py-2">Starting research recipes</summary><div className="divide-y divide-sage-border">{RESEARCH_CYCLE_PILOTS.map(p => <article key={p.key} className="space-y-2 py-3"><h3 className="font-semibold">{p.formula} · {p.stage.replaceAll("_", " ")}</h3><p>{p.question}</p><p>{p.evidence}</p><p>{p.next_action}</p><a className="site-text-link inline-flex min-h-11 items-center" href={p.tool_href}>Open referenced tool</a></article>)}</div></details>
    {busy && <p role="status" className="text-sm">Preparing research data…</p>}{status && <p role="status" className="text-sm text-sage-muted">{status}</p>}{error && <p role="alert" className="break-words text-sm text-red-800">{error}</p>}
  </section>;
}
