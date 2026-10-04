import type { ScientificKey, ScientificMaterial, ScientificReceipt } from "./discovery-scientific";

export const CONDITION_DESIGN_VERSION = "discovery-condition-design/1.0.0";
export const CONDITION_DESIGN_MAX_BYTES = 256 * 1024;
export const CONDITION_DESIGN_MAX_MODIFICATIONS = 8;
export const MODIFICATION_KINDS = {
  doping: "Doping", substitution: "Substitution", vacancy: "Vacancy", strain: "Strain",
  interface: "Interface", layer: "Layer count", twist: "Twist", pressure: "Pressure",
} as const;
export type ModificationKind = keyof typeof MODIFICATION_KINDS;
export const PAIRING_ROUTES = {
  unresolved: "Unresolved mechanism", epc: "Electron–phonon route", correlated: "Correlated-electron route",
  multiband: "Multiband route", interface: "Interface-mediated hypothesis",
} as const;
export type PairingRoute = keyof typeof PAIRING_ROUTES;
export const CONDITION_STAGES: readonly {
  key: "host" | "activation" | "pairing" | "coherence";
  title: string; question: string; fields: readonly ScientificKey[]; scope: string;
}[] = [
  { key: "host", title: "Host", question: "Can this structure exist under the proposed conditions?",
    fields: ["formation_energy_per_atom", "energy_above_hull", "phonon_min_frequency"],
    scope: "Formation energy, a matched hull and sampled phonons address different stability questions. They do not establish survival at 300 K and ambient pressure." },
  { key: "activation", title: "Electronic activation", question: "What modification could create suitable electronic states?",
    fields: ["band_gap", "dos_at_fermi"],
    scope: "Recorded electronic quantities do not prove an activation path. Higher DOS is not universally better, and a calculated zero gap does not establish experimental metallicity." },
  { key: "pairing", title: "Pairing", question: "Which interaction should be investigated in this state?",
    fields: ["electron_phonon_lambda", "omega_log"],
    scope: "These native fields describe the electron–phonon route. Missing λ or ωlog does not count against other mechanisms. Model assumptions and method applicability remain necessary." },
  { key: "coherence", title: "Coherence", question: "Could pairing support a macroscopic coherent state?",
    fields: ["superfluid_stiffness"],
    scope: "Retain dimensionality, temperature, definition and normalization. Superconducting-state observations are post-outcome information unless separately reviewed for a prospective task." },
];

