// Independent server loader. Client components import these types only.
// Published source calculations never enter COD coordinate proposals or RPS inputs.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";

export type PublicEvidenceValue = null | boolean | number | string | PublicEvidenceValue[] | { [key: string]: PublicEvidenceValue };
export type PublicEvidenceObject = { [key: string]: PublicEvidenceValue };
export type SourceHypothesisCriterion = "identity" | "quantitative_route_response" | "pairing_relevance" | "ambient_feasibility" | "competition_and_coherence" | "novelty" | "decision";
export type SourceHypothesisRiskTag = "technetium" | "hydrogen_anharmonicity" | "magnetic_model" | "metastable_phase" | "residual_force_stress" | "sampling_method";
export type SourceHypothesis = {
  id: string;
  formula: string;
  reduced_formula: string;
  composition: Record<string, number>;
  canonical_composition_key: string;
  elements: string[];
  source_state: string;
  control_state: string;
  source_directory: string;
  control_directory: string | null;
  status: "unscored_research_hypothesis";
  route: "geometry_construction";
  route_submechanism: string | null;
  prototype: string;
  prototype_evidence: PublicEvidenceValue;
  support_grade: 3;
  support_scale_max: 4;
  support_meaning: string;
  source_tc: { target_K: number; control_K: number; delta_K: number; unit: "K"; method: "Eliashberg"; mu_star: 0.1; experimental: false; sigma_binding: null };
  lambda_difference: { all10: number[] | null; range: [number, number] | null; convention: "target_minus_control"; unit: "dimensionless" };
  omega_log_ratio_all10: number[] | null;
  risk_summary: string;
  ambient_scope: string;
  route_response: string;
  next_action: string;
  seven_criteria: Record<SourceHypothesisCriterion, string>;
  risk_tags: SourceHypothesisRiskTag[];
  countercontrols: PublicEvidenceObject[];
  physical_summary: PublicEvidenceValue;
  evidence_pins: { artifact: string; bytes: number; sha256: string; availability: "digest_reference" }[];
  newness_scope: string;
  formal_RPS: null;
  rank: null;
  success_probability: null;
  human_scientific_review: null;
  experimental_superconductivity: null;
  room_temperature_support: null;
  quantified_physical_bandwidth: null;
  quantified_mobile_carrier_density: null;
  whole_BZ_stability: null;
  global_thermodynamic_stability: null;
};
export type SourceHypothesisCatalogue = {
  schema_version: "source-computed-hypothesis-catalogue/1.0.0";
  version: "2026-10-07-source103-v1";
  published_on: "2026-10-07";
  publication_status: "public_unscored_research_hypotheses";
  default_sort: "formula";
  download_url: string;
  scope: string;
  source_tc_scope: string;
  pairing_response_scope: string;
  risk_tag_scope: string;
  evidence_scope: string;
  counts: { composition_groups: 103; formal_RPS_scored: 0; human_reviewed: 0; experimental_confirmed: 0; room_temperature_supported: 0 };
  pathway_status: { geometry_construction: 103; quantified_physical_bandwidth: 0; quantified_mobile_carrier_density: 0 };
  dataset_source: { title: string; version: "Materials Cloud 2023.163 v1"; authors: string[]; url: string; doi: "10.24435/materialscloud:qv-bq"; license: "CC BY 4.0"; license_basis: string; license_url: string; attribution: string };
  risk_tag_labels: Record<SourceHypothesisRiskTag, string>;
  projection_provenance: { source_index_sha256: string; frozen_catalogue_sha256: string; publication_eligibility_sha256: string; frozen_sources_changed: false; new_scientific_calculations: 0; public_wording_corrections: { formula: "Nb2HfTa"; field: "seven_criteria.novelty"; reason: string }[] };
  candidates: SourceHypothesis[];
};
export type SourceHypothesisBrowseCandidate = Pick<SourceHypothesis,
  "id" | "formula" | "reduced_formula" | "composition" | "elements" | "source_state" | "control_state" | "status" | "route" | "support_grade" | "prototype" | "source_tc" | "risk_tags"> & {
  lambda_difference_range: [number, number] | null;
  risk_preview: string;
  next_action_preview: string;
  countercontrol_count: number;
  detail: { url: string; bytes: number; sha256: string };
};
export type SourceHypothesisBrowseCatalogue = Omit<SourceHypothesisCatalogue, "schema_version" | "candidates"> & {
  schema_version: "source-computed-hypothesis-browse/1.0.0";
  candidates: SourceHypothesisBrowseCandidate[];
};
export type SourceHypothesisDetail = Pick<SourceHypothesisCatalogue, "dataset_source" | "scope" | "source_tc_scope" | "pairing_response_scope" | "risk_tag_scope"> & {
  schema_version: "source-computed-hypothesis-detail/1.0.0";
  catalogue_version: SourceHypothesisCatalogue["version"];
  candidate: SourceHypothesis;
};

