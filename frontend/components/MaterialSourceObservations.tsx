"use client";

import { useId, useState } from "react";
import {
  downloadSourceObservationWindow, groupSourceObservations, observationLabel, observationValue,
  sourceObservationUrl,
  type SourceObservation, type SourceObservationWindow,
} from "@/lib/material-source-observations";

const record = (value: unknown): Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
const text = (value: unknown): string | null => typeof value === "string" && value.length > 0 ? value : typeof value === "number" && Number.isFinite(value) ? String(value) : null;
const roles: Record<string, string> = {
  source_curve_derived_slope: "Slope derived from a source curve",
  source_reported_model_estimate: "Source-reported model estimate",
  curve_definition: "Definition of this source curve",
  source_condition_expression: "Source condition expression",
  source_reported_fit: "Source-reported fit parameter",
  source_reported_fit_table: "Source-reported table fit parameter",
  listed_CIF_source_metadata: "Listed CIF reference metadata",
};
const rawQuantity = (value: unknown): string => {
  const quantity = record(value), raw = text(quantity.raw_value) ?? text(quantity.value);
  if (!raw) return "Not supplied";
  const unit = text(quantity.raw_unit) ?? text(quantity.unit);
  return `${quantity.approximate === true ? "≈ " : ""}${raw}${unit && !["dimensionless", "fractional", "1"].includes(unit) ? ` ${unit}` : ""}`;
};
const rowLabel = (value: unknown): string | null => text(value)?.replaceAll("\\lambda", "λ").replaceAll("\\Delta_{1}", "Δ₁").replaceAll("T_{\\mathrm{C}}", "Tc") ?? null;

