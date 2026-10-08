// Display-only paraphrases. This module is never an evidence or ranking input.
import companion from "./resources/discovery-readable-evidence-2026-10-09.json";
import type { DiscoveryEvidenceCard } from "./discovery-evidence-policy";
import type { SourceHypothesis, SourceHypothesisBrowseCandidate } from "./discovery-source-hypotheses";

export const readableEvidenceVersion = "2026-10-09-readable-evidence-v1";
export const readableFieldLabels = {
  "prior.case_context": "Prior work and novelty boundary",
  "bottleneck.summary": "Decision bottleneck",
  "bottleneck.ambient_scope": "Ambient-pressure scope",
  "proposed_contribution.intervention": "Proposed contribution",
  "proposed_contribution.next_action": "Next action",
} as const;
export type ReadableEvidenceField = keyof typeof readableFieldLabels;
export type ReadableEvidenceCopy = Partial<Record<ReadableEvidenceField, { text: string; original: string }>>;
type Entry = {
  id: string; formula: string; source_state: string; field: ReadableEvidenceField;
  dossier_sha256: string; source_detail_sha256: string; original_text_sha256: string; text: string;
};
type Companion = { schema_version: string; version: string; source_catalogue_sha256: string; entries: Entry[] };
const sourceHash = "4a9089bc569f99ad7f5f469280814fb22bfcc86252b1fb7c1e1be446f8bcac98";
const hashPattern = /^[a-f0-9]{64}$/;
const closed = (value: unknown, keys: readonly string[]) => value !== null && typeof value === "object"
  && !Array.isArray(value) && Object.keys(value).sort().join("|") === [...keys].sort().join("|");
const entryKeys = ["id", "formula", "source_state", "field", "dossier_sha256", "source_detail_sha256", "original_text_sha256", "text"];

function originals(field: ReadableEvidenceField, detail: SourceHypothesis, card: DiscoveryEvidenceCard): [string, string] {
  switch (field) {
    case "prior.case_context": return [card.prior.case_context, detail.seven_criteria.novelty];
    case "bottleneck.summary": return [card.bottleneck.summary, detail.risk_summary];
    // The visible ambient scope comes from the original detail, not the dossier.
    case "bottleneck.ambient_scope": return [card.bottleneck.ambient_scope, detail.ambient_scope];
    case "proposed_contribution.intervention": return [card.proposed_contribution.intervention, detail.route_response];
    case "proposed_contribution.next_action": return [card.proposed_contribution.next_action, detail.next_action];
  }
}

/** Call only after both existing byte/hash verifiers succeed. Invalid or stale copy leaves all original notes visible. */
export async function readReadableEvidence(candidate: SourceHypothesisBrowseCandidate, detail: SourceHypothesis,
  card: DiscoveryEvidenceCard, raw: unknown = companion): Promise<ReadableEvidenceCopy> {
  try {
    if (!closed(raw, ["schema_version", "version", "source_catalogue_sha256", "entries"])) return {};
    const data = raw as Companion;
    if (data.schema_version !== "discovery-readable-evidence/1.0.0" || data.version !== readableEvidenceVersion
      || data.source_catalogue_sha256 !== sourceHash || !Array.isArray(data.entries) || data.entries.length > 128) return {};
    if (card.id !== candidate.id || detail.id !== candidate.id || card.source_state !== candidate.source_state
      || detail.source_state !== candidate.source_state || card.formula !== candidate.formula || detail.formula !== candidate.formula
      || detail.control_state !== candidate.control_state || card.proposed_contribution.target_state !== candidate.source_state
      || card.proposed_contribution.selected_control !== candidate.control_state
      || card.source_catalogue_sha256 !== sourceHash || card.source_detail_sha256 !== candidate.detail.sha256) return {};
    const matches = data.entries.filter(entry => entry?.id === candidate.id || entry?.source_state === candidate.source_state);
    const result: ReadableEvidenceCopy = {};
    for (const entry of matches) {
      if (!closed(entry, entryKeys) || entry.id !== candidate.id || entry.source_state !== candidate.source_state
        || entry.formula !== candidate.formula || entry.dossier_sha256 !== candidate.research_evidence.detail.sha256
        || entry.source_detail_sha256 !== candidate.detail.sha256 || !hashPattern.test(entry.dossier_sha256)
        || !hashPattern.test(entry.source_detail_sha256) || !hashPattern.test(entry.original_text_sha256)
        || !Object.hasOwn(readableFieldLabels, entry.field) || Object.hasOwn(result, entry.field)
        || typeof entry.text !== "string" || entry.text.trim() !== entry.text || !entry.text.length || entry.text.length > 1600
        || /[\u3400-\u9fff]|(?:\/Users\/|\/home\/|\/opt\/|jack@|password|api_key|private_key)/i.test(entry.text)) return {};
      const [cardOriginal, detailOriginal] = originals(entry.field, detail, card);
      if (typeof cardOriginal !== "string" || cardOriginal !== detailOriginal) return {};
      const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(cardOriginal));
      const hash = Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, "0")).join("");
      if (hash !== entry.original_text_sha256) return {};
      result[entry.field] = { text: entry.text, original: cardOriginal };
    }
    return result;
  } catch { return {}; }
}
