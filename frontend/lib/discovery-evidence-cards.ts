// Server-only hash-bound companion loader. Source data and details remain immutable.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { evidenceVersion, rubricVersion } from "./discovery-evidence-policy";
import type { CounterEvidence, ResearchEvidenceSummary } from "./discovery-evidence-policy";
const frozenHash = "4a9089bc569f99ad7f5f469280814fb22bfcc86252b1fb7c1e1be446f8bcac98";
type Entry = { id: string; source_state: string; formula: string; source_detail_sha256: string;
  observations: { evidence_level: "E1"; source_pairing_quantified: true; geometry_causality_quantified: false;
    ambient_300K_direct_support: null; counterevidence: CounterEvidence[] }; detail: ResearchEvidenceSummary["detail"] };
function check(value: unknown): asserts value { if (!value) throw new Error("The Discovery evidence-card catalogue could not be verified."); }
export function loadDiscoveryEvidenceSummaries(sourceRows: readonly { id: string; source_state: string; formula: string }[], details: ReadonlyMap<string, { sha256: string }>) {
  const directory = join(process.cwd(), "public/research-hypotheses"), name = `${evidenceVersion}.json`;
  const bytes = readFileSync(join(directory, name)), pins = JSON.parse(readFileSync(join(directory, `${evidenceVersion}.pins.json`), "utf8"));
  check(bytes.byteLength <= 1024 * 1024 && pins.data_file === name && pins.bytes === bytes.byteLength && pins.source_catalogue_sha256 === frozenHash
    && createHash("sha256").update(bytes).digest("hex") === pins.sha256);
  const data = JSON.parse(bytes.toString("utf8"));
  check(data.schema_version === "discovery-evidence-card-index/1.0.0" && data.version === evidenceVersion
    && data.rubric_version === rubricVersion && data.source_catalogue_sha256 === frozenHash && data.candidates.length === sourceRows.length);
  check(!/(?:\/Users\/|\/home\/|\/opt\/|jack@|password|api_key|private_key)/i.test(JSON.stringify(data)) && !/[\u3400-\u9fff]/.test(JSON.stringify(data)));
  const result = new Map<string, ResearchEvidenceSummary>();
  for (const entry of data.candidates as Entry[]) {
    const row = sourceRows.find(row => row.id === entry.id), observations = entry.observations;
    check(row && row.source_state === entry.source_state && row.formula === entry.formula && !result.has(entry.id)
      && entry.source_detail_sha256 === details.get(entry.id)?.sha256 && observations.evidence_level === "E1"
      && observations.source_pairing_quantified === true && observations.geometry_causality_quantified === false
      && observations.ambient_300K_direct_support === null && Array.isArray(observations.counterevidence));
    check(entry.detail.url === `/research-hypotheses/evidence-cards/${evidenceVersion}/${entry.source_state}.json`
      && Number.isSafeInteger(entry.detail.bytes) && entry.detail.bytes > 0 && entry.detail.bytes <= 256 * 1024 && /^[a-f0-9]{64}$/.test(entry.detail.sha256));
    check(observations.counterevidence.every(item => ["joint_adverse", "discordant"].includes(item.direction)
      && (item.comparison_origin === "frozen_countercontrol" && Number.isInteger(item.countercontrol_index) && item.countercontrol_index! >= 0
        || item.comparison_origin === "selected_source_control" && item.countercontrol_index === null && item.direction === "discordant")
      && typeof item.control_reference === "string" && item.lambda_target_minus_control_range.length === 2
      && item.lambda_target_minus_control_range.every(Number.isFinite) && Number.isFinite(item.source_tc_target_minus_control_K)
      && item.causal_geometry_effect === null && typeof item.scope === "string"));
    result.set(entry.id, { evidence_level: "E1", source_pairing_quantified: true, geometry_causality_quantified: false,
      ambient_300K_direct_support: null, counterevidence_count: observations.counterevidence.length,
      joint_adverse_count: observations.counterevidence.filter(item => item.direction === "joint_adverse").length,
      discordant_count: observations.counterevidence.filter(item => item.direction === "discordant").length, detail: entry.detail });
  }
  check(result.size === sourceRows.length);
  return result;
}
