import { webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MainBarrierSummary, MaterialDetails, ScientificDiscoveryMatrix } from "@/components/ScientificDiscoveryMatrix";
import { compareMainBarrierBasis, getScientificCatalog, getScientificProjection, mainBarrierOptions, mainBarrierShape, parseScientificCatalog, parseScientificReceipt, validMainBarrier,
  type MainBarrier, type ScientificPublication } from "@/lib/discovery-scientific";
import { parsePreparedSelection, parseSelectionAccess, parseSelectionContext, prepareSelection, prepareSelectionV2, type SelectionRequestV2 } from "@/lib/discovery-selection";
import { parseCurrentInspection, parseGovernanceHeader, parseOperatorAccess } from "@/lib/discovery-governance";
import fullWire from "../fixtures/discovery-scientific-full-eight.detail.wire.json";
import nativeWire from "../fixtures/discovery-main-barrier-native.delivery20260921r4.wire.json";
import { hash, verifiedFixture, wires } from "./helpers/discovery-selection-fixtures";
import { barrierRequest, syntheticV2Prepared } from "./helpers/discovery-main-barrier-fixtures";

vi.mock("@/lib/discovery-scientific", async importOriginal => {
  const original = await importOriginal<typeof import("@/lib/discovery-scientific")>();
  return { ...original, getScientificCatalog: vi.fn(), getScientificProjection: vi.fn() };
});
beforeEach(() => { vi.stubGlobal("crypto", webcrypto); vi.clearAllMocks(); });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
const hypothesis = (): MainBarrier => ({ status: "declared", category: "scientific_hypothesis", statement: "A sampled soft mode warrants follow-up.",
  rationale: "This sampled result does not establish full-zone stability or superconductivity.", basis_refs: [{ kind: "scientific_cell", property_key: "phonon_min_frequency" }] });
// Re-sealed adversarial/client fixtures, not fresh native responses or review.
function v2(change?: (p: any) => void, barrier: MainBarrier = hypothesis()) {
  const r = JSON.parse(fullWire), p = r.payload;
  p.version = "discovery-scientific-projection/2.0.0"; p.selection.version = "discovery-scientific-selection/2.0.0";
  p.rows[0].main_barrier = structuredClone(barrier); p.selection.representatives[0].main_barrier = structuredClone(barrier);
  change?.(p);
  p.campaign_sha256 = hash(JSON.stringify(p.campaign)); p.rows.forEach((row: any) => { row.profile_assignment.campaign_hash = p.campaign_sha256; });
  r.selection_sha256 = p.selection_sha256 = hash(JSON.stringify(p.selection)); r.payload_sha256 = hash(JSON.stringify(p));
  const selected: ScientificPublication = { package_id: r.package_id, payload_sha256: r.payload_sha256, selection_sha256: r.selection_sha256,
    publication_sha256: r.publication_sha256, review_sha256: r.review_sha256 };
  return { raw: JSON.stringify(r), selected, payload: p };
}
function setBarrier(p: any, barrier: unknown) { p.rows[0].main_barrier = barrier; p.selection.representatives[0].main_barrier = structuredClone(barrier); }
function unknownBandGap(p: any) {
  const c = p.rows[0].cells[0]; Object.assign(c, { availability: "unknown", observations: [], result_refs: [], reason_code: "no_matching_registered_result" });
  const { property_key, availability, result_refs, reason_code, evidence_refs } = c;
  p.selection.representatives[0].cells[0] = { property_key, availability, result_refs, reason_code, evidence_refs };
  p.capabilities.scientific_properties[0].populated_observations = 0;
}

