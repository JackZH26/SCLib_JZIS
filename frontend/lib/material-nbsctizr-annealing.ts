import snapshot from "@/public/research-pilots/materials-nbsctizr-annealing-2026-10-04.json";

export type NbsctizrAnnealing = typeof snapshot;
export type NbsctizrSample = NbsctizrAnnealing["samples"][number];
export type NbsctizrWindow = NbsctizrAnnealing["source_windows"][number];
export type NbsctizrSourceCell = {
  raw_value: string | null; raw_unit: string | null; normalized_value: null;
  role: string; status: string; source_locator_id: string;
  literal: { char_start: number; char_end: number; end_exclusive: boolean; literal_sha256: string } | null;
};
export const nbsctizrAnnealingSnapshotSha256 = "e7422f5af6df9113db17c593b37bbe1509fe4bcb64cadf20ccafc2fa29133f27";
export const nbsctizrAnnealingDownloadPath = (process.env.NEXT_PUBLIC_BASE_PATH || "") + "/research-pilots/materials-nbsctizr-annealing-2026-10-04.json";
export const nbsctizrAnnealingRoute = "/materials/source-observations/nbsctizr-annealing";

const row = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const hash = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
function matchesSnapshot(value: unknown, expected: unknown, depth = 0): boolean {
  if (depth > 20) return false;
  if (expected === null || typeof expected !== "object") return value === expected
    && (typeof value !== "number" || Number.isFinite(value)) && (typeof value !== "string" || value.length <= 2048);
  if (Array.isArray(expected)) return Array.isArray(value) && value.length === expected.length && value.length <= 64
    && value.every((item, index) => matchesSnapshot(item, expected[index], depth + 1));
  if (!row(value) || !row(expected)) return false;
  const keys = Object.keys(expected);
  return keys.length <= 64 && Object.keys(value).length === keys.length
    && keys.every(key => Object.hasOwn(value, key) && matchesSnapshot(value[key], expected[key], depth + 1));
}

/** Exact finite source metadata; values are not overlays on selected catalogue properties. */
export function loadNbsctizrAnnealing(value: unknown = snapshot): NbsctizrAnnealing | null {
  if (!matchesSnapshot(value, snapshot)) return null;
  const data = value as NbsctizrAnnealing;
  if (data.version !== "materials-nbsctizr-annealing/1.0.0" || data.status !== "source_qualified_comparison"
    || data.authority.canonical_updates !== 0 || data.authority.scientific_acceptance !== false
    || data.authority.formal_human_review !== false || data.authority.ml_training_approved !== false
    || data.authority.calculation_executed !== false
    || data.authority.selected_result_sample_state_phase_association !== "unestablished"
    || data.authority.cross_publication_physical_sample_equivalence !== "unestablished"
    || data.counts.independent_experiment_count_established !== false
    || data.samples[0].processing_temperature_value !== null || data.samples[0].hold_duration_value !== null
    || data.sources.some(source => !hash(source.pdf_sha256) || !hash(source.derived_text_sha256))
    || data.source_windows.some(window => !hash(window.window_sha256)
      || !Number.isSafeInteger(window.char_start) || !Number.isSafeInteger(window.char_end)
      || window.char_start < 0 || window.char_end <= window.char_start || window.end_exclusive !== true)) return null;
  const tables = [data.phase_table, data.phase_table_2023, data.parameter_table, data.gap_fits, data.tc_2023];
  for (const table of tables) for (const item of table.rows) for (const cell of Object.values(item.cells) as NbsctizrSourceCell[]) {
    const window = data.source_windows.find(window => window.id === cell.source_locator_id && window.source_id === table.source_id);
    if (!window || cell.normalized_value !== null) return null;
    if (cell.raw_value === null) {
      if (cell.status !== "not_listed_in_source_row" || cell.literal !== null) return null;
    } else if (!cell.literal || cell.status !== "reported" || !hash(cell.literal.literal_sha256)
      || cell.literal.end_exclusive !== true || cell.literal.char_start < window.char_start
      || cell.literal.char_end > window.char_end
      || Array.from(cell.raw_value).length !== cell.literal.char_end - cell.literal.char_start) return null;
  }
  return JSON.parse(JSON.stringify(data)) as NbsctizrAnnealing;
}

/** Only captured, versioned PDFs and in-range one-based pages are linked. */
export function nbsctizrSourceHref(sourceId: string, page?: number): string | null {
  const source = snapshot.sources.find(item => item.id === sourceId);
  if (!source || !["https://arxiv.org/pdf/2311.00195v1", "https://arxiv.org/pdf/2406.19553v1"].includes(source.source_url)) return null;
  if (page !== undefined && (!Number.isSafeInteger(page) || page < 1 || page > source.pdf_pages)) return null;
  return source.source_url + (page === undefined ? "" : "#page=" + page);
}

// Exact result/source membership from the inspected material DTO, not physical sample mapping.
const sourceResults: Record<string, ReadonlySet<string>> = {
  "arxiv:2311.00195": new Set([
    "legacy-result:478a9e94511547761b9a890719401f234e0dca58295f0bb9050635f4f21955ac",
    "legacy-result:c2d17bd525c97e7f498cb8f74a4b59e316b259d4490ebf2e2882e41aad76ee99",
    "legacy-result:9c08152181e545561fcd2b7adb4be3da58305a1efa348181bcbfb0b5bd55ca67",
    "legacy-result:4ea0ce71fac67b7808a5b633a6ae5c12b9ee031e60547fc6ae2eaafc5bfff991",
    "legacy-result:8600ed7c60e2d794676721975ca6f208f9185080ce0947c8c5f5470a7f8c20ca",
    "legacy-result:4dcee198b26f5c2315199a06cce5c2b2c55ea83eb46e71a71a1b88e315379089",
    "legacy-result:e3237c8574fa63cf92cd148b675c603d58cb0658fbb5d45a2fa31e103232305f",
    "legacy-result:6c21356129404fc8e23ec4458d8e219999f2b3484e185834018603706ef3b599",
  ]),
  "arxiv:2406.19553": new Set([
    "legacy-result:ed551e132e4a3fb2a0b6ce12b57d1acfef815e250492f81cee70606334d48fdf",
    "legacy-result:738de59a576c4a769a8a634af2315d255af84f29510c1c3a80d0eb47d1703331",
    "legacy-result:1675519088cb5466645dbc9ffc4c4d4a3e59740434142f8fdcc75dd928977df4",
  ]),
};
export function nbsctizrAnnealingReading(materialId: string, selected: unknown): { href: string; label: string; note: string } | null {
  if (materialId !== "mat:nbsctizr" || !row(selected) || !row(selected.source)) return null;
  const paperId = selected.source.paper_id, resultId = selected.result_id;
  if (typeof paperId !== "string" || typeof resultId !== "string"
    || !Object.hasOwn(sourceResults, paperId) || !sourceResults[paperId].has(resultId)) return null;
  return {
    href: (process.env.NEXT_PUBLIC_BASE_PATH || "") + nbsctizrAnnealingRoute,
    label: "Annealing, phase compositions and superconducting parameter comparisons",
    note: "Two source editions retain distinct preparation groups, transition reports and fitted parameters. Related-source matching does not assign the selected result to a physical specimen or phase.",
  };
}
