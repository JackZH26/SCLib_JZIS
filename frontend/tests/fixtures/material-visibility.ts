/** Synthetic policy fixtures, never scientific review decisions. */
import type { MaterialVisibility, SourceOccurrenceVisibility, SourceVisibility } from "@/lib/api";

export function materialVisibility(state: MaterialVisibility["state"] = "catalogue"): MaterialVisibility {
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

export function occurrenceVisibility(state: MaterialVisibility["state"] = "unknown"): SourceOccurrenceVisibility {
  return { ...materialVisibility(state), material_link_status: "unlinked", public_catalogue_eligible: false, reported_claim_filter_eligible: state === "unknown", review_revision: null };
}

export function sourceVisibility(status: SourceVisibility["source_status"] = "active"): SourceVisibility {
  return { version: "material-visibility/1.0.0", source_status: status, bibliography_available: true, reported_claim_filter_eligible: status === "active" || status === "unknown", scientific_acceptance: false, warning_codes: status === "active" ? [] : [`source_${status}`] };
}
