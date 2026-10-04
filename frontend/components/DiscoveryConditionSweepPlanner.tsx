"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { createConditionSweep, estimateConditionSweep, type ConditionSweepAxes, type ConditionSweepEstimate, type ConditionSweepManifest } from "@/lib/discovery-condition-sweep";
import type { DesignCapabilities, DesignEntry, ResearchDesign } from "@/lib/discovery-designs";

const input = "mt-1 block min-h-11 w-full min-w-0 rounded-lg border border-sage-border bg-white px-3 py-2 text-sm text-sage-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent";
const button = "min-h-11 rounded-lg border border-sage-border bg-white px-3 py-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50";
const primary = "min-h-11 rounded-lg bg-accent-deep px-4 py-2 text-sm font-medium text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50";
type Props = { entry: DesignEntry; capabilities: DesignCapabilities; disabled?: boolean; onSelect: (proposal: ResearchDesign) => void; onGenerated?: (manifest: ConditionSweepManifest | null) => void };

function axes(pressures: string, temperatures: string): ConditionSweepAxes {
  const lines = (text: string) => text.trim() ? text.trim().split(/\r?\n/).map(line => line.trim()) : [];
  return {
    pressures: lines(pressures).map(raw => raw.toLowerCase() === "ambient" ? { kind: "ambient", raw_gpa: null }
      : raw.toLowerCase() === "unspecified" ? { kind: "unspecified", raw_gpa: null } : { kind: "specified", raw_gpa: raw }),
    temperatures_k: lines(temperatures).map(raw => raw.toLowerCase() === "unspecified" ? null : raw),
  };
}
function conditionLabel(conditions: ResearchDesign["target_conditions"]) {
  const p = conditions.pressure;
  return `${p.kind === "ambient" ? "Ambient target" : p.kind === "specified" ? `${p.raw_gpa} GPa target` : "Pressure unspecified"} · ${conditions.temperature_k === null ? "Temperature unspecified" : `${conditions.temperature_k} K target`}`;
}
function message(error: unknown) {
  const code = error && typeof error === "object" && "code" in error ? String(error.code) : "";
  if (code === "sweep_empty_axis") return "Add at least one explicit choice to each axis. Empty choices are not replaced with zero.";
  if (code === "sweep_axis_limit" || code === "sweep_scenario_limit") return "Use at most eight choices per axis and 64 combinations. This sweep has not been partially generated.";
  if (["sweep_decimal_invalid", "sweep_pressure_invalid", "sweep_temperature_invalid", "sweep_axes_invalid"].includes(code)) return "Review the choices: use finite nonnegative decimal numbers, ambient for pressure, or unspecified. Each line must contain one choice, at most 64 characters.";
  if (code === "sweep_manifest_limit") return "This manifest is too large. Reduce the choices or shorten the parent proposal before generating again.";
  return "The parent or source reference could not be verified. Reload access and saved history before generating another sweep.";
}

