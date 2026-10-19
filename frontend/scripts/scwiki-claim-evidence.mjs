// Claim commentary is distinct from material evidence used by search filters.
// Preserve the existing experimental spelling in stored claims; it is not a separate evidence strength.
export const claimEvidenceTypes = ["experiment", "experimental", "theory", "prediction", "hypothesis", "editorial-analysis"];

export function validateClaimEvidence(claim) {
  if (!claimEvidenceTypes.includes(claim.evidenceType)) throw new Error("Unknown claim evidence type: " + claim.id);
  if (claim.evidenceType === "editorial-analysis" &&
      (claim.sourceRelationship !== "context-for-editorial-analysis" ||
       typeof claim.derivationNote !== "string" || !claim.derivationNote.trim())) {
    throw new Error("Editorial claim requires an explicit source role and explanation: " + claim.id);
  }
}