const filename = "source-computed-candidates-2026-10-07.json";
const hashPattern = /^[a-f0-9]{64}$/;
const statePattern = /^agm[0-9]{9}$/;
const criteria: SourceHypothesisCriterion[] = ["identity", "quantitative_route_response", "pairing_relevance", "ambient_feasibility", "competition_and_coherence", "novelty", "decision"];
const riskTags: SourceHypothesisRiskTag[] = ["technetium", "hydrogen_anharmonicity", "magnetic_model", "metastable_phase", "residual_force_stress", "sampling_method"];
const nullFields = ["formal_RPS", "rank", "success_probability", "human_scientific_review", "experimental_superconductivity", "room_temperature_support", "quantified_physical_bandwidth", "quantified_mobile_carrier_density", "whole_BZ_stability", "global_thermodynamic_stability"] as const;
const privateText = /(?:\/Users\/|\/opt\/|\/home\/|\/var\/|\/tmp\/|[A-Za-z]:\\|jack@|ssh:\/\/)/;
const privateKey = /^(?:local_path|remote_path|remote_directory|working_directory|account|email|user|hostname|host_id|invocation|InvocationID|invocation_id|unit_name|service|runtime|resource|resources|resource_envelope|cpu_seconds|wall_seconds|MemoryPeak|MemoryMax|budget|available_budget|native_cost|private_resource|within_route_priority|token)$/;
function check(value: unknown): asserts value { if (!value) throw new Error("The source-computed hypothesis catalogue could not be verified."); }
function closed(value: unknown, keys: readonly string[]) {
  check(value !== null && typeof value === "object" && !Array.isArray(value));
  check(Object.keys(value).sort().join("|") === [...keys].sort().join("|"));
}
function finite(value: unknown): value is number { return typeof value === "number" && Number.isFinite(value); }
function text(value: unknown): value is string { return typeof value === "string" && value.trim().length > 0 && value.length <= 131072 && !privateText.test(value); }
function boundedPublic(value: unknown) {
  let nodes = 0;
  function visit(item: unknown, depth: number): void {
    check(++nodes <= 400000 && depth <= 40);
    if (typeof item === "string") check(item.length <= 131072 && !privateText.test(item) && !/[\u3400-\u9fff]/.test(item));
    else if (typeof item === "number") check(finite(item));
    else if (item !== null && typeof item === "object") {
      check(Array.isArray(item) || Object.getPrototypeOf(item) === Object.prototype || Object.getPrototypeOf(item) === null);
      for (const [key, child] of Object.entries(item)) {
        check(!privateKey.test(key) && !/(?:cgroup|systemd|credential|auth_token|access_token|refresh_token|api_key|password|ssh_|CPUQuota|MemAvailable)/i.test(key));
        visit(child, depth + 1);
      }
    } else check(item === null || typeof item === "boolean");
  }
  visit(value, 0);
  check(Buffer.byteLength(JSON.stringify(value), "utf8") <= 8 * 1024 * 1024);
}
function formulaComposition(formula: string): Record<string, number> {
  check(text(formula) && /^(?:[A-Z][a-z]?(?:[1-9][0-9]*)?)+$/.test(formula));
  const counts: Record<string, number> = {};
  for (const match of formula.matchAll(/([A-Z][a-z]?)([0-9]*)/g)) {
    check(!Object.hasOwn(counts, match[1]));
    counts[match[1]] = match[2] ? Number(match[2]) : 1;
  }
  return counts;
}
function canonicalComposition(value: Record<string, number>): string {
  check(value !== null && typeof value === "object" && !Array.isArray(value));
  const entries = Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0);
  check(entries.length > 0 && entries.length <= 118 && entries.every(([element, n]) => /^[A-Z][a-z]?$/.test(element) && Number.isInteger(n) && n > 0));
  return entries.map(([element, n]) => `${element}:${n}`).join("|");
}

