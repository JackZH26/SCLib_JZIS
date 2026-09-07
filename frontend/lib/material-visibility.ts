/** Server governance metadata is not scientific acceptance or a formula-based join. */
import type { MaterialRawArchive, MaterialVisibility, SourceOccurrenceVisibility, SourceVisibility } from "@/lib/api";
import { objectValue } from "@/lib/property-evidence";

export const MATERIAL_VISIBILITY_VERSION = "material-visibility/1.0.0";
const STATES = ["catalogue", "pending", "disputed", "corrected", "retracted", "quarantined", "unknown"];
const SOURCES = ["active", "retracted", "corrected", "mixed", "unknown"];

export function visibilityIsRestricted(value: unknown): boolean {
  const v = objectValue(value);
  return v.state === "quarantined" || v.archive_available === false;
}

export function knownVisibility(value: unknown): MaterialVisibility | null {
  const v = objectValue(value);
  if (v.version !== MATERIAL_VISIBILITY_VERSION || !STATES.includes(String(v.state)) ||
      !SOURCES.includes(String(v.source_status)) || v.scientific_acceptance !== false ||
      typeof v.public_catalogue_eligible !== "boolean" || typeof v.archive_available !== "boolean" ||
      typeof v.review_revision !== "string" || !v.review_revision.trim() || v.review_revision.length > 200 ||
      ![v.reason_codes, v.warning_codes].every(codes => Array.isArray(codes) && codes.length <= 100 && codes.every(code => typeof code === "string" && /^[a-zA-Z0-9_.:-]{1,120}$/.test(code)))) return null;
  // Contradictory metadata cannot promote a non-catalogue or restricted record.
  if ((v.state === "catalogue") !== v.public_catalogue_eligible ||
      (v.state === "quarantined" && v.archive_available)) return null;
  return {
    version: MATERIAL_VISIBILITY_VERSION, state: v.state as MaterialVisibility["state"],
    public_catalogue_eligible: v.public_catalogue_eligible, archive_available: v.archive_available,
    scientific_acceptance: false, reason_codes: [...v.reason_codes as string[]], warning_codes: [...v.warning_codes as string[]],
    review_revision: v.review_revision, source_status: v.source_status as MaterialVisibility["source_status"],
  };
}

export function knownOccurrenceVisibility(value: unknown): SourceOccurrenceVisibility | null {
  const v = objectValue(value);
  if (!["resolved", "unresolved", "unlinked"].includes(String(v.material_link_status)) ||
      typeof v.reported_claim_filter_eligible !== "boolean" ||
      !(v.review_revision === null || typeof v.review_revision === "string")) return null;
  // An unlinked occurrence has no material revision. This is not an approval token.
  const checked = knownVisibility({ ...v, review_revision: v.review_revision ?? "unlinked-occurrence", source_status: v.source_status === "disputed" ? "unknown" : v.source_status });
  return checked ? value as SourceOccurrenceVisibility : null;
}

export function knownSourceVisibility(value: unknown): SourceVisibility | null {
  const v = objectValue(value);
  return v.version === MATERIAL_VISIBILITY_VERSION &&
    ["active", "retracted", "corrected", "disputed", "unknown"].includes(String(v.source_status)) &&
    v.scientific_acceptance === false && typeof v.bibliography_available === "boolean" &&
    typeof v.reported_claim_filter_eligible === "boolean" ? value as SourceVisibility : null;
}

export function sourceVisibilityLabel(value: unknown): string {
  const v = knownSourceVisibility(value);
  if (!v || v.source_status === "unknown") return "Source status unknown — claims are unverified";
  if (v.source_status === "active") return "Active bibliographic source — not scientific approval";
  return `Source Archive — ${v.source_status}`;
}

export function eligibleForScientificSeo(value: unknown): boolean {
  const v = knownVisibility(value);
  return !!v && v.state === "catalogue" && v.public_catalogue_eligible &&
    v.archive_available && ["active", "unknown"].includes(v.source_status);
}

export function visibilityLabel(value: unknown, scope: "material" | "source occurrence" = "material"): string {
  const v = scope === "source occurrence" ? knownOccurrenceVisibility(value) : knownVisibility(value);
  if (!v) return "Archive — visibility unverified";
  const labels: Record<MaterialVisibility["state"], string> = {
    catalogue: "Catalogue eligible — not scientific approval",
    pending: "Archive — review pending",
    disputed: "Archive — disputed claim",
    corrected: "Archive — correction requires review",
    retracted: "Archive — retracted source or claim",
    quarantined: "Restricted — unavailable",
    unknown: "Archive — visibility unverified",
  };
  return labels[v.state];
}

export function visibilityWarning(value: unknown, scope: "material" | "source occurrence" = "material"): string {
  const v = scope === "source occurrence" ? knownOccurrenceVisibility(value) : knownVisibility(value);
  if (!v) return "Current visibility metadata is unavailable. Do not interpret this record as approved science or a training label.";
  if (v.state === "unknown") return "The current read policy could not establish catalogue eligibility. Do not interpret this record as approved science or a training label.";
  if (v.state === "catalogue") return "Catalogue eligibility is a read-policy decision, not experimental confirmation or permission to use every property for ML.";
  if (v.state === "quarantined") return "This record is not available through public catalogue or Archive views.";
  return "Retained for source inspection only. This record is excluded from the default catalogue and must not be treated as an accepted superconductivity result or ML label.";
}

/** Export the authorized response with governance attached, never a bare raw claim. */
export function archiveExport(archive: MaterialRawArchive, visibility?: MaterialVisibility) {
  const v = knownVisibility(visibility ?? archive.visibility);
  return {
    export_scope: "authorized_retained_scientific_records",
    visibility: v,
    visibility_label: visibilityLabel(v),
    visibility_warning: visibilityWarning(v),
    scientific_acceptance: false,
    archive: { ...archive, visibility: v },
  };
}