export interface ConditionDesignInput {
  hostLabel: string;
  stateLabel: string;
  modifications: { kind: ModificationKind; parameters: string }[];
  targetPressure: "unspecified" | "ambient" | "specified";
  pressureGpa: string;
  temperatureK: string;
  pairingRoute: PairingRoute;
  hypothesis: string;
  nextAction: string;
}
export function initialConditionDesign(row?: ScientificMaterial | null): ConditionDesignInput {
  return { hostLabel: row?.assessment.formula ?? "", stateLabel: "", modifications: [{ kind: "doping", parameters: "" }],
    targetPressure: "unspecified", pressureGpa: "", temperatureK: "", pairingRoute: "unresolved", hypothesis: "", nextAction: "" };
}
export class ConditionDesignError extends Error {}
function text(value: unknown, name: string, max: number): string {
  if (typeof value !== "string" || !value.trim()) throw new ConditionDesignError(`${name} is required.`);
  if (Array.from(value).length > max || /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(value)
    || /[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/.test(value)) {
    throw new ConditionDesignError(`${name} must be valid text of at most ${max.toLocaleString("en-US")} characters.`);
  }
  return value.trim();
}
function targetNumber(raw: unknown, name: string, optional = false): number | null {
  if (optional && raw === "") return null;
  if (typeof raw !== "string" || !/^(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(raw.trim())) {
    throw new ConditionDesignError(`${name} must be a nonnegative decimal number.`);
  }
  const value = Number(raw);
  if (!Number.isFinite(value) || value < 0 || (value === 0 && /[1-9]/.test(raw.split(/[eE]/)[0]))) {
    throw new ConditionDesignError(`${name} must be finite and representable without underflow.`);
  }
  return value;
}
export interface ConditionDesignStep {
  stage: "host" | "activation" | "pairing" | "coherence" | "validation";
  kind: "source_review" | "calculation" | "experiment";
  question: string;
  requirements: string[];
  execution_status: "proposal_only";
}
function workPlan(route: PairingRoute, modifications: ConditionDesignInput["modifications"]): ConditionDesignStep[] {
  const modificationsContext: Record<ModificationKind, string> = {
    doping: "Specify dopant, site, concentration basis, charge compensation and nominal versus measured composition.",
    substitution: "Specify parent and substituted sites, occupancy, composition and competing configurations.",
    vacancy: "Specify vacancy species and site, supercell, concentration, charge state and configuration sampling.",
    strain: "Specify the strain tensor, reference structure, coordinate frame and relaxation constraints.",
    interface: "Specify both materials, orientation, termination, stack, spacing and charge-transfer reference.",
    layer: "Specify active layers, thickness, boundary conditions and the distinction between geometric and electronic dimensionality.",
    twist: "Specify layers, angle convention, heterostrain, supercell and structural relaxation.",
    pressure: "Specify pressure path, medium or stress mode, calibration, temperature and decompression conditions.",
  };
  const step = (stage: ConditionDesignStep["stage"], kind: ConditionDesignStep["kind"], question: string, requirements: string[]): ConditionDesignStep =>
    ({ stage, kind, question, requirements, execution_status: "proposal_only" });
  const pairing = route === "epc"
    ? step("pairing", "calculation", "Is an electron–phonon model applicable to the proposed state?", [
      "Use a reviewed structure and state; establish convergence and the normal-state model before DFPT.",
      "Keep α²F, λ, ωlog, frequency units, k/q meshes and solver assumptions in one computation chain.",
      "Declare μ* and test model sensitivity; a solver output would be a prediction, not an observation.",
    ]) : route === "unresolved"
      ? step("pairing", "source_review", "Which pairing channels are supported by relevant evidence?", [
        "Review mechanism-specific literature and competing explanations before choosing a solver.",
        "Absence of EPC quantities is not adverse evidence for a nonphonon route.",
      ]) : step("pairing", "calculation", "Which model could test the proposed pairing hypothesis?", [
        `The ${PAIRING_ROUTES[route].toLowerCase()} is a user hypothesis, not an established mechanism.`,
        "Define the orbital or band subspace, interactions, susceptibility or interface model and domain of applicability.",
        "Retain normal-state inputs, convergence, approximations and alternative channels; do not substitute EPC descriptors.",
      ]);
  return [
    step("host", "source_review", "Is the starting host and proposed modification identifiable?", [
      "Find coordinates, occupancies, composition and source locators for the exact starting state.",
      ...[...new Set(modifications.map(m => m.kind))].map(kind => modificationsContext[kind]),
      "The selected source is a reference; its results are not inherited by a modified state.",
    ]),
    step("host", "calculation", "Can the proposed state remain stable at the target conditions?", [
      "Review structure identity before relaxation and same-method competing-phase calculations.",
      "Specify pressure and temperature, energy versus enthalpy or free energy, phonon coverage and applicable approximations.",
      "Test chemical, mechanical and kinetic stability where relevant; a sampled phonon minimum is not a full stability verdict.",
    ]),
    step("activation", "calculation", "How does the modification change the low-energy electronic state?", [
      "Compare the host and modified states with matched structure, method, pressure and temperature definitions.",
      "Retain bands, orbital subspaces, DOS normalization and carrier definitions; no universal larger-is-better rule is applied.",
    ]), pairing,
    step("coherence", "calculation", "What limits macroscopic coherence in this proposed state?", [
      "Specify dimensionality, temperature, phase-stiffness definition, normalization and the model domain.",
      "Separate prospective calculations from superconducting-state measurements and target-related post-outcome features.",
    ]),
    step("validation", "experiment", "Which outcomes would change the decision to continue?", [
      "Before execution, define at least two distinguishing outcomes, stop or redirect decisions, and equipment or sample prerequisites.",
      "Declare CPU, GPU, memory, storage and human-time costs under a fixed budget; missing costs are not free.",
      "If feasible, establish sample composition and structure, conditions, transport and magnetic or thermodynamic criteria with detection limits.",
      "A transport anomaly alone does not establish bulk superconductivity; retain null results with their measurement window.",
    ]),
  ];
}
function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value !== null && typeof value === "object") return `{${Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)
    .map(([key, v]) => `${JSON.stringify(key)}:${stable(v)}`).join(",")}}`;
  return typeof value === "number" && Object.is(value, -0) ? "-0" : JSON.stringify(value);
}
function readable(value: unknown, depth = 0): string {
  const pad = "  ".repeat(depth), next = "  ".repeat(depth + 1);
  if (Array.isArray(value)) return value.length ? `[\n${value.map(v => `${next}${readable(v, depth + 1)}`).join(",\n")}\n${pad}]` : "[]";
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value);
    return entries.length ? `{\n${entries.map(([key, v]) => `${next}${JSON.stringify(key)}: ${readable(v, depth + 1)}`).join(",\n")}\n${pad}}` : "{}";
  }
  return stable(value);
}
function bounded(value: unknown): string {
  const encoded = stable(value);
  if (new TextEncoder().encode(encoded).length > CONDITION_DESIGN_MAX_BYTES) {
    throw new ConditionDesignError("The selected source and design exceed the 256 KiB plan limit. Inspect the full scientific record separately; no source pins were silently omitted.");
  }
  return encoded;
}

/** Local proposals only. The caller supplies an already verified public row;
 * this is not a publication parser or a new scientific-admission path. */