/** Validate release semantics independently of a particular artifact hash. */
export function validateSourceHypothesisCatalogue(raw: unknown): SourceHypothesisCatalogue {
  boundedPublic(raw);
  closed(raw, ["schema_version", "version", "published_on", "publication_status", "default_sort", "download_url", "scope", "source_tc_scope", "pairing_response_scope", "risk_tag_scope", "evidence_scope", "counts", "pathway_status", "dataset_source", "risk_tag_labels", "projection_provenance", "candidates"]);
  const catalogue = raw as SourceHypothesisCatalogue;
  check(catalogue.schema_version === "source-computed-hypothesis-catalogue/1.0.0" && catalogue.version === "2026-10-07-source103-v1"
    && catalogue.published_on === "2026-10-07" && catalogue.publication_status === "public_unscored_research_hypotheses"
    && catalogue.default_sort === "formula" && catalogue.download_url === `/research-hypotheses/${filename}`);
  for (const value of [catalogue.scope, catalogue.source_tc_scope, catalogue.pairing_response_scope, catalogue.risk_tag_scope, catalogue.evidence_scope]) check(text(value));
  closed(catalogue.counts, ["composition_groups", "formal_RPS_scored", "human_reviewed", "experimental_confirmed", "room_temperature_supported"]);
  check(catalogue.counts.composition_groups === 103 && Object.entries(catalogue.counts).every(([key, value]) => key === "composition_groups" || value === 0));
  closed(catalogue.pathway_status, ["geometry_construction", "quantified_physical_bandwidth", "quantified_mobile_carrier_density"]);
  check(catalogue.pathway_status.geometry_construction === 103 && catalogue.pathway_status.quantified_physical_bandwidth === 0 && catalogue.pathway_status.quantified_mobile_carrier_density === 0);
  closed(catalogue.dataset_source, ["title", "version", "authors", "url", "doi", "license", "license_basis", "license_url", "attribution"]);
  const source = catalogue.dataset_source;
  check(source.version === "Materials Cloud 2023.163 v1" && source.doi === "10.24435/materialscloud:qv-bq" && source.url === "https://archive.materialscloud.org/records/3kbt5-r3n56"
    && source.license === "CC BY 4.0" && source.license_url === "https://creativecommons.org/licenses/by/4.0/"
    && JSON.stringify(source.authors) === JSON.stringify(["Tiago F. T. Cerqueira", "Antonio Sanna", "Miguel A. L. Marques"]) && text(source.title) && text(source.license_basis) && text(source.attribution));
  closed(catalogue.risk_tag_labels, riskTags);
  check(riskTags.every(tag => text(catalogue.risk_tag_labels[tag])));
  closed(catalogue.projection_provenance, ["source_index_sha256", "frozen_catalogue_sha256", "publication_eligibility_sha256", "frozen_sources_changed", "new_scientific_calculations", "public_wording_corrections"]);
  const provenance = catalogue.projection_provenance;
  check(hashPattern.test(provenance.source_index_sha256) && hashPattern.test(provenance.frozen_catalogue_sha256) && hashPattern.test(provenance.publication_eligibility_sha256)
    && provenance.frozen_sources_changed === false && provenance.new_scientific_calculations === 0 && provenance.public_wording_corrections.length === 1);
  const correction = provenance.public_wording_corrections[0];
  closed(correction, ["formula", "field", "reason"]);
  check(correction.formula === "Nb2HfTa" && correction.field === "seven_criteria.novelty" && text(correction.reason));
  check(Array.isArray(catalogue.candidates) && catalogue.candidates.length === 103);
  const compositions = new Set<string>(), ids = new Set<string>();
  for (const row of catalogue.candidates) {
    closed(row, ["id", "formula", "reduced_formula", "composition", "canonical_composition_key", "elements", "source_state", "control_state", "source_directory", "control_directory", "status", "route", "route_submechanism", "prototype", "prototype_evidence", "support_grade", "support_scale_max", "support_meaning", "source_tc", "lambda_difference", "omega_log_ratio_all10", "risk_summary", "ambient_scope", "route_response", "next_action", "seven_criteria", "risk_tags", "countercontrols", "physical_summary", "evidence_pins", "newness_scope", ...nullFields]);
    check(statePattern.test(row.source_state) && statePattern.test(row.control_state) && row.id === `source-hypothesis:${row.source_state}` && !ids.has(row.id));
    ids.add(row.id);
    const composition = canonicalComposition(row.composition);
    check(composition === row.canonical_composition_key && composition === canonicalComposition(formulaComposition(row.formula))
      && row.reduced_formula === row.formula && !compositions.has(composition));
    compositions.add(composition);
    check(JSON.stringify(row.elements) === JSON.stringify(Object.keys(row.composition).sort()));
    check(/^batch-a\/[A-Za-z0-9]+_agm[0-9]{9}$/.test(row.source_directory) && row.source_directory.endsWith(`_${row.source_state}`)
      && (row.control_directory === null || /^batch-a\/[A-Za-z0-9]+_agm[0-9]{9}$/.test(row.control_directory) && row.control_directory.endsWith(`_${row.control_state}`)));
    check(row.status === "unscored_research_hypothesis" && row.route === "geometry_construction" && row.support_grade === 3 && row.support_scale_max === 4);
    check(row.route_submechanism === null || text(row.route_submechanism));
    for (const value of [row.prototype, row.support_meaning, row.risk_summary, row.ambient_scope, row.route_response, row.next_action, row.newness_scope]) check(text(value));
    check(nullFields.every(key => row[key] === null));
    closed(row.source_tc, ["target_K", "control_K", "delta_K", "unit", "method", "mu_star", "experimental", "sigma_binding"]);
    const tc = row.source_tc;
    check(tc.unit === "K" && tc.method === "Eliashberg" && tc.mu_star === 0.1 && tc.experimental === false && tc.sigma_binding === null
      && finite(tc.target_K) && finite(tc.control_K) && finite(tc.delta_K) && Math.abs(tc.target_K - tc.control_K - tc.delta_K) < 1e-9);
    closed(row.lambda_difference, ["all10", "range", "convention", "unit"]);
    const lambda = row.lambda_difference;
    check(lambda.convention === "target_minus_control" && lambda.unit === "dimensionless"
      && (lambda.all10 === null || Array.isArray(lambda.all10) && lambda.all10.length === 10 && lambda.all10.every(finite))
      && (lambda.range === null || Array.isArray(lambda.range) && lambda.range.length === 2 && lambda.range.every(finite) && lambda.range[0] <= lambda.range[1]));
    if (lambda.all10 !== null) check(lambda.range !== null && Math.abs(Math.min(...lambda.all10) - lambda.range[0]) < 1e-12 && Math.abs(Math.max(...lambda.all10) - lambda.range[1]) < 1e-12);
    check(row.omega_log_ratio_all10 === null || Array.isArray(row.omega_log_ratio_all10) && row.omega_log_ratio_all10.length === 10 && row.omega_log_ratio_all10.every(finite));
    closed(row.seven_criteria, criteria);
    check(criteria.every(key => text(row.seven_criteria[key])));
    if (row.formula === "Nb2HfTa") check(row.seven_criteria.novelty.includes("HfNbTa") && !row.seven_criteria.novelty.includes("Nb2TiMo"));
    check(Array.isArray(row.risk_tags) && new Set(row.risk_tags).size === row.risk_tags.length && row.risk_tags.every(tag => riskTags.includes(tag)));
    check(Array.isArray(row.countercontrols) && row.countercontrols.every(value => value !== null && typeof value === "object" && !Array.isArray(value)));
    check(Array.isArray(row.evidence_pins) && row.evidence_pins.every(pin => {
      closed(pin, ["artifact", "bytes", "sha256", "availability"]);
      return text(pin.artifact) && !/[\\/]/.test(pin.artifact) && Number.isSafeInteger(pin.bytes) && pin.bytes >= 0 && hashPattern.test(pin.sha256) && pin.availability === "digest_reference";
    }));
  }
  return catalogue;
}

