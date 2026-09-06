"use client";

import { useState } from "react";
import { DISCOVERY_FIELD_SCHEMA, FIELD_GROUPS, ROLE_LABELS, SCIENTIFIC_FIELDS } from "@/lib/discovery-field-registry";

/** Definitions only: never import demonstration values here. */
export function DiscoveryFieldGuide() {
  const [query, setQuery] = useState("");
  const fields = SCIENTIFIC_FIELDS.filter(field => `${field.key} ${field.label} ${field.definition} ${field.profiles.join(" ")} ${ROLE_LABELS[field.featureRole]}`.toLowerCase().includes(query.trim().toLowerCase()));
  return <details className="rounded-lg border border-sage-border bg-white p-4 text-sm">
    <summary className="cursor-pointer font-medium">Scientific field dictionary · {SCIENTIFIC_FIELDS.length} fields / {FIELD_GROUPS.length} groups</summary>
    <p className="mt-3 leading-6 text-sage-muted">{DISCOVERY_FIELD_SCHEMA} · Shared cross-family definitions and overlapping profiles. This draft display contract does not imply that all results are available. Changing columns does not change RPS; no universal monotonic scoring direction is assumed.</p>
    <label className="mt-3 block">Find a field<input value={query} onChange={e => setQuery(e.target.value)} placeholder="U/W, twist, oxygen, post-outcome…" className="ml-3 w-72 max-w-full rounded border border-sage-border px-3 py-2" /></label>
    <p className="mt-2 text-xs text-sage-muted">Conditional candidate inputs still require time, budget, provenance and leakage checks before use in training.</p>
    <div tabIndex={0} role="region" aria-label="Scrollable scientific field dictionary" className="mt-3 max-h-[60vh] space-y-5 overflow-auto pr-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">{FIELD_GROUPS.map(group => {
      const entries = fields.filter(field => field.group === group.id);
      if (!entries.length) return null;
      return <section key={group.id} aria-label={`${group.label} field definitions`}><h3 className="border-b border-sage-border pb-2 font-semibold">{group.label} · {entries.length}</h3>
        <dl className="divide-y divide-sage-border/50">{entries.map(field => <div key={field.key} className="py-3">
          <dt className="font-medium">{field.label} {field.unit && `[${field.unit}]`} <code className="ml-2 break-all text-xs font-normal text-sage-muted">{field.key}</code></dt>
          <dd className="mt-1 leading-6">{field.definition}</dd>
          <dd className="mt-1 text-xs leading-5 text-sage-muted">{field.tier === "core" ? "Core definition" : "Research extension · not required for every record"} · {ROLE_LABELS[field.featureRole]} · {field.profiles.length ? `Relevant profiles: ${field.profiles.join(" + ")}` : "Shared interface"}. Profiles do not exclude applicability.</dd>
          <dd className="mt-1 text-xs leading-5 text-sage-muted">{field.requiredContext} {field.requiresNormalization ? "Normalization must be specified." : ""} {field.comparisonScope}</dd>
        </div>)}</dl></section>;
    })}{fields.length === 0 && <p role="status">No matching fields.</p>}</div>
  </details>;
}