function conditions(entry: SourceObservation): [string, string][] {
  const window = record(entry.source_window), entries: [string, string][] = [];
  const add = (label: string, value: unknown) => { const display = text(value); if (display) entries.push([label, display]); };
  add("Field direction", window.magnetic_field_direction_raw);
  add("Hc2 curve criterion", window.curve_criterion_raw);
  add("Slope temperature window", window.slope_temperature_window_raw);
  add("Method scope", window.method_scope);
  if (window.pressure && typeof window.pressure === "object") entries.push(["Pressure column", rawQuantity(window.pressure)]);
  else if (text(window.pressure_expression_raw)) entries.push(["Pressure wording", `${text(window.pressure_expression_raw)}; numeric pressure not supplied`]);
  else entries.push(["Pressure", "Not supplied in this source window"]);
  if (typeof window.model_temperature_k === "number") entries.push(["Model temperature", `${window.model_temperature_k} K · extrapolated`]);
  add("Model", window.model_label);
  if (window.measurement_temperature_k === null || window.temperature_k === null) entries.push(["Measurement temperature", "Not supplied in this source window"]);
  if (rowLabel(window.raw_row_label)) entries.push(["Source row", rowLabel(window.raw_row_label)!]);
  if (!window.pressure && text(window.raw_column_header)) entries.push(["Source column", `${text(window.raw_column_header)} GPa`]);
  return entries;
}
const conditionKey = ([label, value]: [string, string]) => `${label}\u0000${value}`;
function sharedConditions(entries: SourceObservation[]): [string, string][] {
  return conditions(entries[0]).filter(condition => entries.every(entry => conditions(entry).some(value => conditionKey(value) === conditionKey(condition))));
}
function ConditionList({ entries }: { entries: [string, string][] }) {
  return entries.length ? <dl className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs leading-5 text-sage-muted">{entries.map(([label, value]) => <div key={label}><dt className="inline font-medium">{label}: </dt><dd className="inline">{value}</dd></div>)}</dl> : null;
}
function sourceHref(entry: SourceObservation): string | null {
  const source = record(entry.source), href = sourceObservationUrl(source.source_url);
  if (!href) return null;
  try {
    const url = new URL(href);
    const xpath = text(record(source.locator).xml_xpath), id = xpath?.match(/^\/\/\*\[@id='([^']+)'\]$/)?.[1];
    if (id) url.hash = id;
    return url.href;
  } catch { return null; }
}
function locator(entry: SourceObservation): string {
  const source = record(entry.source), anchor = record(entry.field_locator), parts: string[] = [];
  const xpath = text(record(source.locator).xml_xpath), element = xpath?.match(/^\/\/\*\[@id='([^']+)'\]$/)?.[1];
  if (element) parts.push(`HTML element ${element}`);
  if (typeof anchor.char_start === "number" && typeof anchor.char_end === "number") parts.push(`Captured characters ${anchor.char_start}–${anchor.char_end}`);
  if (typeof anchor.line_start === "number" && typeof anchor.line_end === "number") parts.push(`CIF lines ${anchor.line_start}–${anchor.line_end}`);
  if (typeof anchor.table_column === "number") parts.push(`Table column ${anchor.table_column}`);
  if (Array.isArray(anchor.spans)) parts.push(`${anchor.spans.length} captured condition spans`);
  return parts.join(" · ") || "See downloaded metadata for the source locator";
}
function groupScope(entry: SourceObservation): string {
  if (entry.field === "listed_atomic_sites" || record(entry.source).provider === "COD") return "Independent 1954 crystallographic reference. Listed sites and declared operations do not establish a validated coordinate model or a superconducting sample association.";
  if (record(entry.source_window).id === "ambient_prose_fit") return "Ambient prose fit for the source-defined Nb0.07-CVS alias. Its correspondence to the pressure-table dataset and catalogue sample remains unresolved.";
  if (record(entry.source_window).id === "pressure_series_table_zero_column") return "Zero-GPa column in the pressure-series fit table. Its values remain separate from the ambient prose fit; the λ(T>0) source row is preserved.";
  return "Nominal source composition BaFe1.90Pt0.10As2. Its relation to the refined catalogue sample remains pending; model estimates are separate from direct measurements.";
}
function GroupProvenance({ entry }: { entry: SourceObservation }) {
  const source = record(entry.source), href = sourceHref(entry);
  const hash = text(source.content_sha256) ?? text(source.file_sha256);
  return <details className="mt-3 text-xs leading-5 text-sage-muted">
    <summary className="w-fit cursor-pointer text-accent-deep">Source snapshot and association</summary>
    <dl className="mt-2 space-y-1">
      <div><dt className="inline font-medium">Captured source: </dt><dd className="inline">{text(source.paper_id) ?? (text(source.cod_id) ? `COD ${text(source.cod_id)}` : "Source identifier not supplied")}</dd></div>
      <div><dt className="inline font-medium">Version: </dt><dd className="inline">{text(source.source_revision) ?? (text(source.captured_revision) ? `CIF revision ${text(source.captured_revision)}` : "Not supplied")}. Current source status has not been checked{source.provider === "COD" ? "." : "; the requested paper revision remains unverified."}</dd></div>
      {hash && <div><dt className="inline font-medium">Captured content SHA-256: </dt><dd className="inline break-all font-mono">{hash}</dd></div>}
    </dl>
    <p className="mt-2">These are AI-assisted source-expression checks. They do not grant human review, scientific approval or a physical sample/state association.</p>
    {href && <a className="site-text-link mt-2 inline-block" href={href} target="_blank" rel="noopener noreferrer">Open original source locator</a>}
  </details>;
}
function StructuredValue({ entry }: { entry: SourceObservation }) {
  if (entry.field === "listed_atomic_sites" && Array.isArray(entry.value)) return <details className="mt-3 text-xs leading-5 text-sage-muted">
    <summary className="w-fit cursor-pointer text-accent-deep">Inspect the 2 listed sites</summary>
    <p className="mt-2">Listed fractional sites retain their source precision and occupancies. This asymmetric-unit list is not a count of all unit-cell atoms.</p>
    <div className="mt-2 overflow-x-auto" tabIndex={0} role="region" aria-label="Listed fractional sites">
      <table className="w-full text-left tabular-nums"><thead><tr>{["Site", "Element", "x", "y", "z", "Occupancy"].map(label => <th key={label} scope="col" className="whitespace-nowrap py-1 pr-4 font-medium">{label}</th>)}</tr></thead><tbody>{entry.value.map((value, index) => {
        const site = record(value), coords = Array.isArray(site.fractional_coordinates) ? site.fractional_coordinates : [];
        return <tr key={text(site.label) ?? index}><th scope="row" className="py-1 pr-4 font-medium">{text(site.label) ?? "Not supplied"}</th><td className="py-1 pr-4">{text(site.element) ?? "Not supplied"}</td>{[0, 1, 2].map(axis => <td key={axis} className="py-1 pr-4">{rawQuantity(coords[axis])}</td>)}<td className="py-1 pr-4">{rawQuantity(site.occupancy)}</td></tr>;
      })}</tbody></table>
    </div>
    <p className="mt-2">The B coordinates 0.3333 and 0.6667 remain as reported; exact thirds have not been substituted.</p>
  </details>;
  if (entry.field === "declared_symmetry_operations" && Array.isArray(entry.value)) return <details className="mt-3 text-xs leading-5 text-sage-muted">
    <summary className="w-fit cursor-pointer text-accent-deep">Inspect the 24 declared operations</summary>
    <p className="mt-2">Operations declared in the captured CIF; no independent space-group inference is asserted here.</p>
    <ol className="mt-2 grid list-inside list-decimal gap-x-6 gap-y-1 font-mono sm:grid-cols-2">{entry.value.filter((item): item is string => typeof item === "string").map((item, index) => <li className="break-words" key={`${index}-${item}`}>{item}</li>)}</ol>
  </details>;
  return null;
}
function Observation({ entry, shared }: { entry: SourceObservation; shared: [string, string][] }) {
  const value = record(entry.value), display = entry.field === "hc2_measurement_window" ? [text(value.field_direction_raw), text(value.temperature_raw)].filter(Boolean).join(" · ") : observationValue(entry);
  const sharedKeys = new Set(shared.map(conditionKey));
  const context = conditions(entry).filter(condition => !sharedKeys.has(conditionKey(condition))), anchor = record(entry.field_locator);
  return <li id={entry.id.replace(/[^a-zA-Z0-9_-]/g, "-")} className="scroll-mt-24 grid min-w-0 gap-2 py-4 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)] md:gap-8">
    <div><h4 className="text-sm font-medium">{observationLabel(entry.field)}</h4><p className="mt-1 text-xs leading-5 text-sage-muted">{roles[entry.source_role] ?? entry.source_role.replaceAll("_", " ")}</p></div>
    <div className="min-w-0">
      <p className="text-sm font-semibold tabular-nums">{display || "Source value not supplied"}</p>
      <ConditionList entries={context} />
      <StructuredValue entry={entry} />
      <p className="mt-2 text-xs leading-5 text-sage-muted">{locator(entry)}</p>
      <details className="mt-2 text-xs leading-5 text-sage-muted"><summary className="w-fit cursor-pointer text-accent-deep">Observation identity and limits</summary>
        <dl className="mt-2 space-y-1"><div><dt className="inline font-medium">Source observation ID: </dt><dd className="inline break-all font-mono">{entry.id}</dd></div>{text(anchor.token_sha256) && <div><dt className="inline font-medium">Literal token SHA-256: </dt><dd className="inline break-all font-mono">{text(anchor.token_sha256)}</dd></div>}</dl>
        <ul className="mt-2 list-disc space-y-1 pl-4">{entry.limitations.map(limit => <li key={limit}>{limit}</li>)}</ul>
      </details>
    </div>
  </li>;
}
export function MaterialSourceObservations({ window, defaultExpanded = false }: { window: SourceObservationWindow | null; defaultExpanded?: boolean }) {
  const headingId = useId();
  const [failureKey, setFailureKey] = useState<string | null>(null);
  if (!window || window.entries.length === 0) return null;
  const groups = groupSourceObservations(window.entries);
  const key = `${window.view_context.material_id ?? "independent"}:${window.entries.map(entry => entry.id).join("|")}`;
  return <section className="min-w-0" aria-labelledby={headingId}>
    <details className="min-w-0 rounded-lg border border-sage-border bg-white p-4 sm:p-5" open={defaultExpanded || undefined}>
      <summary id={headingId} className="cursor-pointer text-sm font-semibold">Additional source observations ({window.entries.length})</summary>
      <div className="mt-4 space-y-5">
        <div className="space-y-2 text-xs leading-5 text-sage-muted">
          <p>{window.entries.length} field {window.entries.length === 1 ? "projection" : "projections"} across {groups.length} source {groups.length === 1 ? "window" : "windows"}. Source fits, estimates and crystal metadata remain separate from selected catalogue properties. A source window is a reading context, not a physical sample identity or a count of independent experiments.</p>
          <button type="button" className="site-text-link rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent-deep" onClick={() => {
            try { setFailureKey(downloadSourceObservationWindow(window) ? null : key); }
            catch { setFailureKey(key); }
          }}>Download this observation window (JSON)</button>
          {failureKey === key && <p role="status">Observation metadata download is unavailable for this window.</p>}
        </div>
        {groups.map(group => { const shared = sharedConditions(group.entries); return <section className="min-w-0 border-t border-sage-border pt-4" key={group.id} aria-labelledby={`${headingId}-${group.id}`}>
          <h3 id={`${headingId}-${group.id}`} className="text-base font-semibold">{group.label}</h3>
          <p className="mt-2 max-w-3xl text-xs leading-5 text-sage-muted">{groupScope(group.entries[0])}</p>
          <ConditionList entries={shared} />
          <GroupProvenance entry={group.entries[0]} />
          <ol className="mt-3 divide-y divide-sage-border">{group.entries.map(entry => <Observation key={entry.id} entry={entry} shared={shared} />)}</ol>
        </section>; })}
      </div>
    </details>
  </section>;
}
