"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { DISCOVERY_DEMO_ROWS, type DiscoveryDemoRow } from "@/lib/discovery-layout-demo";
import { PHYSICAL_DIMENSIONS } from "@/lib/research-priority";
import { FIELD_BY_KEY, FIELD_GROUPS, OVERVIEW_KEYS, ROLE_LABELS, SCIENTIFIC_FIELDS, checkedScientificValue, formatScientificValue, type FieldGroup, type ScientificValue } from "@/lib/discovery-field-registry";
import { DiscoveryFieldGuide } from "@/components/DiscoveryFieldGuide";

const format = (value: number | null, digits = 0) => value === null ? "—" : value.toLocaleString("en-US", { maximumFractionDigits: digits });
const cell = "whitespace-nowrap border-b border-sage-border/60 px-3 py-3 text-right tabular-nums";
const header = "whitespace-nowrap border-b border-sage-border bg-sage-surface px-3 py-2.5 text-right font-medium";
const selectStyle = "rounded-md border border-sage-border bg-white px-3 py-2 text-sm";
type View = "overview" | FieldGroup;
const valueFor = (row: DiscoveryDemoRow, key: string) => checkedScientificValue(key, row.fields[key], row.stateId);

function ScoreCell({ value, label }: { value: number; label: string }) {
  return <td className={cell} title={`${label}: ${format(value, 1)} / 100 (synthetic)`}><span className={`inline-block min-w-11 rounded px-2 py-1 ${value >= 75 ? "bg-emerald-50 text-emerald-800" : value >= 50 ? "bg-slate-100 text-slate-700" : "bg-amber-50 text-amber-800"}`}>{format(value, 1)}</span></td>;
}

function ValueDetail({ value }: { value: ScientificValue }) {
  if (value.availability !== "known") return <p className="mt-2 text-sm">{formatScientificValue(value)}: {value.reason}</p>;
  return <div className="mt-3 space-y-1 text-sm">
    <p className="font-semibold">{formatScientificValue(value)} {value.kind === "number" ? value.unit : ""}</p>
    {value.kind === "artifact" && <p className="text-amber-800">Illustrative artifact reference only; no actual calculation artifact is available.</p>}
    <p>{value.provenance.origin} · {value.provenance.review} · {value.provenance.synthetic ? "Synthetic" : "Source-backed"}</p>
    <p>{value.provenance.locator}</p><p>{value.provenance.method}</p>
    {value.provenance.normalization && <p>Normalization: {value.provenance.normalization}</p>}
    {value.kind === "number" && value.uncertainty && <p>Uncertainty definition: {value.uncertainty.definition}</p>}
    {value.kind === "number" && value.original && <p>Original record: {value.original.value} {value.original.unit} · Conversion: {value.original.conversion}</p>}
    <p>{value.provenance.context}</p><p className="break-all font-mono text-xs text-sage-muted">State: {value.provenance.stateId} · Result: {value.provenance.resultId}</p>
  </div>;
}

