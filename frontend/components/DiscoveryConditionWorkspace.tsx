"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import Link from "@/components/AppLink";
import { AVAILABILITY_LABELS, SCIENTIFIC_FIELDS, scientificQuantity, type ScientificMaterial, type ScientificReceipt } from "@/lib/discovery-scientific";
import { CONDITION_STAGES, CONDITION_DESIGN_MAX_MODIFICATIONS, MODIFICATION_KINDS, PAIRING_ROUTES,
  conditionDesignPublication, createConditionDesignPlan, initialConditionDesign, type ConditionDesignInput, type ConditionDesignPlan, type ModificationKind, type PairingRoute } from "@/lib/discovery-condition-design";

const inputStyle = "mt-1 block min-h-11 w-full rounded-lg border border-sage-border bg-white px-3 py-2 text-sm text-sage-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent";
const buttonStyle = "min-h-11 rounded-lg border border-sage-border bg-white px-3 py-2 text-sm text-sage-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60";
export interface DiscoveryConditionWorkspaceProps {
  row?: ScientificMaterial | null;
  receipt?: ScientificReceipt | null;
}

/** Consumes a verified selected public row. Local design fields never mutate it. */
export function DiscoveryConditionWorkspace({ row = null, receipt = null }: DiscoveryConditionWorkspaceProps) {
  // Reset synchronously by source identity, so an old prepared draft cannot
  // appear for even one render under a newly selected publication or row.
  const sourceIdentity = JSON.stringify({ row, publication: conditionDesignPublication(receipt) });
  return <WorkspaceContent key={sourceIdentity} row={row} receipt={receipt} />;
}
function WorkspaceContent({ row: sourceRow = null, receipt: sourceReceipt = null }: DiscoveryConditionWorkspaceProps) {
  const [sourceHidden, setSourceHidden] = useState(false);
  const row = sourceHidden || !sourceReceipt ? null : sourceRow;
  const receipt = sourceHidden ? null : sourceReceipt;
  const [draft, setDraft] = useState<ConditionDesignInput>(() => initialConditionDesign(row));
  const [prepared, setPrepared] = useState<ConditionDesignPlan | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [downloaded, setDownloaded] = useState(false);
  const generation = useRef(0);
  const resultHeading = useRef<HTMLHeadingElement>(null);
  const formDisclosure = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const hide = () => {
      generation.current++; setDraft(initialConditionDesign(null)); setPrepared(null); setError(""); setBusy(false); setDownloaded(false); setSourceHidden(true);
      if (formDisclosure.current) formDisclosure.current.open = false;
    };
    const visibility = () => { if (document.visibilityState === "hidden") hide(); };
    document.addEventListener("visibilitychange", visibility); window.addEventListener("pagehide", hide);
    return () => { generation.current++; document.removeEventListener("visibilitychange", visibility); window.removeEventListener("pagehide", hide); };
  }, []);
  function edit(next: ConditionDesignInput) {
    generation.current++; setDraft(next); setPrepared(null); setError(""); setBusy(false); setDownloaded(false);
  }
  function field<K extends keyof ConditionDesignInput>(key: K, value: ConditionDesignInput[K]) { edit({ ...draft, [key]: value }); }
  async function prepare(event: FormEvent) {
    event.preventDefault(); if (busy) return;
    const current = ++generation.current; setPrepared(null); setError(""); setBusy(true); setDownloaded(false);
    try {
      const plan = await createConditionDesignPlan(draft, row, receipt);
      if (generation.current === current) { setPrepared(plan); requestAnimationFrame(() => resultHeading.current?.focus()); }
    } catch (caught) {
      if (generation.current === current) setError(caught instanceof Error ? caught.message : "The local design could not be prepared. Review the fields and try again.");
    } finally { if (generation.current === current) setBusy(false); }
  }
  function download() {
    if (!prepared) return;
    let url: string | null = null;
    try {
      url = URL.createObjectURL(new Blob([prepared.json], { type: "application/json;charset=utf-8" }));
      const link = document.createElement("a"); link.href = url;
      link.download = `sclib-condition-design-${prepared.plan.content_sha256.slice(0, 12)}.json`;
      document.body.appendChild(link); link.click(); link.remove(); setDownloaded(true);
    } catch { setError("The browser could not start the JSON download. Your prepared plan remains available below."); }
    finally { if (url) setTimeout(() => URL.revokeObjectURL(url!), 1000); }
  }
  const sourcePressure = row?.state_context.pressure_status === "explicit_ambient" ? "Explicit ambient (stored as 0 GPa)"
    : row?.state_context.pressure_status === "reported" ? `${row.state_context.pressure_gpa} GPa`
      : row?.state_context.pressure_status.replaceAll("_", " ") ?? "No selected source";
  return <section aria-labelledby="condition-workspace-heading" className="space-y-5 rounded-xl border border-sage-border bg-white p-4 sm:p-5">
    <header className="space-y-2">
      <h2 id="condition-workspace-heading" className="text-xl font-semibold tracking-tight">Design superconducting conditions</h2>
      <p className="max-w-3xl text-sm leading-6 text-sage-muted">Study the host, electronic activation, pairing and coherence. Define a hypothesis and the next calculation or experiment.</p>
      <p className="text-sm font-medium text-accent">Host → Modification → State → Conditions</p>
      <Link className="inline-block text-sm text-accent-deep underline underline-offset-4" href="/dashboard/research/discovery-designs">Open private research-design history</Link>
    </header>
    {row ? <div className="space-y-2 rounded-lg bg-sage-surface p-3 text-sm" role="note">
      <p><strong>Selected source:</strong> {row.assessment.formula} · {row.assessment.state_summary}</p>
      <p><strong>Source pressure:</strong> {sourcePressure} · <strong>Recorded next action:</strong> {row.assessment.action_summary}</p>
      <p className="text-xs text-sage-muted">This reference describes its selected state. A proposed modification creates a new research question; it does not inherit the source results or reviewed action.</p>
    </div> : <p role="status" className="rounded-lg bg-sage-surface p-3 text-sm">{sourceHidden ? "Source context and local draft cleared after leaving this page. Select the publication and material again to use source evidence." : sourceRow && !sourceReceipt ? "Source publication context is missing. Select the publication and material again to inspect verified source evidence." : "No published material state selected. Select a verified source record to inspect its evidence. A local hypothesis can still be outlined without source support."}</p>}

    <div className="grid gap-4 md:grid-cols-2" aria-label="Four research stages">
      {CONDITION_STAGES.map(stage => {
        const cells = stage.fields.map(key => row?.cells.find(c => c.property_key === key));
        const populated = cells.filter(c => c?.observations.length).length;
        return <section key={stage.key} aria-label={`${stage.title} research question`} className="min-w-0 space-y-3 border-t border-sage-border pt-3">
          <h3 className="font-semibold">{stage.title}</h3><p className="text-sm leading-6">{stage.question}</p>
          {row && <p className="text-xs text-sage-muted">{populated} / {stage.fields.length} fields with recorded results · coverage, not a scientific verdict</p>}
          {row && <dl className="space-y-3 text-sm">{stage.fields.map((key, index) => {
            const cell = cells[index];
            return <div key={key} className="min-w-0">
              <dt className="font-medium">{SCIENTIFIC_FIELDS[key].label} <span className="font-normal text-sage-muted">[{SCIENTIFIC_FIELDS[key].unit === "1" ? "dimensionless" : SCIENTIFIC_FIELDS[key].unit}]</span></dt>
              <dd className="mt-1 break-words [overflow-wrap:anywhere]">{cell ? AVAILABILITY_LABELS[cell.availability] : "No selected record"}
                {cell?.observations.length ? <ul className="mt-1 space-y-1">{cell.observations.map(o => <li key={o.property.id}>
                  <span>{scientificQuantity(o.quantity)} · {o.event.knowledge_origin}</span>
                  <span className="block text-xs text-sage-muted">{o.scientific_scope_accepted ? "Accepted review: sampled phonon minimum only" : "Scientific result unreviewed"}</span>
                  <details className="mt-1"><summary className="cursor-pointer text-xs text-accent underline underline-offset-4">Inspect result, state, run and review pins</summary>
                    <pre tabIndex={0} aria-label={`${SCIENTIFIC_FIELDS[key].label} source pins`} className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap break-all rounded border border-sage-border bg-sage-surface p-2 text-xs">{JSON.stringify(o, null, 2)}</pre>
                  </details>
                </li>)}</ul> : cell && <p className="mt-1 text-xs text-sage-muted">{cell.reason_code.replaceAll("_", " ")}</p>}
              </dd>
            </div>;
          })}</dl>}
        </section>;
      })}
    </div>
    <details className="rounded-lg border border-sage-border p-3 text-sm">
      <summary className="cursor-pointer font-medium">Evidence scope and design-space limits</summary>
      <div className="mt-3 space-y-2 leading-6 text-sage-muted">
        {CONDITION_STAGES.map(stage => <p key={stage.key}><strong>{stage.title}:</strong> {stage.scope}</p>)}
        <p>Stability and electronic or pairing behavior are separate research questions. A useful numerical map needs compatible states, physical definitions, conditions and methods.</p>
        <p>No scatter coordinates or scores are inferred from missing fields or RPS. RPS prioritizes a reviewed action within a fixed campaign and budget; this draft does not reassess it.</p>
        <p>Ambient pressure and approximately 300 K are design targets to test. A high-pressure reference can inform a substitution, strain or interface hypothesis; it does not establish ambient survival or successful translation.</p>
      </div>
    </details>

    <details ref={formDisclosure} className="border-t border-sage-border pt-4">
      <summary className="cursor-pointer font-semibold">Outline a local research design</summary>
    <form onSubmit={prepare} noValidate aria-label="Local condition-design hypothesis" className="mt-4 space-y-4">
      <p className="text-sm leading-6 text-sage-muted">All fields below are your proposal. Preparing a plan keeps it in this page until you export it; no database write or calculation is submitted.</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="min-w-0 text-sm">Proposed host label<input className={inputStyle} value={draft.hostLabel} required maxLength={4000} onChange={e => field("hostLabel", e.target.value)} aria-describedby="host-label-scope" /></label>
        <label className="min-w-0 text-sm">Proposed state label<input className={inputStyle} value={draft.stateLabel} required maxLength={200} onChange={e => field("stateLabel", e.target.value)} placeholder="Name the modified state" /></label>
      </div>
      <p id="host-label-scope" className="text-xs leading-5 text-sage-muted">The initial host label is copied from the selected formula when available. It is not a verified stable-host designation or a parent–child association.</p>
      <fieldset className="space-y-3"><legend className="text-sm font-medium">Proposed modifications</legend>
        {draft.modifications.map((modification, index) => <div key={index} className="grid gap-3 rounded-lg border border-sage-border p-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_auto] sm:items-start">
          <label className="min-w-0 text-sm">Modification {index + 1} kind<select className={inputStyle} value={modification.kind} onChange={e => field("modifications", draft.modifications.map((m, i) => i === index ? { ...m, kind: e.target.value as ModificationKind } : m))}>{Object.entries(MODIFICATION_KINDS).map(([kind, name]) => <option key={kind} value={kind}>{name}</option>)}</select></label>
          <label className="min-w-0 text-sm">Modification {index + 1} parameters<textarea className={inputStyle} rows={2} required maxLength={2000} value={modification.parameters} placeholder="Species, site, amount, reference and units" onChange={e => field("modifications", draft.modifications.map((m, i) => i === index ? { ...m, parameters: e.target.value } : m))} /></label>
          <button type="button" className={`${buttonStyle} sm:mt-6`} disabled={draft.modifications.length === 1} aria-label={`Remove modification ${index + 1}`} onClick={() => field("modifications", draft.modifications.filter((_, i) => i !== index))}>Remove</button>
        </div>)}
        <button type="button" className={buttonStyle} disabled={draft.modifications.length >= CONDITION_DESIGN_MAX_MODIFICATIONS} onClick={() => field("modifications", [...draft.modifications, { kind: "doping", parameters: "" }])}>Add modification</button>
        <p className="text-xs text-sage-muted">Up to eight explicit modifications form one proposed state. No automatic Cartesian expansion or fabricated genealogy is created.</p>
      </fieldset>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <label className="min-w-0 text-sm">Target pressure<select className={inputStyle} value={draft.targetPressure} onChange={e => field("targetPressure", e.target.value as ConditionDesignInput["targetPressure"])}><option value="unspecified">Unspecified target</option><option value="ambient">Ambient target, approximately 1 atm</option><option value="specified">Specify target in GPa</option></select></label>
        {draft.targetPressure === "specified" && <label className="min-w-0 text-sm">Target pressure (GPa)<input className={inputStyle} inputMode="decimal" value={draft.pressureGpa} onChange={e => field("pressureGpa", e.target.value)} /></label>}
        <label className="min-w-0 text-sm">Target temperature (K, optional)<input className={inputStyle} inputMode="decimal" value={draft.temperatureK} onChange={e => field("temperatureK", e.target.value)} placeholder="Unspecified" /></label>
        <label className="min-w-0 text-sm">Pairing hypothesis<select className={inputStyle} value={draft.pairingRoute} onChange={e => field("pairingRoute", e.target.value as PairingRoute)}>{Object.entries(PAIRING_ROUTES).map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select></label>
      </div>
      <label className="block text-sm">Research hypothesis<textarea className={inputStyle} rows={3} required maxLength={2000} value={draft.hypothesis} onChange={e => field("hypothesis", e.target.value)} placeholder="What physical condition could change, and what evidence would test it?" /></label>
      <label className="block text-sm">Proposed next action<textarea className={inputStyle} rows={2} required maxLength={2000} value={draft.nextAction} onChange={e => field("nextAction", e.target.value)} placeholder="One calculation, source review or experiment that would change the decision" /></label>
      {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</p>}
      <button type="submit" className="min-h-11 rounded-lg bg-accent-deep px-4 py-2 text-sm font-semibold text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-60" disabled={busy}>{busy ? "Preparing local plan…" : "Prepare plan"}</button>
    </form></details>
    {prepared && <section aria-labelledby="condition-plan-heading" className="space-y-3 rounded-lg border border-sage-border bg-sage-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-3"><h3 id="condition-plan-heading" ref={resultHeading} tabIndex={-1} className="font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">Prepared local research plan</h3><button type="button" className={buttonStyle} onClick={download}>Export JSON</button></div>
      <p className="text-sm"><strong>Next action:</strong> {prepared.plan.user_proposal.next_action}</p>
      <p className="text-xs leading-5 text-sage-muted">Requirements below are proposed follow-up work. No execution, scientific approval, modified-state result or new RPS score is established.</p>
      <ol className="space-y-4">{prepared.plan.work_plan.map((step, index) => <li key={`${step.stage}:${step.kind}`} className="space-y-2 text-sm">
        <h4 className="font-medium">{index + 1}. {step.question}</h4><p className="text-xs text-sage-muted">{step.kind.replaceAll("_", " ")} · proposal only</p>
        <ul className="list-disc space-y-1 pl-5 text-xs leading-5">{step.requirements.map(requirement => <li key={requirement}>{requirement}</li>)}</ul>
      </li>)}</ol>
      <details><summary className="cursor-pointer text-sm font-medium">Inspect reproducible plan and source pins</summary><pre tabIndex={0} aria-label="Prepared condition-design JSON" className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-all rounded border border-sage-border bg-white p-3 text-xs">{prepared.json}</pre></details>
      {downloaded && <p role="status" className="text-sm">JSON download requested. The plan checksum identifies this local draft, not scientific validity.</p>}
    </section>}
  </section>;
}