export function conditionDesignPublication(receipt?: ScientificReceipt | null) {
  return receipt ? { package_id: receipt.package_id, payload_sha256: receipt.payload_sha256,
    selection_sha256: receipt.selection_sha256, publication_sha256: receipt.publication_sha256, review_sha256: receipt.review_sha256,
    release_id: receipt.payload.base.release_id, campaign_id: receipt.payload.campaign.id, campaign_version: receipt.payload.campaign.version } : null;
}
export async function createConditionDesignPlan(input: ConditionDesignInput, row?: ScientificMaterial | null, receipt?: ScientificReceipt | null) {
  if (row && !receipt) throw new ConditionDesignError("A selected source row requires its verified publication context. Select the publication and material again.");
  if (row && receipt && !receipt.payload.rows.some(candidate => stable(candidate) === stable(row))) {
    throw new ConditionDesignError("The selected row does not match this publication. Select the material again before preparing a design.");
  }
  const host = text(input.hostLabel, "Proposed host label", 4000);
  const state = text(input.stateLabel, "Proposed state label", 200);
  if (!Array.isArray(input.modifications) || input.modifications.length < 1 || input.modifications.length > CONDITION_DESIGN_MAX_MODIFICATIONS) {
    throw new ConditionDesignError("Use between one and eight explicit modifications.");
  }
  const modifications = input.modifications.map(m => {
    if (!m || !Object.hasOwn(MODIFICATION_KINDS, m.kind)) throw new ConditionDesignError("Select a supported modification kind.");
    return { kind: m.kind, parameters: text(m.parameters, "Modification parameters", 2000) };
  });
  if (new Set(modifications.map(m => stable(m))).size !== modifications.length) throw new ConditionDesignError("Duplicate modifications must be combined or distinguished by their parameters.");
  if (!Object.hasOwn(PAIRING_ROUTES, input.pairingRoute)) throw new ConditionDesignError("Select a supported pairing hypothesis.");
  if (!["unspecified", "ambient", "specified"].includes(input.targetPressure)) throw new ConditionDesignError("Select an explicit target-pressure option.");
  const pressure = input.targetPressure === "ambient" ? { kind: "ambient_target", requested_atm: 1 }
    : input.targetPressure === "specified" ? { kind: "specified_target", requested_gpa: targetNumber(input.pressureGpa, "Target pressure") }
      : { kind: "unspecified_target" };
  const body = {
    version: CONDITION_DESIGN_VERSION,
    record_kind: "local_research_design",
    research_unit: "host_modification_state_conditions",
    source_basis: row ? { publication: conditionDesignPublication(receipt), selected_row: row,
      scope: "Unmodified reference record; no scientific result is inherited by the proposed state." } : null,
    user_proposal: { host_label: host, state_label: state, modifications,
      target_conditions: { pressure, temperature_k: targetNumber(input.temperatureK, "Target temperature", true), status: "requested_not_realized" },
      pairing_hypothesis: input.pairingRoute, hypothesis: text(input.hypothesis, "Research hypothesis", 2000),
      next_action: text(input.nextAction, "Proposed next action", 2000),
      scope: "User-authored hypothesis; not a reviewed action, host designation or established material genealogy." },
    work_plan: workPlan(input.pairingRoute, modifications),
    authority: { database_changed: false, calculation_submitted: false, scientific_acceptance: false,
      ml_training_approved: false, genealogy_established: false, modified_state_result_inheritance: false, rps_reassessed: false },
    reproducibility: { input_order: "Modification order is preserved; object keys are sorted for a deterministic plan digest.",
      digest_scope: "Canonical UTF-8 body with sorted object keys, preserved array order and signed zero; excludes plan_id and content_sha256. Local document identity, not original publication bytes or scientific validity.",
      evaluation: "These research questions are a conceptual framework, not a universal physical equation or quantitative probability model." },
  };
  // Detach the validated source before the first await. A caller changing its
  // row while WebCrypto runs must not change the body attached to this digest.
  const canonicalBody = bounded(body);
  const snapshot = JSON.parse(canonicalBody) as typeof body;
  const bytes = new TextEncoder().encode(canonicalBody);
  if (!globalThis.crypto?.subtle) throw new ConditionDesignError("This browser cannot compute the local plan checksum. Use a secure browser context and try again.");
  const digest = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), v => v.toString(16).padStart(2, "0")).join("");
  const plan = JSON.parse(bounded({ ...snapshot, plan_id: `condition-design:${digest}`, content_sha256: digest })) as typeof body & { plan_id: string; content_sha256: string };
  // JSON.stringify would turn a source's signed zero into positive zero.
  // Keep the original numeric sign without claiming native payload byte parity.
  const json = `${readable(plan)}\n`;
  if (new TextEncoder().encode(json).length > CONDITION_DESIGN_MAX_BYTES) {
    throw new ConditionDesignError("The formatted design exceeds the 256 KiB export limit. No source pins were silently omitted.");
  }
  return { plan, json };
}
export type ConditionDesignPlan = Awaited<ReturnType<typeof createConditionDesignPlan>>;