export function DiscoveryLayoutPreview() {
  const [query, setQuery] = useState("");
  const [family, setFamily] = useState("all");
  const [profile, setProfile] = useState("all");
  const [view, setView] = useState<"data" | "physics">("data");
  const [group, setGroup] = useState<View>("overview");
  const [visibleKeys, setVisibleKeys] = useState<string[]>(OVERVIEW_KEYS);
  const [columnPicker, setColumnPicker] = useState(false);
  const [selected, setSelected] = useState<DiscoveryDemoRow | null>(null);
  const [selectedField, setSelectedField] = useState<string | null>(null);
  const [descending, setDescending] = useState(true);
  const detailRef = useRef<HTMLElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (selected || selectedField) { detailRef.current?.focus(); detailRef.current?.scrollIntoView?.({ block: "nearest" }); }
  }, [selected, selectedField]);
  const families = [...new Set(DISCOVERY_DEMO_ROWS.map(row => row.family))];
  const profiles = [...new Set(DISCOVERY_DEMO_ROWS.flatMap(row => row.profiles))];
  const groupFields = group === "overview" ? OVERVIEW_KEYS.map(key => FIELD_BY_KEY[key]) : SCIENTIFIC_FIELDS.filter(field => field.group === group);
  const activeFields = visibleKeys.map(key => FIELD_BY_KEY[key]);
  const groupDefinition = FIELD_GROUPS.find(item => item.id === group);
  const rows = useMemo(() => DISCOVERY_DEMO_ROWS.filter(row =>
    (family === "all" || row.family === family) && (profile === "all" || row.profiles.some(p => p === profile)) &&
    `${row.formula} ${row.family} ${row.id} ${row.profiles.join(" ")}`.normalize("NFKC").toLowerCase().includes(query.trim().normalize("NFKC").toLowerCase()),
  ).sort((a, b) => a.score === null && b.score === null ? a.id.localeCompare(b.id) : a.score === null ? 1 : b.score === null ? -1 : (descending ? b.score - a.score : a.score - b.score) || a.id.localeCompare(b.id)), [query, family, profile, descending]);

  function changeGroup(next: View) {
    setGroup(next); setView("data"); setSelectedField(null);
    setVisibleKeys(next === "overview" ? OVERVIEW_KEYS : SCIENTIFIC_FIELDS.filter(field => field.group === next).slice(0, 6).map(field => field.key));
  }
  function inspect(row: DiscoveryDemoRow | null, key: string | null, trigger?: HTMLElement) {
    if (trigger) returnFocus.current = trigger;
    setSelected(row); setSelectedField(key);
    if (!row && !key) returnFocus.current?.focus();
  }
  const detailField = selectedField ? FIELD_BY_KEY[selectedField] : null;

  return <main className="space-y-4">
    <header className="flex flex-wrap items-end justify-between gap-3">
      <div className="flex items-baseline gap-3"><h1 className="text-3xl font-semibold tracking-tight">Discovery</h1><span className="text-sm text-sage-muted">Cross-family material shortlist</span></div>
      <p className="text-sm text-sage-muted">Higher RPS → higher research priority · not a superconductivity probability</p>
    </header>
    <div role="note" className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-950">
      <strong className="font-semibold">Layout preview · synthetic data</strong><span>All values and rankings are synthetic, including those beside familiar formulas. Not scientific results.</span>
    </div>

    <section className="overflow-hidden rounded-xl border border-sage-border bg-white" aria-label="Material list layout preview">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-sage-border p-3">
        <div className="flex flex-wrap items-center gap-2">
          <label className="sr-only" htmlFor="demo-material-search">Search example materials</label>
          <input id="demo-material-search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search material or family…" className={`${selectStyle} w-56 max-w-full outline-none focus:ring-2 focus:ring-accent/30`} />
          <label className="sr-only" htmlFor="demo-family">Material family</label>
          <select id="demo-family" value={family} onChange={e => setFamily(e.target.value)} className={selectStyle}><option value="all">All chemical families</option>{families.map(item => <option key={item} value={item}>{item}</option>)}</select>
          <label className="sr-only" htmlFor="demo-profile">Research profile</label>
          <select id="demo-profile" value={profile} onChange={e => setProfile(e.target.value)} className={selectStyle}><option value="all">All profiles</option>{profiles.map(item => <option key={item} value={item}>{item}</option>)}</select>
          <span className="px-1 text-sm text-sage-muted">{rows.length} materials</span>
        </div>
        <div className="inline-flex rounded-md border border-sage-border p-0.5" role="group" aria-label="Table columns">{[["data", "Material data"], ["physics", "Physics scores"]].map(([key, label]) => <button key={key} aria-pressed={view === key} onClick={() => setView(key as "data" | "physics")} className={`rounded px-3 py-1.5 text-sm ${view === key ? "bg-sage-ink text-white" : "text-sage-muted hover:bg-sage-surface"}`}>{label}</button>)}</div>
      </div>

      {view === "data" && <div className="border-b border-sage-border bg-sage-surface/50 px-3 py-2.5">
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <label htmlFor="scientific-group" className="font-medium">Scientific fields</label>
          <select id="scientific-group" value={group} onChange={e => changeGroup(e.target.value as View)} className={selectStyle}><option value="overview">Cross-family overview</option>{FIELD_GROUPS.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select>
          <button aria-expanded={columnPicker} aria-controls="column-picker" onClick={() => setColumnPicker(!columnPicker)} className={selectStyle}>Columns {activeFields.length}/{groupFields.length}</button>
          <span className="text-sage-muted">{SCIENTIFIC_FIELDS.length} field definitions · Select a header for its definition or a value for its source</span>
        </div>
        <p className="mt-2 text-xs leading-5 text-sage-muted">{groupDefinition?.description ?? "Shared material–state–action context. Chemical families and mechanism profiles are separate; new fields do not automatically become scoring factors."}</p>
        {columnPicker && <div id="column-picker" className="mt-3 border-t border-sage-border pt-3">
          <div className="mb-2 flex gap-4 text-sm"><button className="text-accent underline" onClick={() => setVisibleKeys(groupFields.map(field => field.key))}>Show all in group</button><button className="text-accent underline" onClick={() => setVisibleKeys(groupFields.slice(0, 6).map(field => field.key))}>Reset compact columns</button></div>
          <div className="flex flex-wrap gap-x-5 gap-y-2">{groupFields.map(field => <label key={field.key} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={visibleKeys.includes(field.key)} disabled={visibleKeys.length === 1 && visibleKeys[0] === field.key} onChange={e => setVisibleKeys(e.target.checked ? groupFields.filter(f => visibleKeys.includes(f.key) || f.key === field.key).map(f => f.key) : visibleKeys.filter(key => key !== field.key))} />{field.label}</label>)}</div>
        </div>}
      </div>}

      <div className="max-h-[70vh] overflow-auto" tabIndex={0} aria-label="Scrollable material comparison">
        <table className="w-full min-w-[1250px] border-separate border-spacing-0 text-sm">
          <caption className="sr-only">Synthetic layout preview. Each material occupies one row with a selected state and action. Scores are not superconductivity probabilities.</caption>
          <thead className="sticky top-0 z-20 text-xs text-sage-muted">
            <tr>
              <th scope="colgroup" colSpan={3} className={`${header} text-left`}>MATERIAL · STATE · ACTION</th>
              <th scope="colgroup" colSpan={view === "data" ? activeFields.length : 6} className={`${header} border-x text-center`}>{view === "data" ? `${groupDefinition?.label ?? "Cross-family overview"} · SYNTHETIC` : "PHYSICAL SUPPORT · 0–100"}</th>
              <th scope="colgroup" colSpan={3} className={`${header} text-center`}>PRIORITY COMPONENTS · 0–100</th>
              <th scope="col" rowSpan={2} className="sticky right-0 z-30 min-w-[110px] border-b border-l border-sage-border bg-emerald-50 px-4 text-right text-emerald-900" aria-sort={descending ? "descending" : "ascending"}><button onClick={() => setDescending(value => !value)} className="whitespace-nowrap text-sm font-semibold">RPS {descending ? "↓" : "↑"}</button><span className="mt-1 block font-normal">1,000–10,000</span></th>
            </tr>
            <tr>
              <th scope="col" className={`${header} w-12`}>#</th>
              <th scope="col" className={`${header} sticky left-0 z-30 min-w-[190px] text-left`}>Material</th>
              <th scope="col" className={`${header} text-left`}>Chemical family</th>
              {view === "data" ? activeFields.map(field => <th scope="col" key={field.key} className={header}><button aria-controls="scientific-detail" onClick={e => inspect(null, field.key, e.currentTarget)} className="underline decoration-dotted underline-offset-4" title={field.definition}>{field.label}</button><span className="mt-1 block font-normal">{field.unit || (field.kind === "artifact" ? "artifact" : "context")}{field.featureRole === "post_outcome" ? " · post-outcome" : ""}</span></th>) : PHYSICAL_DIMENSIONS.map(([key, label]) => <th scope="col" key={key} className={header}>{label}</th>)}
              <th scope="col" className={header} title="P: physical support lower bound">Physical</th><th scope="col" className={header} title="G: decision gain from next action">Gain</th><th scope="col" className={header} title="A: execution readiness and affordability">Execution</th>
            </tr>
          </thead>
          <tbody>{rows.map(row => <tr key={row.id} className="group hover:bg-sage-surface/60">
            <td className={`${cell} text-sage-muted`}>{row.score === null ? "—" : 1 + DISCOVERY_DEMO_ROWS.filter(other => other.score !== null && other.score > row.score!).length}</td>
            <th scope="row" className="sticky left-0 z-10 whitespace-nowrap border-b border-sage-border/60 bg-white px-3 py-3 text-left font-normal group-hover:bg-sage-surface"><button aria-controls="scientific-detail" onClick={e => inspect(row, null, e.currentTarget)} className="font-semibold text-sage-ink hover:text-accent hover:underline" title={`${row.stateId} · ${row.action}`}>{row.formula}</button><span className="ml-2 rounded border border-amber-200 px-1 py-0.5 text-xs font-normal text-amber-800" title={`${row.id}: synthetic example`}>Demo</span></th>
            <td className="whitespace-nowrap border-b border-sage-border/60 px-3 py-3 text-sage-muted">{row.family}</td>
            {view === "data" ? activeFields.map(field => {
              const value = valueFor(row, field.key);
              const missing = value.availability !== "known";
              return <td key={field.key} className={`${cell} ${missing ? value.availability === "conflicted" || value.availability === "failed" ? "text-amber-800" : "text-sage-muted" : "text-sage-ink"}`}><button aria-controls="scientific-detail" onClick={e => inspect(row, field.key, e.currentTarget)} aria-label={`${row.formula} · ${field.label} · ${formatScientificValue(value)}`} className="max-w-[230px] truncate align-middle hover:underline" title={missing ? value.reason : `${value.provenance.normalization ?? ""} · ${value.provenance.locator}`}>{formatScientificValue(value)}</button>{value.availability === "known" && value.kind === "number" && value.provenance.normalization && <span className="ml-1 text-xs text-sage-muted" title={value.provenance.normalization}>ⓘ</span>}</td>;
            }) : row.dimensions.map((value, index) => <td key={index} className={cell} title={value === null ? "Unknown — not zero" : "Synthetic physical-support anchor"}>{value === null ? "Unknown" : format(value)}</td>)}
            <ScoreCell value={row.physical} label="Physical support" /><ScoreCell value={row.gain} label="Decision gain" /><ScoreCell value={row.execution} label="Executability" />
            <td className={`${cell} sticky right-0 z-10 border-l border-sage-border/60 bg-emerald-50 text-lg font-semibold tracking-tight text-emerald-950`} title={row.score === null ? "No supported decision gain: unranked" : "Synthetic research priority, not a probability"}>{format(row.score)}</td>
          </tr>)}</tbody>
        </table>
      </div>
      {rows.length === 0 && <p role="status" className="p-8 text-center text-sm text-sage-muted">No matching example materials.</p>}
      <footer className="flex flex-wrap justify-between gap-2 px-4 py-3 text-xs leading-5 text-sage-muted"><p>Unknown ≠ not reported ≠ not computed ≠ not applicable · Conflicts and failures stay separate · RPS — means unranked</p><p>RPS = 1,000 + 45 × Physical + 27 × Gain + 18 × Execution</p></footer>
    </section>

    {(selected || detailField) && <aside id="scientific-detail" ref={detailRef} tabIndex={-1} className="rounded-lg border border-sage-border bg-white p-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent" aria-label="Example material detail">
      <div className="flex items-center justify-between gap-4"><h2 className="font-semibold">{selected ? `${selected.formula} · ${selected.id}` : "Field definition"}{detailField ? ` / ${detailField.label}` : ""}</h2><button onClick={() => inspect(null, null)} className="rounded border border-sage-border px-3 py-1 text-sm">Close</button></div>
      {selected && <><p className="mt-2 text-sm">Next action: {selected.action}. State pressure: {selected.pressure === null ? "unknown" : `${format(selected.pressure, 1)} GPa`}.</p><p className="mt-1 break-all text-xs text-sage-muted">{selected.stateId} · {selected.actionId} · profiles: {selected.profiles.join(" + ") || "unresolved"}</p><p className="mt-1 text-sm text-amber-800">Synthetic example only. No research evidence, verified calculation, or published assessment.</p></>}
      {detailField && <div className="mt-3 space-y-2 text-sm leading-6"><p>{detailField.definition}</p><p className="text-sage-muted">{ROLE_LABELS[detailField.featureRole]} · {detailField.profiles.length ? `Relevant profiles: ${detailField.profiles.join(" + ")}` : "Shared cross-family interface"} · {detailField.tier}</p><p>{detailField.requiredContext}</p><p>{detailField.comparisonScope}</p><p className="text-amber-800">Direction: no universally favorable or adverse trend is assumed. Physical values and policy points are different objects.</p>{selected && <ValueDetail value={valueFor(selected, detailField.key)} />}</div>}
      {selected && !detailField && <dl className="mt-3 grid gap-2 md:grid-cols-2">{groupFields.map(field => <div key={field.key} className="border-t border-sage-border/50 py-2 text-sm"><dt><button className="text-accent underline" onClick={() => setSelectedField(field.key)}>{field.label}</button></dt><dd className="mt-1 text-sage-muted">{formatScientificValue(valueFor(selected, field.key))} {valueFor(selected, field.key).availability === "known" ? field.unit : ""}</dd></div>)}</dl>}
    </aside>}

    <DiscoveryFieldGuide />
    <details className="text-sm text-sage-muted"><summary className="w-fit cursor-pointer">Scoring notes &amp; preview limitations</summary><p className="mt-2 max-w-4xl leading-6">This is a frontend-only mockup with {DISCOVERY_DEMO_ROWS.length} unique materials. Scores use synthetic common-weight inputs, not validated family-specific assessments. Raw data are invented independently and are not used to infer physics scores. Selecting profiles, changing columns or adding unknown extension fields never changes the score. Each real row must retain a curator-selected state and next action; different states must not be merged by taking the highest score. No training export is provided by this preview.</p></details>
  </main>;
}