function loadPublished() {
  const directory = join(process.cwd(), "public/research-hypotheses");
  const body = readFileSync(join(directory, filename));
  check(body.byteLength <= 8 * 1024 * 1024);
  const pins = JSON.parse(readFileSync(join(directory, filename.replace(".json", ".pins.json")), "utf8"));
  closed(pins, ["schema_version", "data_file", "bytes", "sha256", "source_index_sha256", "frozen_catalogue_sha256", "publication_eligibility_sha256", "detail_manifest_file", "detail_manifest_bytes", "detail_manifest_sha256"]);
  check(pins.schema_version === "source-computed-hypothesis-public-pins/1.0.0" && pins.data_file === filename && pins.bytes === body.byteLength
    && hashPattern.test(pins.sha256) && createHash("sha256").update(body).digest("hex") === pins.sha256);
  const catalogue = validateSourceHypothesisCatalogue(JSON.parse(body.toString("utf8")));
  check(pins.source_index_sha256 === catalogue.projection_provenance.source_index_sha256 && pins.frozen_catalogue_sha256 === catalogue.projection_provenance.frozen_catalogue_sha256
    && pins.publication_eligibility_sha256 === catalogue.projection_provenance.publication_eligibility_sha256);
  check(pins.detail_manifest_file === filename.replace(".json", ".details.json"));
  const manifestBody = readFileSync(join(directory, pins.detail_manifest_file));
  check(manifestBody.byteLength <= 128 * 1024 && pins.detail_manifest_bytes === manifestBody.byteLength && createHash("sha256").update(manifestBody).digest("hex") === pins.detail_manifest_sha256);
  const manifest = JSON.parse(manifestBody.toString("utf8")) as {
    schema_version: string; catalogue_version: string; catalogue_sha256: string;
    details: { id: string; source_state: string; file: string; bytes: number; sha256: string }[];
  };
  closed(manifest, ["schema_version", "catalogue_version", "catalogue_sha256", "details"]);
  check(manifest.schema_version === "source-computed-hypothesis-detail-manifest/1.0.0" && manifest.catalogue_version === catalogue.version && manifest.catalogue_sha256 === pins.sha256
    && Array.isArray(manifest.details) && manifest.details.length === catalogue.candidates.length);
  const details = new Map<string, { url: string; bytes: number; sha256: string }>();
  for (const record of manifest.details) {
    closed(record, ["id", "source_state", "file", "bytes", "sha256"]);
    const row = catalogue.candidates.find(candidate => candidate.id === record.id);
    check(row && row.source_state === record.source_state && !details.has(record.id) && record.file === `details/${row.source_state}.json`
      && Number.isSafeInteger(record.bytes) && record.bytes > 0 && record.bytes <= 1024 * 1024 && hashPattern.test(record.sha256));
    const detailBody = readFileSync(join(directory, record.file));
    check(detailBody.byteLength === record.bytes && createHash("sha256").update(detailBody).digest("hex") === record.sha256);
    const detail = JSON.parse(detailBody.toString("utf8")) as SourceHypothesisDetail;
    closed(detail, ["schema_version", "catalogue_version", "dataset_source", "scope", "source_tc_scope", "pairing_response_scope", "risk_tag_scope", "candidate"]);
    check(detail.schema_version === "source-computed-hypothesis-detail/1.0.0" && detail.catalogue_version === catalogue.version
      && JSON.stringify(detail.candidate) === JSON.stringify(row));
    for (const key of ["dataset_source", "scope", "source_tc_scope", "pairing_response_scope", "risk_tag_scope"] as const) check(JSON.stringify(detail[key]) === JSON.stringify(catalogue[key]));
    details.set(record.id, { url: `/research-hypotheses/${record.file}`, bytes: record.bytes, sha256: record.sha256 });
  }
  return { catalogue, details };
}

