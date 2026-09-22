/** Server governance metadata is not scientific acceptance or a formula-based join. */
import type { MaterialRawArchive, MaterialSourceScope, MaterialVisibility, MaterialVisibilityV1, SourceOccurrenceVisibility, SourceVisibility } from "@/lib/api";
import { objectValue } from "@/lib/property-evidence";

export const MATERIAL_VISIBILITY_VERSION = "material-visibility/1.0.0";
export const SOURCE_SCOPED_VISIBILITY_VERSION = "material-visibility/2.0.0";
export const MATERIAL_SOURCE_SCOPE_VERSION = "material-source-scope/1.0.0";
const STATES = ["catalogue", "pending", "disputed", "corrected", "retracted", "quarantined", "unknown"];
const SOURCES = ["active", "retracted", "corrected", "mixed", "unknown"];
const VISIBILITY_KEYS = ["version", "state", "public_catalogue_eligible", "archive_available", "scientific_acceptance",
  "reason_codes", "warning_codes", "review_revision", "source_status"];
// Version-owned public copy, mirrored from the closed server policy. Private
// prose is not accepted merely because it arrived in a messages array.
const SOURCE_SCOPED_WARNINGS: Record<string, string> = {
  catalogue_is_not_scientific_acceptance: "Catalogue eligibility does not establish scientific acceptance or ML-training eligibility.",
  source_status_unknown: "Current source status is unknown; active publication status has not been established.",
  source_status_incomplete: "Current status is unknown for one or more linked sources.",
  legacy_status_unspecified: "The legacy material status is unspecified; no approval is inferred.",
  archive_only: "Archive material is retained for traceability and is excluded from the default public catalogue.",
  parent_review_hold: "This material inherits a visibility hold from its parent.",
  archive_access_unresolved: "Public Archive access is unavailable until provenance restrictions can be resolved.",
  source_scoped_reported_records_only: "Only eligible reported records from explicitly active sources are displayed; this is not scientific acceptance.",
  excluded_records_retained_in_archive: "Other retained records do not contribute to the current selection and remain subject to Archive access rules.",
};

function knownSourceScope(value: unknown): MaterialSourceScope | null {
  const v = objectValue(value);
  const keys = ["version", "status", "total_records", "eligible_records", "excluded_records", "eligible_source_count", "fingerprint", "independent_support_count"];
  if (Object.keys(v).length !== keys.length || !keys.every(key => Object.hasOwn(v, key)) ||
      v.version !== MATERIAL_SOURCE_SCOPE_VERSION || v.status !== "eligible_records_only" ||
      ![v.total_records, v.eligible_records, v.excluded_records, v.eligible_source_count].every(n => typeof n === "number" && Number.isSafeInteger(n) && n > 0 && n <= 5000) ||
      v.total_records !== (v.eligible_records as number) + (v.excluded_records as number) ||
      (v.eligible_source_count as number) > (v.eligible_records as number) ||
      typeof v.fingerprint !== "string" || !/^[0-9a-f]{64}$/.test(v.fingerprint) || v.independent_support_count !== null) return null;
  return { version: MATERIAL_SOURCE_SCOPE_VERSION, status: "eligible_records_only",
    total_records: v.total_records as number, eligible_records: v.eligible_records as number,
    excluded_records: v.excluded_records as number, eligible_source_count: v.eligible_source_count as number,
    fingerprint: v.fingerprint, independent_support_count: null };
}

export function visibilityIsRestricted(value: unknown): boolean {
  const v = objectValue(value);
  return v.state === "quarantined" || v.archive_available === false;
}

