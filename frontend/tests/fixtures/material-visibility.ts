/** Synthetic policy fixtures, never scientific review decisions. */
import type { MaterialVisibility, MaterialVisibilityV1, MaterialVisibilityV2, SourceOccurrenceVisibility, SourceVisibility } from "@/lib/api";

export function materialVisibility(state: MaterialVisibility["state"] = "catalogue"): MaterialVisibilityV1 {
  return {
    version: "material-visibility/1.0.0", state,
    public_catalogue_eligible: state === "catalogue", archive_available: state !== "quarantined",
    scientific_acceptance: false,
    reason_codes: state === "catalogue" ? [] : [`material_${state}`],
    warning_codes: ["catalogue_is_not_scientific_acceptance"],
    review_revision: "synthetic-review-revision",
    source_status: state === "retracted" || state === "corrected" ? state : "active",
  };
}

export function sourceScopedMaterialVisibility(): MaterialVisibilityV2 {
  return { ...materialVisibility(), version: "material-visibility/2.0.0", state: "catalogue",
    public_catalogue_eligible: true, archive_available: true, source_status: "mixed",
    reason_codes: [], reason_messages: [], review_revision: "b".repeat(64),
    warning_codes: ["catalogue_is_not_scientific_acceptance", "excluded_records_retained_in_archive", "source_scoped_reported_records_only"],
    warning_messages: ["Catalogue eligibility does not establish scientific acceptance or ML-training eligibility.",
      "Other retained records do not contribute to the current selection and remain subject to Archive access rules.",
      "Only eligible reported records from explicitly active sources are displayed; this is not scientific acceptance."],
    source_scope: { version: "material-source-scope/1.0.0", status: "eligible_records_only",
      total_records: 3, eligible_records: 2, excluded_records: 1, eligible_source_count: 1,
      fingerprint: "a".repeat(64), independent_support_count: null } };
}

export function occurrenceVisibility(state: MaterialVisibility["state"] = "unknown"): SourceOccurrenceVisibility {
  return { ...materialVisibility(state), material_link_status: "unlinked", public_catalogue_eligible: false, reported_claim_filter_eligible: state === "unknown", review_revision: null };
}

export function sourceVisibility(status: SourceVisibility["source_status"] = "active"): SourceVisibility {
  return { version: "material-visibility/1.0.0", source_status: status, bibliography_available: true, reported_claim_filter_eligible: status === "active" || status === "unknown", scientific_acceptance: false, warning_codes: status === "active" ? [] : [`source_${status}`] };
}