describe("actual guarded native v2 wire compatibility", () => {
  it("pins the retained capture and the backend inputs used by this batch", () => {
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/discovery-main-barrier-native.delivery20260921r4.wire.json"), "utf8")))
      .toBe("a82406b1a077d7def40f73e3cda3c1f01d4c7d79a81eb208ddb47d4a2f6b554b");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/discovery-main-barrier-native.batch75.wire.json"), "utf8")))
      .toBe("8966bbc04eac7e46c98cb0cf764e8b9fd93585f5b5a007e1b4858ad3da0e6f7e");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/discovery-main-barrier-native.batch72.wire.json"), "utf8")))
      .toBe("ebc7a1b27ab2eaf742507da39eea4f4532e7ea629298d458d64b3f8d7deccd8e");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/discovery-main-barrier-native.batch73.wire.json"), "utf8")))
      .toBe("dc88cea1acb6ffaaac0df1504aae279f1ea9b61936940c6bffe596e5867afe4c");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/discovery-main-barrier-native.batch74.wire.json"), "utf8")))
      .toBe("6d061a88e3ba71039fe09b1c3151569ef454854fd70738b615ff6758372ac556");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/discovery-main-barrier-native.batch71.wire.json"), "utf8")))
      .toBe("bbd9d7490b881a233314b3a60025788320c2205c8b9a6d1ba7a341e976d877a9");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/discovery-main-barrier-native.batch70.wire.json"), "utf8")))
      .toBe("45b4552e1c7e332fa77a95a20a16d8121e7b3c29126e94bccdf9766e6fca30e9");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/discovery-main-barrier-native.batch69.wire.json"), "utf8")))
      .toBe("e74ffc908035889d4cd28424ef1e96ac8ea401f7289809f2f0ffc73d068b9b1e");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/discovery-main-barrier-native.batch68.wire.json"), "utf8")))
      .toBe("24060676f250dda54bd604ff097f8a883e35a755f24f165d6146b467f2a6a428");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/discovery-main-barrier-native.batch67.wire.json"), "utf8")))
      .toBe("cc48f80182e16f1238a5da9480c43f10b31b6bd93d037412a6fe3400ecb830ad");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/discovery-main-barrier-native.batch65.wire.json"), "utf8")))
      .toBe("83c65fb4120d796d8f5116269cc146198aefe6cd7da104565a186a2fc13387ed");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/discovery-main-barrier-native.wire.json"), "utf8")))
      .toBe("6ecd0b0b05e52971013cada385f195cc1c2f967a8013eaa2f613e2163272bfc9");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/discovery-main-barrier-native.batch59.wire.json"), "utf8")))
      .toBe("837e79928da739ffcd44d7ac95927fa56e7191881f2d31e14ecf05d11d6c83e9");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/discovery-main-barrier-native.batch58.wire.json"), "utf8")))
      .toBe("488b2967d4abbbbbf1a6dcbc2c9232cef5f106b4091fc1321d512b0255ee6167");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/discovery-main-barrier-native.batch57.wire.json"), "utf8")))
      .toBe("b5b131b248e7c5e1f17ae1731db2a466972e0b8b5103cfb40ec0e3e99a5cca40");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/discovery-main-barrier-native.batch56.wire.json"), "utf8")))
      .toBe("9e245e6ab25082a48cb7842b3aa4c2818961cd9e7bfab640473bcb4c56b7addc");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/discovery-main-barrier-native.batch55.wire.json"), "utf8")))
      .toBe("fceb5673302755deb975dba759f536af70db78d9f3a7c56e7cbb36ebcdc92aa9");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/discovery-main-barrier-native.batch54.wire.json"), "utf8")))
      .toBe("bcdd029d75d726b8450e675b41abe608067b63ee948c595bf21d9ddec40d7fd2");
    // Batch52 remains historical evidence, not a relabeled current capture.
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/discovery-main-barrier-native.batch52.wire.json"), "utf8")))
      .toBe("1873c02e3d9305ec4c3d048706193447aa4c12b156afa7a003d83796c91f9f7a");
    expect(nativeWire.fixture_notice).toBe("Actual guarded SQL-to-HTTP synthetic v2 capture; no real scientific or rights approval.");
    expect(nativeWire.capture_test_path).toBe("api/tests/test_discovery_main_barrier.py");
    expect(nativeWire.capture_test_name).toBe("test_barrier_edit_needs_new_preview_package_and_independent_review_then_source_hold");
    expect(nativeWire.source_pins).toHaveLength(297);
    expect(nativeWire.source_pins.some(p => p.path === "api/services/ml08_pilot.schema.json")).toBe(true);
    expect(new Set(nativeWire.source_pins.map(p => p.path)).size).toBe(nativeWire.source_pins.length);
    for (const pin of nativeWire.source_pins) {
      expect(Object.keys(pin).sort()).toEqual(["path", "sha256"]); expect(pin.path).toMatch(/^api\/[A-Za-z0-9_./-]+$/);
      expect(pin.path.split("/")).not.toContain(".."); expect(pin.sha256).toMatch(/^[a-f0-9]{64}$/);
      expect(hash(readFileSync(resolve(process.cwd(), "..", pin.path), "utf8")), pin.path).toBe(pin.sha256);
    }
  });
  it("accepts exact native preparation, independent inspection and public response without reserializing Python numbers", async () => {
    const request = nativeWire.request as SelectionRequestV2, access = parseSelectionAccess(nativeWire.selection_access_response);
    const context = await parseSelectionContext(nativeWire.context_response, access, request.source);
    const prepared = await parsePreparedSelection(nativeWire.prepared_response, access, context, request);
    expect(prepared.payload.version).toBe("discovery-scientific-projection/2.0.0");
    expect(prepared.payload.rows[0]).toHaveProperty("main_barrier", request.choices[0].main_barrier);
    const operator = parseOperatorAccess(nativeWire.operator_access_response), publicEnvelope = JSON.parse(nativeWire.public_response);
    const header = parseGovernanceHeader(nativeWire.governance_header_response, operator, publicEnvelope.package_id);
    const current = await parseCurrentInspection(nativeWire.inspection_response, header);
    const selected: ScientificPublication = { package_id: publicEnvelope.package_id, payload_sha256: publicEnvelope.payload_sha256,
      selection_sha256: publicEnvelope.selection_sha256, publication_sha256: publicEnvelope.publication_sha256, review_sha256: publicEnvelope.review_sha256 };
    const published = await parseScientificReceipt(nativeWire.public_response, selected);
    expect(current.payload_sha256).toBe(prepared.payload_sha256); expect(published.payload_sha256).toBe(prepared.payload_sha256);
    expect(current.payload).toEqual(prepared.payload); expect(published.payload).toEqual(prepared.payload);
    expect(current.payload.rows[0]).toHaveProperty("main_barrier", request.choices[0].main_barrier);
    expect(operator.actor_user_id).not.toBe(access.actor_user_id);
    expect(published.payload.scientific_acceptance).toBe(false); expect(published.payload.ml_training_approved).toBe(false);
    expect(prepared.commit_json).toBe(JSON.parse(nativeWire.prepared_response).commit_json);
  });
});

