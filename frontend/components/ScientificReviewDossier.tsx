"use client";

import { reviewNumber, reviewQuantity, type ReviewDossier } from "@/lib/scientific-review";

const panel = "min-w-0 rounded-lg border border-sage-border bg-white p-4";
const label = (value: string) => value.replaceAll("_", " ");
function Field({ name, children }: { name: string; children: React.ReactNode }) {
  return <div className="min-w-0 py-1"><dt className="text-xs font-medium text-sage-muted">{name}</dt><dd className="break-words text-sm text-sage-ink">{children}</dd></div>;
}
function Hash({ value }: { value: string | null }) {
  return value === null ? <>Not available</> : <code className="break-all text-xs">{value}</code>;
}

export function ScientificReviewDossier({ value, idPrefix = "" }: { value: ReviewDossier; idPrefix?: string }) {
  const sectionId = (name: string) => idPrefix ? idPrefix + "-" + name : name;
  return <div className="min-w-0 space-y-4">
    <div className={panel}>
      <h3 className="font-semibold">Exact result · {value.material.formula}</h3>
      <dl className="mt-2 grid gap-x-4 sm:grid-cols-2">
        <Field name="Property ID">{value.target.property_id}</Field>
        <Field name="Parent event">{value.target.event_id} · revision {reviewNumber(value.target.event_revision)}</Field>
        <Field name="Captured descriptor SHA-256"><Hash value={value.descriptor_sha256} /></Field>
        <Field name="Dependency inventory SHA-256"><Hash value={value.inventory.sha256} /></Field>
      </dl>
      <p className="mt-2 text-xs text-sage-muted">These hashes identify the server-captured database snapshot. This browser has not independently verified original files. A hash is not scientific validation or persistent currentness.</p>
    </div>
    <div className="grid min-w-0 gap-4 xl:grid-cols-2">
      <section className={panel} aria-labelledby={sectionId("result-heading")}>
        <h4 id={sectionId("result-heading")} className="font-semibold">Typed result, state and run</h4>
        <dl className="mt-2">
          <Field name="Quantity">{label(value.result.property_key)}: {reviewQuantity(value.result)}</Field>
          <Field name="Reported relation">{label(value.result.relation)} — a stored quantity relation, not exact underlying physics</Field>
          <Field name="Registry / component">{value.result.registry_version} / {value.result.component_key}</Field>
          <Field name="Origin / event type">{value.event.knowledge_origin} / {label(value.event.event_type)}</Field>
          <Field name="Parent event status">Review: {label(value.event.review_status)}; validity: {label(value.event.validity_status)}. These are stored parent-event states, not a new property-level approval.</Field>
          <Field name="Material / state">{value.material.id} / {value.state.id}</Field>
          <Field name="State resolution">{label(value.state.resolution)}</Field>
          <Field name="Pressure">{value.state.pressure_gpa === null ? "Not reported / unresolved" : `${reviewNumber(value.state.pressure_gpa)} GPa`} · {label(value.state.pressure_status)}</Field>
          <Field name="Temperature">{value.state.temperature_k === null ? "Not reported / unresolved" : `${reviewNumber(value.state.temperature_k)} K`} · role: {label(value.state.temperature_role)}</Field>
          <Field name="Structure">{value.structure ? <>{label(value.structure.structure_kind)} · {value.structure.id}<br />Artifact: {value.structure.artifact_id ?? "Not available"}</> : "Not available"}</Field>
          <Field name="Producer run">{value.run ? <>{label(value.run.run_kind)} · {label(value.run.status)}<br />{value.run.id}</> : "Not available"}</Field>
        </dl>
        <p className="mt-3 text-xs text-sage-muted">Unknown conditions are not zero. An extraction run is not an attested upstream calculation. Formula agreement does not establish phase, sample or state identity.</p>
      </section>
      <section className={panel} aria-labelledby={sectionId("sources-heading")}>
        <h4 id={sectionId("sources-heading")} className="font-semibold">Source bindings and locators</h4>
        <p className="my-2 text-xs text-sage-muted">Retained dependency artifacts may include parent, sibling, state and run evidence. Membership does not establish support for this property. Raw source text, metadata payloads and file exports are withheld for every role. Access labels do not grant disclosure rights.</p>
        {value.sources.length === 0 && <p className="text-sm">No source-artifact bindings are included in this dependency inventory.</p>}
        <ul className="space-y-3">{value.sources.map(source => <li className="min-w-0 rounded border border-sage-border p-3" key={source.artifact_id}>
          <dl>
            <Field name="Artifact">{source.artifact_id}</Field>
            <Field name="Kind / access label">{label(source.kind)} / {label(source.access)}</Field>
            <Field name="Stored hash status">{label(source.hash_status)} — not a new browser file verification</Field>
            <Field name="Retained bytes SHA-256"><Hash value={source.bytes_sha256} /></Field>
          </dl>
          <p className="mt-2 text-xs font-medium">Locations only</p>
          <ul className="list-inside list-disc text-xs">{source.locators.map((locator, index) => <li key={index}>{"scope" in locator
            ? "Locator not disclosed" : `Line ${reviewNumber(locator.line)}; byte range ${reviewNumber(locator.start_byte)}–${reviewNumber(locator.end_byte)}`}</li>)}</ul>
          <details className="mt-2 text-xs"><summary className="cursor-pointer">Evidence-link identifiers ({source.evidence_link_ids.length})</summary>
            <ul>{source.evidence_link_ids.map(id => <li key={id} className="break-all font-mono">{id}</li>)}</ul>
          </details>
        </li>)}</ul>
      </section>
    </div>
    <section className={panel} aria-labelledby={sectionId("warnings-heading")}>
      <h4 id={sectionId("warnings-heading")} className="font-semibold">Inspection warnings</h4>
      {value.warnings.length ? <ul className="mt-2 list-inside list-disc text-sm">{value.warnings.map(warning => <li key={warning}>{label(warning)}</li>)}</ul>
        : <p className="mt-2 text-sm">No warning codes were returned. This is not a completeness or scientific-acceptance assessment.</p>}
    </section>
    <section className={panel} aria-labelledby={sectionId("impact-heading")}>
      <h4 id={sectionId("impact-heading")} className="font-semibold">Bounded dependency relationships</h4>
      <p className="my-2 text-sm">This is a database relationship inventory, not a prediction of scientific effects. This inspection does not approve, refresh, publish or change any records.</p>
      <dl>
        <Field name="Included scope">{value.impact.scope.map(label).join("; ") || "None declared"}</Field>
        <Field name="Unsupported scope">{value.impact.unsupported_scopes.map(label).join("; ") || "None declared; no global completeness is inferred"}</Field>
        <Field name="Captured inventory">{reviewNumber(value.inventory.row_count)} rows; {reviewNumber(value.inventory.artifact_count)} artifacts</Field>
        <Field name="Relationship counts">{Object.entries(value.impact.counts).map(([table, count]) => `${label(table)}: ${reviewNumber(count)}`).join("; ") || "No relationships reported"}</Field>
      </dl>
      <details className="mt-3"><summary className="cursor-pointer text-sm">Inspect {reviewNumber(value.impact.items.length)} declared relationship entries</summary>
        <ul className="mt-2 space-y-2 text-xs">{value.impact.items.map((item, index) => <li key={index} className="break-all rounded bg-sage-surface p-2">
          {item.table}: {item.row_id}<br />{label(item.relation)} via {item.via_table}: {item.via_id}
        </li>)}</ul>
      </details>
    </section>
  </div>;
}