/** Local, bounded condition scenarios. Selecting one only fills the existing proposal form. */
export function DiscoveryConditionSweepPlanner(props: Props) {
  const identity = JSON.stringify({ actor: props.capabilities.actor_user_id, session: props.capabilities.session_version,
    grant: props.capabilities.curator_grant_id, entry: props.entry });
  return <Planner key={identity} {...props} />;
}
function Planner({ entry, capabilities, disabled = false, onSelect, onGenerated }: Props) {
  const [pressures, setPressures] = useState(""), [temperatures, setTemperatures] = useState("");
  const [estimated, setEstimated] = useState<{ axes: ConditionSweepAxes; value: ConditionSweepEstimate } | null>(null);
  const [manifest, setManifest] = useState<ConditionSweepManifest | null>(null), [error, setError] = useState("");
  const [busy, setBusy] = useState(false), [offset, setOffset] = useState(0), [downloaded, setDownloaded] = useState(false);
  const generation = useRef(0), mounted = useRef(true), disclosure = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    mounted.current = true;
    const clear = () => { ++generation.current; onGenerated?.(null); setPressures(""); setTemperatures(""); setEstimated(null); setManifest(null); setError(""); setBusy(false); setOffset(0); setDownloaded(false); if (disclosure.current) disclosure.current.open = false; };
    const visibility = () => { if (document.visibilityState === "hidden") clear(); };
    window.addEventListener("pagehide", clear); document.addEventListener("visibilitychange", visibility);
    return () => { mounted.current = false; ++generation.current; window.removeEventListener("pagehide", clear); document.removeEventListener("visibilitychange", visibility); };
  }, []);
  function change(update: () => void) { ++generation.current; onGenerated?.(null); update(); setEstimated(null); setManifest(null); setError(""); setBusy(false); setOffset(0); setDownloaded(false); }
  function estimate(event: FormEvent) {
    event.preventDefault(); if (disabled || busy) return; ++generation.current; onGenerated?.(null); setManifest(null); setError(""); setDownloaded(false);
    try { const next = axes(pressures, temperatures); setEstimated({ axes: next, value: estimateConditionSweep(next) }); }
    catch (caught) { setEstimated(null); setError(message(caught)); }
  }
  async function generate() {
    if (!estimated || disabled || busy) return; const current = ++generation.current; onGenerated?.(null); setBusy(true); setManifest(null); setError(""); setOffset(0); setDownloaded(false);
    try { const next = await createConditionSweep({ capabilities, entry, axes: estimated.axes }); if (mounted.current && current === generation.current) { setManifest(next); onGenerated?.(structuredClone(next)); } }
    catch (caught) { if (mounted.current && current === generation.current) setError(message(caught)); }
    finally { if (mounted.current && current === generation.current) setBusy(false); }
  }
  function download() {
    if (!manifest || disabled || busy) return; let url: string | null = null;
    try { url = URL.createObjectURL(new Blob([JSON.stringify(manifest, null, 2) + "\n"], { type: "application/json;charset=utf-8" })); const link = document.createElement("a"); link.href = url; link.download = `sclib-condition-sweep-${manifest.manifest_sha256.slice(0, 12)}.json`; document.body.appendChild(link); link.click(); link.remove(); setDownloaded(true); }
    catch { setError("The browser could not start the manifest download. The prepared scenarios remain available here."); }
    finally { if (url) setTimeout(() => URL.revokeObjectURL(url!), 1000); }
  }
  const canUse = !disabled && !busy && entry.is_head && entry.status === "proposed" && entry.eligibility.eligible && entry.baseline.kind !== "unanchored";
  return <details ref={disclosure} className="min-w-0 space-y-3 border-t border-sage-border pt-4" aria-label="Condition sweep planner">
    <summary className="cursor-pointer font-semibold">Plan a bounded condition sweep</summary>
    <p className="text-sm leading-6 text-sage-muted">Choose explicit pressure and temperature targets for this proposal. Review the combination count before generating a local research list.</p>
    <p className="text-xs text-sage-muted">The parent hypothesis, modifications and next action are copied as researcher proposals. Source properties stay in the separate reference above.</p>
    <form onSubmit={estimate} noValidate className="space-y-3" aria-label="Condition sweep choices">
      <fieldset disabled={disabled || busy} className="grid gap-3 sm:grid-cols-2">
        <label className="min-w-0 text-sm">Pressure choices (GPa, one per line)<textarea className={input} rows={4} maxLength={600} value={pressures} onChange={e => change(() => setPressures(e.target.value))} aria-describedby="sweep-pressure-help" /></label>
        <label className="min-w-0 text-sm">Temperature choices (K, one per line)<textarea className={input} rows={4} maxLength={600} value={temperatures} onChange={e => change(() => setTemperatures(e.target.value))} aria-describedby="sweep-temperature-help" /></label>
      </fieldset>
      <p id="sweep-pressure-help" className="text-xs leading-5 text-sage-muted">Pressure accepts a number, ambient (approximately 1 atm) or unspecified. A specified 0 GPa target stays distinct from ambient.</p>
      <p id="sweep-temperature-help" className="text-xs leading-5 text-sage-muted">Temperature accepts a number or unspecified. Each axis needs 1–8 choices. Empty choices remain incomplete; equivalent decimal aliases are counted once.</p>
      <button type="submit" className={button} disabled={disabled || busy}>Estimate combinations</button>
    </form>
    {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</p>}
    {estimated && <section className="space-y-3 rounded-lg bg-sage-surface p-3" aria-label="Condition sweep estimate">
      <p className="text-sm"><strong>{estimated.value.unique_cartesian_count} unique condition combinations</strong> from {estimated.value.raw_cartesian_count} raw combinations · maximum {estimated.value.max_scenarios}.</p>
      <p className="text-xs text-sage-muted">{estimated.value.pressure.collapsed_count} duplicate pressure choices and {estimated.value.temperature.collapsed_count} duplicate temperature choices collapsed. Raw decimal spellings remain in the manifest input.</p>
      <button type="button" className={primary} disabled={disabled || busy} onClick={() => void generate()}>{busy ? "Verifying parent and preparing scenarios…" : "Generate scenarios"}</button>
    </section>}
    {manifest && <section className="min-w-0 space-y-3" aria-label="Prepared condition scenarios">
      <div className="flex flex-wrap items-center justify-between gap-3"><h4 className="font-medium">Requested condition scenarios ({manifest.scenarios.length})</h4><button type="button" className={button} disabled={disabled || busy} onClick={download}>Download sweep manifest</button></div>
      <p className="text-xs leading-5 text-sage-muted">Select one scenario to fill a linked proposal, then reload the current baseline and preview before saving. The batch manifest remains local; saving a proposal retains its parent and conditions, and does not retain this generation batch.</p>
      <div role="region" aria-label="Requested condition scenarios" tabIndex={0} className="min-w-0 max-w-full overflow-x-auto focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
        <table role="table" className="block w-full min-w-0 text-left text-sm sm:table sm:min-w-[32rem]">
          <thead role="rowgroup" className="sr-only border-b border-sage-border text-xs text-sage-muted sm:not-sr-only sm:table-header-group"><tr role="row"><th role="columnheader" className="py-2 pr-3">Requested conditions</th><th role="columnheader" className="py-2 pr-3">Proposed next action</th><th role="columnheader" className="py-2">Selection</th></tr></thead>
          <tbody role="rowgroup" className="block divide-y divide-sage-border sm:table-row-group">{manifest.scenarios.slice(offset, offset + 8).map(scenario => <tr role="row" key={scenario.candidate_id} className="block py-3 sm:table-row sm:py-0">
            <td role="cell" className="block break-words align-top [overflow-wrap:anywhere] sm:table-cell sm:py-3 sm:pr-3"><span aria-hidden="true" className="mb-1 block text-xs text-sage-muted sm:hidden">Requested conditions</span>{conditionLabel(scenario.conditions)}</td>
            <td role="cell" className="mt-3 block break-words align-top [overflow-wrap:anywhere] sm:mt-0 sm:table-cell sm:max-w-60 sm:py-3 sm:pr-3"><span aria-hidden="true" className="mb-1 block text-xs text-sage-muted sm:hidden">Proposed next action</span>{scenario.proposal.next_action.question}</td>
            <td role="cell" className="mt-3 block align-top sm:mt-0 sm:table-cell sm:py-3"><button type="button" className={`${button} w-full sm:w-auto`} disabled={!canUse} aria-label={`Use ${conditionLabel(scenario.conditions)}`} onClick={() => onSelect(structuredClone(scenario.proposal))}>Use scenario</button></td>
          </tr>)}</tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center gap-3 text-xs"><button type="button" className={button} disabled={offset === 0 || disabled || busy} onClick={() => setOffset(Math.max(0, offset - 8))}>Previous scenarios</button><span>{offset + 1}–{Math.min(offset + 8, manifest.scenarios.length)} of {manifest.scenarios.length}</span><button type="button" className={button} disabled={offset + 8 >= manifest.scenarios.length || disabled || busy} onClick={() => setOffset(offset + 8)}>Next scenarios</button></div>
      <p className="text-xs leading-5 text-sage-muted">No atomic sites or calculation inputs are generated. Per-action budgets stay as entered; batch resource totals remain unknown or unaggregated.</p>
      <details className="text-xs"><summary className="cursor-pointer">Inspect local manifest and exact generation pins</summary><pre tabIndex={0} className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-sage-surface p-3">{JSON.stringify(manifest, null, 2)}</pre></details>
      {downloaded && <p role="status" className="text-sm">Manifest download requested. Keep the file to trace these local choices.</p>}
    </section>}
  </details>;
}