describe("explicit main-barrier v2 scientific contract", () => {
  it.each([hypothesis(), { status: "not_declared" } as const])("accepts explicit %s without altering the registry or frozen RPS", async barrier => {
    const x = v2(undefined, barrier), checked = await parseScientificReceipt(x.raw, x.selected), old = JSON.parse(fullWire).payload;
    expect(checked.payload.version).toBe("discovery-scientific-projection/2.0.0");
    expect(checked.payload.rows[0]).toHaveProperty("main_barrier", barrier);
    expect(checked.payload.capabilities.version).toBe("discovery-scientific-projection/1.0.0");
    expect(checked.payload.rows[0].assessment).toEqual(old.rows[0].assessment);
    expect(checked.payload.scientific_acceptance).toBe(false); expect(checked.payload.ml_training_approved).toBe(false);
  });
  it("preserves real historical v1 bytes, with no invented barrier field", async () => {
    const r = JSON.parse(fullWire), selected = { package_id: r.package_id, payload_sha256: r.payload_sha256, selection_sha256: r.selection_sha256,
      publication_sha256: r.publication_sha256, review_sha256: r.review_sha256 };
    const checked = await parseScientificReceipt(fullWire, selected);
    expect(checked.payload.rows[0]).not.toHaveProperty("main_barrier"); expect(checked.payload.selection.representatives[0]).not.toHaveProperty("main_barrier");
  });
  it.each([
    ["missing row declaration", (p: any) => { delete p.rows[0].main_barrier; }],
    ["missing selection declaration", (p: any) => { delete p.selection.representatives[0].main_barrier; }],
    ["row-selection disagreement", (p: any) => { p.rows[0].main_barrier.statement = "A different interpretation"; }],
    ["future payload", (p: any) => { p.version = "discovery-scientific-projection/3.0.0"; }],
    ["future selection", (p: any) => { p.selection.version = "discovery-scientific-selection/3.0.0"; }],
    ["mixed v1 selection", (p: any) => { p.selection.version = "discovery-scientific-selection/1.0.0"; }],
    ["v1 with injected declaration", (p: any) => { p.version = "discovery-scientific-projection/1.0.0"; p.selection.version = "discovery-scientific-selection/1.0.0"; }],
    ["capability version bump", (p: any) => { p.capabilities.version = "discovery-scientific-projection/2.0.0"; }],
    ["undeclared with hidden text", (p: any) => setBarrier(p, { status: "not_declared", statement: "Hidden inference" })],
    ["unknown category", (p: any) => setBarrier(p, { ...hypothesis(), category: "causal_proof" })],
    ["no basis", (p: any) => setBarrier(p, { ...hypothesis(), basis_refs: [] })],
    ["duplicate basis", (p: any) => { const b: any = hypothesis(); b.basis_refs.push(b.basis_refs[0]); setBarrier(p, b); }],
    ["unsorted basis", (p: any) => setBarrier(p, { ...hypothesis(), basis_refs: [{ kind: "scientific_cell", property_key: "phonon_min_frequency" }, { kind: "scientific_cell", property_key: "band_gap" }] })],
    ["invented property", (p: any) => setBarrier(p, { ...hypothesis(), basis_refs: [{ kind: "scientific_cell", property_key: "invented_property" }] })],
    ["cross-context native ref", (p: any) => setBarrier(p, { ...hypothesis(), basis_refs: [{ kind: "scientific_cell", property_key: "phonon_min_frequency", state_id: crypto.randomUUID() }] })],
    ["arbitrary source URL", (p: any) => setBarrier(p, { ...hypothesis(), basis_refs: [{ kind: "url", url: "https://example.com" }] })],
    ["invented science approval", (p: any) => setBarrier(p, { ...hypothesis(), scientific_acceptance: true })],
    ["gap on a reported result", (p: any) => setBarrier(p, { ...hypothesis(), category: "evidence_gap" })],
    ["hypothesis on unquantified cell", (p: any) => { unknownBandGap(p); setBarrier(p, { ...hypothesis(), basis_refs: [{ kind: "scientific_cell", property_key: "band_gap" }] }); }],
    ["category/ref kind mismatch", (p: any) => setBarrier(p, { ...hypothesis(), category: "execution_constraint" })],
    ["unrecorded policy reason", (p: any) => setBarrier(p, { ...hypothesis(), category: "recorded_policy_reason", basis_refs: [{ kind: "assessment_reason", code: "invented" }] })],
    ["unrecorded action constraint", (p: any) => setBarrier(p, { ...hypothesis(), category: "execution_constraint", basis_refs: [{ kind: "execution_constraint", code: "invented" }] })],
    ["alternative-only reason", (p: any) => {
      const alternate = structuredClone(p.rows[0].assessment); alternate.id = "synthetic-alternative"; alternate.result.reason_codes = ["alternative_only"];
      const reference = { ...p.rows[0].representative, id: alternate.id }; p.rows[0].alternatives = [{ reference, assessment: alternate }];
      p.selection.representatives[0].alternatives = [reference];
      setBarrier(p, { ...hypothesis(), category: "recorded_policy_reason", basis_refs: [{ kind: "assessment_reason", code: "alternative_only" }] });
    }],
    ["foreign observation state", (p: any) => { p.rows[0].cells[6].observations[0].state.id = crypto.randomUUID(); }],
  ] as const)("rejects re-sealed %s", async (_name, change) => {
    const x = v2(change); await expect(parseScientificReceipt(x.raw, x.selected)).rejects.toThrow();
  });
  it("accepts an unknown-cell gap without zero imputation", async () => {
    const x = v2(p => { unknownBandGap(p); setBarrier(p, { ...hypothesis(), category: "evidence_gap", basis_refs: [{ kind: "scientific_cell", property_key: "band_gap" }] }); });
    const checked = await parseScientificReceipt(x.raw, x.selected);
    expect(checked.payload.rows[0].cells[0].observations).toEqual([]); expect(checked.payload.rows[0].cells[0].availability).toBe("unknown");
  });
  it.each([
    ["evidence_gap", "unknown", false, true], ["evidence_gap", "not_computed", false, true], ["evidence_gap", "conflicted", true, true],
    ["evidence_gap", "not_applicable", false, false], ["scientific_hypothesis", "conflicted", true, true],
    ["scientific_hypothesis", "reported", false, false], ["scientific_hypothesis", "not_computed", true, false],
  ] as const)("uses the explicit %s / %s / quantified %s category rules", (category, availability, quantified, expected) => {
    const row = v2().payload.rows[0];
    expect(validMainBarrier({ ...hypothesis(), category }, row.assessment, [{ property_key: "phonon_min_frequency", availability, quantified }])).toBe(expected);
  });
  it.each(["recorded_policy_reason", "execution_constraint"] as const)("keeps %s exact and case-sensitive", async category => {
    const code = "Missing:DFPT.Dependency-01";
    const x = v2(p => {
      p.rows[0].assessment.result[category === "recorded_policy_reason" ? "reason_codes" : "execution_constraint_reasons"].push(code);
      setBarrier(p, { ...hypothesis(), category, basis_refs: [{ kind: category === "recorded_policy_reason" ? "assessment_reason" : "execution_constraint", code }] });
    });
    await expect(parseScientificReceipt(x.raw, x.selected)).resolves.toBeDefined();
    const row = x.payload.rows[0], cells = row.cells.map((c: any) => ({ ...c, quantified: true }));
    expect(validMainBarrier({ ...row.main_barrier, basis_refs: [{ ...row.main_barrier.basis_refs[0], code: code.toLowerCase() }] }, row.assessment, cells)).toBe(false);
  });
  it("does not infer a barrier from dimension minima, reason order, rank or alternatives", () => {
    const x = v2(undefined, { status: "not_declared" }), row = x.payload.rows[0];
    row.assessment.result.reason_codes = ["second", "first"]; row.assessment.result.score_display = 1000;
    row.assessment.dimensions.stability.anchor = 0; row.alternatives.reverse();
    expect(validMainBarrier(row.main_barrier, row.assessment, [])).toBe(true);
    expect(row.main_barrier).toEqual({ status: "not_declared" });
    expect(mainBarrierOptions("scientific_hypothesis", row.assessment, [])).toEqual([]);
  });
  it("uses Python-compatible Unicode blankness and code-point ordering, not UTF-16 ordering", () => {
    expect(mainBarrierShape({ ...hypothesis(), statement: "\u0085" })).toBe(false);
    expect(mainBarrierShape({ ...hypothesis(), statement: "\uFEFF" })).toBe(true);
    expect(mainBarrierShape({ ...hypothesis(), statement: "\u{1F9EA}".repeat(500) })).toBe(true);
    expect(mainBarrierShape({ ...hypothesis(), statement: "\u{1F9EA}".repeat(501) })).toBe(false);
    const row = v2().payload.rows[0], refs = ["\u{10000}", "\uE000"].map(code => ({ kind: "assessment_reason" as const, code }));
    row.assessment.result.reason_codes = refs.map(r => r.code); refs.sort(compareMainBarrierBasis);
    expect(refs.map(r => r.code)).toEqual(["\uE000", "\u{10000}"]);
    expect(validMainBarrier({ ...hypothesis(), category: "recorded_policy_reason", basis_refs: refs }, row.assessment, [])).toBe(true);
    expect(validMainBarrier({ ...hypothesis(), category: "recorded_policy_reason", basis_refs: [...refs].reverse() }, row.assessment, [])).toBe(false);
  });
  it.each(["", " ", "\u202f", "bad\u0000", "bad\u001f", "bad\u007f", "\uD800"])("rejects invalid barrier text %j", text => {
    expect(mainBarrierShape({ ...hypothesis(), statement: text })).toBe(false);
    expect(mainBarrierShape({ ...hypothesis(), rationale: text })).toBe(false);
  });
  it("accepts tabs, line breaks and bounded rationale without scientific authority", () => {
    expect(mainBarrierShape({ ...hypothesis(), statement: "line\nnext\tpart\r", rationale: "x".repeat(2000) })).toBe(true);
    expect(mainBarrierShape({ ...hypothesis(), rationale: "x".repeat(2001) })).toBe(false);
  });
});

