import type { MatchingScientificResult } from "@/lib/api";
import { pressureLabel } from "@/lib/pressure-semantics";
import { resultOrigin, scientificNumber } from "@/lib/result-semantics";

export function ScientificMatches({ results }: { results?: MatchingScientificResult[] }) {
  if (!results?.length) return null;
  return (
    <div className="mt-2 text-xs font-normal text-slate-500">
      <span className="font-medium">Matching result evidence ({results.length})</span>
      <ul className="mt-1 space-y-1">
        {results.slice(0, 3).map((r) => (
          <li key={`${r.result_id}:${r.record_index}`} title={`${r.result_id} · ${r.filter_policy_version}`}>
            {r.formula ? `${r.formula} · ` : ""}
            {r.tc_lower_bound_k != null ? `Tc lower bound ${scientificNumber(r.tc_lower_bound_k)} K · ` : ""}
            {pressureLabel(r.pressure_semantics)} · {resultOrigin(r.result_classification.knowledge_origin)}
          </li>
        ))}
      </ul>
      {results.length > 3 && <span>More matching records are included in the API response.</span>}
    </div>
  );
}
