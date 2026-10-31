import { syntheticAmendments } from "./materials-amendment-test-data";
import type { Body } from "../../lib/materials-proposal-review";

export const syntheticResultAmendments = JSON.parse(JSON.stringify(syntheticAmendments)) as typeof syntheticAmendments;
const candidate = syntheticResultAmendments.cases[0], summary = candidate.amendments.listing.items[0];
const dto = candidate.amendments.details[summary.id], a = dto.amendment, result = a.graph.results[0];
result.quantity_kind = "penetration_depth";
(result.quantity as Body).unit = "nm";
result.dependencies = [];
a.validation = { normalized: {} };
a.source_review = { status: "pending_reassessment", parent_terminal_sha256: "7".repeat(64), findings_sha256: "8".repeat(64),
  findings_author: { kind: "assistant", identity: "Synthetic source reviewer", thread_id: "synthetic-source" }, findings_created_at: "2026-10-26T00:00:00Z",
  paper_completed: false, independent_review: false, findings: [
    { id: "state", kind: "entity", path: "/states/0", code: "synthetic_pending_review", note: "Synthetic state issue remains pending.", anchors: a.reviews[0].fields.quantity.anchors },
    { id: "omission", kind: "source_completeness", path: "/paper", code: "synthetic_omission", note: "Synthetic omitted source occurrence remains pending.", anchors: a.reviews[0].fields.quantity.anchors },
  ] };
dto.mapping.schema = "materials-reviewed-result-mapping/1";
Object.assign(dto.mapping.records[0], { target_table: null, result_pointer: "/graph/results/0", quantity_kind: result.quantity_kind,
  source_quantity: JSON.parse(JSON.stringify(result.quantity)), result_semantics: { version: "materials-result-semantics/1", definition: result.definition, qualifiers: result.qualifiers },
  dependencies: [], normalized: {}, validation_issues: ["state_has_validation_issues"], review_status: "quarantined",
  holds: ["canonical_result_mapping_required", "independent_scientific_review_required", "state_has_validation_issues"] });