describe("v2 preparation and shared barrier presentation", () => {
  it.each([hypothesis(), { status: "not_declared" } as const])("checks nested v2 while preserving v1 access/context/wrapper and exact commands", async barrier => {
    const f = await verifiedFixture(), request = barrierRequest(barrier), raw = syntheticV2Prepared(request.request_key, barrier);
    const prepared = await parsePreparedSelection(raw, f.access, f.context, request);
    expect(prepared.payload.rows[0]).toHaveProperty("main_barrier", barrier);
    expect(prepared.payload.selection.representatives[0]).toHaveProperty("main_barrier", barrier);
    expect(prepared.commit_json).not.toEqual(f.prepared.commit_json); expect(prepared.request_sha256).not.toEqual(f.prepared.request_sha256);
    await expect(parsePreparedSelection(wires.preparedWire, f.access, f.context, request)).rejects.toThrow();
    await expect(parsePreparedSelection(raw, f.access, f.context, f.request)).rejects.toThrow();
  });
  it("rejects edited barrier choices against the original preview even when old hashes are retained", async () => {
    const f = await verifiedFixture(), request = barrierRequest(hypothesis()), raw = syntheticV2Prepared(request.request_key, hypothesis());
    if (request.choices[0].main_barrier.status === "declared") request.choices[0].main_barrier.rationale = "Changed after compilation";
    await expect(parsePreparedSelection(raw, f.access, f.context, request)).rejects.toThrow();
  });
  it("posts new drafts only to prepare-v2, with no fallback to the v1 route", async () => {
    const fetcher = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => new Response("{}", { headers: { "content-type": "application/json" } })); vi.stubGlobal("fetch", fetcher);
    const request = barrierRequest(); await prepareSelectionV2(request);
    expect(fetcher.mock.calls[0][0]).toMatch(/\/selection\/prepare-v2$/);
    expect(fetcher.mock.calls[0][1]).toMatchObject({ method: "POST", cache: "no-store", credentials: "include", redirect: "error", body: JSON.stringify(request) });
    expect(() => prepareSelection(request)).toThrow(); expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("shows category, full rationale and exact basis in shared public/private details", async () => {
    const x = v2(), checked = await parseScientificReceipt(x.raw, x.selected), row = checked.payload.rows[0], close = vi.fn();
    render(<MaterialDetails row={row} prepared close={close} />);
    const section = screen.getByRole("region", { name: "Curator-declared main barrier" });
    expect(within(section).getByText("Scientific hypothesis")).toBeInTheDocument();
    expect(within(section).getByText("A sampled soft mode warrants follow-up.")).toBeInTheDocument();
    expect(within(section).getByText(/This sampled result does not establish/, { selector: "p" })).toBeInTheDocument();
    expect(within(section).getByText(/Scientific cell · Sampled phonon minimum/)).toBeInTheDocument();
    expect(within(section).getByText(/not proof of a primary causal obstacle or an ML training label/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close details" })); expect(close).toHaveBeenCalledOnce();
  });
  it("distinguishes legacy absence from an explicit new undeclared choice", () => {
    const old = JSON.parse(fullWire).payload.rows[0]; const { rerender } = render(<MainBarrierSummary row={old} />);
    expect(screen.getByText("Main barrier not separately declared")).toBeInTheDocument();
    rerender(<MainBarrierSummary row={{ ...old, main_barrier: { status: "not_declared" } }} />);
    expect(screen.getByText("Not declared · explicit curator choice")).toBeInTheDocument();
  });
  it("shows a declared barrier in the compact public material row, with rationale and basis available in details", async () => {
    const x = v2(), receipt = await parseScientificReceipt(x.raw, x.selected);
    const catalog = parseScientificCatalog(JSON.stringify({ version: "discovery-scientific-catalog/1.0.0", status: "published", items: [x.selected],
      unavailable_count: 0, scientific_acceptance: false, ml_training_approved: false }));
    vi.mocked(getScientificCatalog).mockResolvedValue(catalog); vi.mocked(getScientificProjection).mockResolvedValue(receipt);
    render(<ScientificDiscoveryMatrix />);
    await screen.findByRole("option", { name: new RegExp(x.selected.package_id) });
    fireEvent.change(screen.getByLabelText("Published scientific version"), { target: { value: x.selected.package_id } });
    const table = await screen.findByRole("table");
    expect(within(table).getByText("A sampled soft mode warrants follow-up.")).toBeInTheDocument();
    expect(within(table).getByText("Scientific hypothesis")).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "Curator-declared main barrier / constraints" })).toBeInTheDocument();
    fireEvent.click(within(table).getByRole("button", { name: receipt.payload.rows[0].assessment.formula }));
    const detail = screen.getByRole("region", { name: "Curator-declared main barrier" });
    expect(within(detail).getByText(/This sampled result does not establish/, { selector: "p" })).toBeInTheDocument();
    expect(within(detail).getByText(/Scientific cell · Sampled phonon minimum/)).toBeInTheDocument();
  });
});