export function getSourceHypothesisCatalogue(): SourceHypothesisCatalogue {
  return loadPublished().catalogue;
}

function excerpt(value: string, maximum: number): string {
  if (value.length <= maximum) return value;
  const prefix = value.slice(0, maximum);
  return prefix.slice(0, Math.max(prefix.lastIndexOf(" "), maximum - 40)).trimEnd() + "…";
}

/** Only short list/filter fields cross the initial server-to-client boundary. */
export function getSourceHypothesisBrowseCatalogue(): SourceHypothesisBrowseCatalogue {
  const { catalogue, details } = loadPublished();
  const candidates = catalogue.candidates.map(row => ({
    id: row.id, formula: row.formula, reduced_formula: row.reduced_formula, composition: row.composition, elements: row.elements,
    source_state: row.source_state, control_state: row.control_state, status: row.status, route: row.route, support_grade: row.support_grade,
    prototype: excerpt(row.prototype, 180), source_tc: row.source_tc, risk_tags: row.risk_tags,
    lambda_difference_range: row.lambda_difference.range, risk_preview: excerpt(row.risk_summary, 240),
    next_action_preview: excerpt(row.next_action, 180), countercontrol_count: row.countercontrols.length, detail: details.get(row.id)!,
  }));
  const browse: SourceHypothesisBrowseCatalogue = { ...catalogue, schema_version: "source-computed-hypothesis-browse/1.0.0", candidates };
  check(Buffer.byteLength(JSON.stringify(browse), "utf8") <= 300 * 1024);
  return browse;
}
