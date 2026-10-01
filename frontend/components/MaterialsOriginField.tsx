"use client";
import { useState } from "react";

/** Preserve the legacy observed-only key without retaining it when another origin is chosen. */
export function MaterialsOriginField({ initial, observedOnly }: { initial?: string; observedOnly: boolean }) {
  const [origin, setOrigin] = useState(initial || (observedOnly ? "Observed" : ""));
  return <>
    <select id="materials-origin" name="knowledge_origin" value={origin} onChange={event => setOrigin(event.target.value)}>
      <option value="">Any origin</option>
      <option value="Observed">Observed</option>
      <option value="Computed">Computed</option>
      <option value="Inferred">Inferred</option>
      <option value="AI-Proposed">AI-Proposed</option>
      <option value="Unknown">Unknown</option>
    </select>
    {origin === "Observed" && <input type="hidden" name="experimental_only" value="true" />}
  </>;
}
