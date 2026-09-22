import type { MatchingScientificResult } from "@/lib/api";
import { pressureLabel } from "@/lib/pressure-semantics";
import { resultOrigin, scientificNumber } from "@/lib/result-semantics";
import { MaterialVisibilityNotice } from "@/components/MaterialVisibilityNotice";
import { visibilityIsRestricted } from "@/lib/material-visibility";

export function ScientificMatches({ results, scope = "source occurrence" }: { results?: MatchingScientificResult[]; scope?: "material" | "source occurrence" }) {
  results = results?.filter(result => !visibilityIsRestricted(result.visibility));
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
            <MaterialVisibilityNotice visibility={r.visibility} compact scope={scope} />
          </li>
        ))}
      </ul>
      {results.length > 3 && <span>More matching records are included in the API response.</span>}
    </div>
  );
}