export function knownVisibility(value: unknown): MaterialVisibility | null {
  const v = objectValue(value);
  if ((v.version !== MATERIAL_VISIBILITY_VERSION && v.version !== SOURCE_SCOPED_VISIBILITY_VERSION) || !STATES.includes(String(v.state)) ||
      !SOURCES.includes(String(v.source_status)) || v.scientific_acceptance !== false ||
      typeof v.public_catalogue_eligible !== "boolean" || typeof v.archive_available !== "boolean" ||
      typeof v.review_revision !== "string" || !v.review_revision.trim() || v.review_revision.length > 200 ||
      ![v.reason_codes, v.warning_codes].every(codes => Array.isArray(codes) && codes.length <= 100 && codes.every(code => typeof code === "string" && /^[a-zA-Z0-9_.:-]{1,120}$/.test(code)))) return null;
  // Contradictory metadata cannot promote a non-catalogue or restricted record.
  if ((v.state === "catalogue") !== v.public_catalogue_eligible ||
      (v.state === "quarantined" && v.archive_available)) return null;
  const legacy: MaterialVisibilityV1 = {
    version: MATERIAL_VISIBILITY_VERSION, state: v.state as MaterialVisibility["state"],
    public_catalogue_eligible: v.public_catalogue_eligible, archive_available: v.archive_available,
    scientific_acceptance: false, reason_codes: [...v.reason_codes as string[]], warning_codes: [...v.warning_codes as string[]],
    review_revision: v.review_revision, source_status: v.source_status as MaterialVisibility["source_status"],
  };
  if (v.version === MATERIAL_VISIBILITY_VERSION) return legacy;
  // V1 remains unchanged. V2 requires the complete closed server shape and
  // exact code/message correspondence; it never forwards arbitrary prose.
  const allowed = [...VISIBILITY_KEYS, "reason_messages", "warning_messages", "source_scope"];
  if (Object.keys(v).length !== allowed.length || !allowed.every(key => Object.hasOwn(v, key)) ||
      v.state !== "catalogue" || typeof v.source_status !== "string" || v.archive_available !== true || v.public_catalogue_eligible !== true ||
      (v.reason_codes as string[]).length !== 0 || !(v.warning_codes as string[]).includes("catalogue_is_not_scientific_acceptance") ||
      !(v.warning_codes as string[]).includes("source_scoped_reported_records_only") ||
      !(v.warning_codes as string[]).includes("excluded_records_retained_in_archive") ||
      new Set(v.warning_codes as string[]).size !== (v.warning_codes as string[]).length ||
      !/^[0-9a-f]{64}$/.test(v.review_revision) ||
      !Array.isArray(v.reason_messages) || v.reason_messages.length !== 0 ||
      !Array.isArray(v.warning_messages) || v.warning_messages.length !== (v.warning_codes as string[]).length ||
      (v.warning_codes as string[]).some((code, index, codes) => !Object.hasOwn(SOURCE_SCOPED_WARNINGS, code) ||
        code !== [...codes].sort()[index] || (v.warning_messages as unknown[])[index] !== SOURCE_SCOPED_WARNINGS[code])) return null;
  const sourceScope = knownSourceScope(v.source_scope);
  return sourceScope ? { ...legacy, version: SOURCE_SCOPED_VISIBILITY_VERSION, state: "catalogue",
    public_catalogue_eligible: true, archive_available: true, reason_codes: [], reason_messages: [],
    warning_messages: [...v.warning_messages as string[]], source_scope: sourceScope } : null;
}

export function knownOccurrenceVisibility(value: unknown): SourceOccurrenceVisibility | null {
  const v = objectValue(value);
  if (v.version !== MATERIAL_VISIBILITY_VERSION || !["resolved", "unresolved", "unlinked"].includes(String(v.material_link_status)) ||
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
  return !!v && v.version === MATERIAL_VISIBILITY_VERSION && v.state === "catalogue" && v.public_catalogue_eligible &&
    v.archive_available && ["active", "unknown"].includes(v.source_status);
}

export function visibilityLabel(value: unknown, scope: "material" | "source occurrence" = "material"): string {
  const v = scope === "source occurrence" ? knownOccurrenceVisibility(value) : knownVisibility(value);
  if (!v) return "Archive — visibility unverified";
  if (v.version === SOURCE_SCOPED_VISIBILITY_VERSION) return "Catalogue — eligible source records only";
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
  if (v.version === SOURCE_SCOPED_VISIBILITY_VERSION) return "Only eligible reported source records contribute to this catalogue view. Excluded records remain in the Archive. This is not scientific approval or evidence of independent replication.";
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
