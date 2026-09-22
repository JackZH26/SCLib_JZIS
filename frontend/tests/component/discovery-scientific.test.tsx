import { createHash, webcrypto } from "node:crypto";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ScientificDiscoveryMatrix } from "@/components/ScientificDiscoveryMatrix";
import { PUBLIC_API_BASE } from "@/lib/api";
import {
  SCIENTIFIC_DISCLAIMER, SCIENTIFIC_FAILURE, SCIENTIFIC_MAX_BYTES, getScientificCatalog, getScientificProjection,
  parseScientificCatalog, parseScientificReceipt, scientificNumber, scientificQuantity,
  type ScientificReceipt, type ScientificPublication, type ScientificCell,
} from "@/lib/discovery-scientific";
import fullCatalogWire from "../fixtures/discovery-scientific-full-eight.catalogue.wire.json";
import fullWire from "../fixtures/discovery-scientific-full-eight.detail.wire.json";
import lowerCatalogWire from "../fixtures/discovery-scientific-lower-score.catalogue.wire.json";
import lowerWire from "../fixtures/discovery-scientific-lower-score.detail.wire.json";
import provenance from "../fixtures/discovery-scientific-provenance.json";

vi.mock("@/lib/discovery-scientific", async importOriginal => {
  const actual = await importOriginal<typeof import("@/lib/discovery-scientific")>();
  return { ...actual, getScientificCatalog: vi.fn(), getScientificProjection: vi.fn() };
});
const checksum = (s: string) => createHash("sha256").update(s).digest("hex");
const catalog = () => parseScientificCatalog(fullCatalogWire);
const original = () => JSON.parse(fullWire) as ScientificReceipt;
const pin = (r: ScientificReceipt): ScientificPublication => ({ package_id: r.package_id, payload_sha256: r.payload_sha256,
  selection_sha256: r.selection_sha256, publication_sha256: r.publication_sha256, review_sha256: r.review_sha256 });

// Deliberately re-sealed adversarial client fixtures, NOT public approvals.
// Independent semantic tests must fail even when superficial outer pins match.
function reseal(mutate: (r: ScientificReceipt) => void) {
  const r = original(); mutate(r);
  r.payload.campaign_sha256 = checksum(JSON.stringify(r.payload.campaign));
  for (const row of r.payload.rows) row.profile_assignment.campaign_hash = r.payload.campaign_sha256;
  r.selection_sha256 = r.payload.selection_sha256 = checksum(JSON.stringify(r.payload.selection));
  r.payload_sha256 = checksum(JSON.stringify(r.payload));
  return { raw: JSON.stringify(r), selected: pin(r), value: r };
}
function syncCells(r: ScientificReceipt) {
  r.payload.selection.representatives[0].cells = r.payload.rows[0].cells.map(({ property_key, availability, reason_code, result_refs, evidence_refs }) =>
    ({ property_key, availability, reason_code, result_refs, evidence_refs }));
  for (const c of r.payload.capabilities.scientific_properties) c.populated_observations = r.payload.rows.reduce((n, row) =>
    n + row.cells.find(cell => cell.property_key === c.property_key)!.observations.length, 0);
}
function setAbsent(r: ScientificReceipt, status: ScientificCell["availability"]) {
  const c = r.payload.rows[0].cells[0], source = c.observations[0].sources[0];
  c.availability = status; c.observations = []; c.result_refs = [];
  c.reason_code = status === "unknown" ? "no_matching_registered_result" : "explicit_synthetic_declaration";
  c.evidence_refs = status === "unknown" ? [] : [{ table: "event_evidence", row_id: source.id, row_sha256: source.row_sha256 }];
  c.availability_basis = status === "unknown" ? "registered_result_inventory" : "explicit_review_required_declaration";
  syncCells(r);
}
function addSecondResult(r: ScientificReceipt, conflicted: boolean) {
  const c = r.payload.rows[0].cells[0], second = structuredClone(c.observations[0]);
  second.property.id = "00000000-0000-0000-0000-000000000001";
  second.property.row_sha256 = "a".repeat(64); second.quantity.value = 0.25;
  if (!conflicted) second.property.component_key = "second_component";
  c.observations.unshift(second);
  c.result_refs.unshift({ table: "event_properties", row_id: second.property.id, row_sha256: second.property.row_sha256 });
  if (conflicted) {
    const source = second.sources[0]; c.availability = "conflicted"; c.reason_code = "explicit_synthetic_conflict";
    c.availability_basis = "explicit_review_required_declaration";
    c.evidence_refs = [{ table: "event_evidence", row_id: source.id, row_sha256: source.row_sha256 }];
  }
  syncCells(r);
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
beforeEach(() => { vi.resetAllMocks(); vi.stubGlobal("crypto", webcrypto); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("scientific public wire contract", () => {
  it.each([
    ["full-eight.catalogue.json", fullCatalogWire], ["full-eight.detail.json", fullWire],
    ["lower-score.catalogue.json", lowerCatalogWire], ["lower-score.detail.json", lowerWire],
  ])("retains exact captured UTF-8 bytes: %s", (name, wire) => {
    const evidence = provenance.files.find(f => f.file === name)!;
    expect(checksum(wire)).toBe(evidence.sha256);
    expect(new TextEncoder().encode(wire)).toHaveLength(evidence.size_bytes);
    expect(provenance.synthetic_fixture_only).toBe(true);
    expect(provenance.production_publication_performed).toBe(false);
  });
  it("accepts actual public HTTP bytes, eight native fields, and only the narrow phonon acceptance", async () => {
    const r = await parseScientificReceipt(fullWire, catalog().items[0]);
    const cells = r.payload.rows[0].cells;
    expect(cells).toHaveLength(8);
    expect(cells.flatMap(c => c.observations).filter(o => o.scientific_scope_accepted).map(o => o.property.property_key)).toEqual(["phonon_min_frequency"]);
    expect(r.payload.rows[0].assessment.result.score_display).toBe(7100);
    expect(r.scientific_acceptance).toBe(false);
  });
  it("retains the explicitly published lower-score action and higher-score alternative", async () => {
    const r = await parseScientificReceipt(lowerWire, parseScientificCatalog(lowerCatalogWire).items[0]);
    expect(r.payload.rows).toHaveLength(1);
    expect(r.payload.rows[0].assessment.result.score_display).toBe(4400);
    expect(r.payload.rows[0].alternatives[0].assessment.result.score_display).toBe(7100);
  });
  it.each(["package_id", "payload_sha256", "selection_sha256", "publication_sha256", "review_sha256"] as const)("rejects a different selected %s", async key => {
    const chosen = { ...catalog().items[0], [key]: key === "package_id" ? "00000000-0000-0000-0000-000000000001" : "a".repeat(64) };
    await expect(parseScientificReceipt(fullWire, chosen)).rejects.toThrow(SCIENTIFIC_FAILURE);
  });
  it("rejects payload bytes changed without a fresh catalog pin", async () => {
    await expect(parseScientificReceipt(fullWire.replace("SYNTHETIC TEST ONLY", "SYNTHETIC FAKE ONLY"), catalog().items[0])).rejects.toThrow();
  });
  it.each([
    '{"x":1,"x":2}', '{"x":1,"\\u0078":2}', '{"x":NaN}', '{"x":1e999}', '{"x":1e-999}', '{"x":01}', '{"x":1,}',
    '{"x":"\\ud800"}', '{"x":"\\udc00"}', '{"x":"\\x41"}', '\ufeff{}', '{} {}', '['.repeat(41) + '0' + ']'.repeat(41),
  ])("rejects malformed, duplicate, unsafe or over-deep JSON: %s", async raw => {
    expect(() => parseScientificCatalog(raw)).toThrow(SCIENTIFIC_FAILURE);
    await expect(parseScientificReceipt(raw, catalog().items[0])).rejects.toThrow(SCIENTIFIC_FAILURE);
  });
  it.each([
    (c: ReturnType<typeof catalog>) => c.items.push(c.items[0]),
    (c: ReturnType<typeof catalog>) => { c.status = "not_published"; },
    (c: ReturnType<typeof catalog>) => { c.unavailable_count = 25; },
    (c: ReturnType<typeof catalog>) => { (c as unknown as { scientific_acceptance: boolean }).scientific_acceptance = true; },
  ])("rejects inconsistent catalogs", mutate => { const c = catalog(); mutate(c); expect(() => parseScientificCatalog(JSON.stringify(c))).toThrow(); });
  it.each([
    ["missing cell", (r: ScientificReceipt) => { r.payload.rows[0].cells.pop(); }],
    ["wrong registry unit", (r: ScientificReceipt) => { r.payload.rows[0].cells[0].unit = "meV"; }],
    ["wrong capability count", (r: ScientificReceipt) => { r.payload.capabilities.scientific_properties[0].populated_observations++; }],
    ["wrong property identity", (r: ScientificReceipt) => { r.payload.rows[0].cells[0].observations[0].property.id = crypto.randomUUID(); }],
    ["wrong state identity", (r: ScientificReceipt) => { r.payload.rows[0].cells[0].observations[0].state.id = crypto.randomUUID(); }],
    ["wrong structure identity", (r: ScientificReceipt) => { r.payload.rows[0].cells[0].observations[0].structure = null; }],
    ["wrong material identity", (r: ScientificReceipt) => { r.payload.rows[0].cells[0].observations[0].material.id = "other"; }],
    ["wrong pressure", (r: ScientificReceipt) => { r.payload.rows[0].cells[0].observations[0].state.pressure_gpa = 100; }],
    ["wrong representative", (r: ScientificReceipt) => { r.payload.rows[0].representative.id = "other"; }],
    ["wrong rationale", (r: ScientificReceipt) => { r.payload.rows[0].selection_rationale = "Changed after publication"; }],
    ["wrong profile", (r: ScientificReceipt) => { r.payload.rows[0].profile_assignment.mix = { flatband: 1 }; }],
    ["wrong policy", (r: ScientificReceipt) => { r.payload.policy_sha256 = "0".repeat(64); }],
    ["false nonphonon acceptance", (r: ScientificReceipt) => { r.payload.rows[0].cells[0].observations[0].scientific_scope_accepted = true; }],
    ["no narrow accepted result", (r: ScientificReceipt) => { for (const c of r.payload.rows[0].cells) for (const o of c.observations) {
      o.scientific_scope_accepted = false; for (const s of o.review.scopes) Object.assign(s, { decision: null, decision_id: null, decision_sha256: null,
        profile_version: null, effective_status: "unreviewed", scientific_scope_accepted: false });
    } }],
    ["negative band gap", (r: ScientificReceipt) => { r.payload.rows[0].cells[0].observations[0].quantity.value = -1; }],
    ["interval with exact value", (r: ScientificReceipt) => { r.payload.rows[0].cells[0].observations[0].quantity.relation = "interval"; }],
    ["locator over disclosure bound", (r: ScientificReceipt) => { r.payload.rows[0].cells[0].observations[0].sources[0].locator = { line: 1000001, start_byte: 0, end_byte: 1 }; }],
    ["invented source edge kind", (r: ScientificReceipt) => { (r.payload.rows[0].cells[0].observations[0].sources[0] as unknown as { link_type: string }).link_type = "input_event"; }],
    ["ambiguous source dependency", (r: ScientificReceipt) => { const s = r.payload.rows[0].cells[0].observations[0].sources[0];
      Object.assign(s, { link_type: "derives_from", artifact: null, input_event_id: crypto.randomUUID(), input_property_id: crypto.randomUUID(), input_claim_id: crypto.randomUUID() }); }],
    ["unreported zero imputation", (r: ScientificReceipt) => { r.payload.rows[0].cells[0].observations[0].quantity.relation = "unreported"; }],
    ["unranked number", (r: ScientificReceipt) => { r.payload.rows[0].assessment.result.eligibility = "pending"; }],
    ["nonanchor policy value", (r: ScientificReceipt) => { r.payload.rows[0].assessment.dimensions.stability.anchor = 51; }],
    ["global ML authority", (r: ScientificReceipt) => { (r.payload as unknown as { ml_training_approved: boolean }).ml_training_approved = true; }],
    ["extra undisclosed field", (r: ScientificReceipt) => { Object.assign(r.payload.rows[0], { private_rationale: "should never be displayed" }); }],
  ] as const)("rejects independently re-sealed malformed payload: %s", async (_name, mutate) => {
    const x = reseal(mutate); await expect(parseScientificReceipt(x.raw, x.selected)).rejects.toThrow(SCIENTIFIC_FAILURE);
  });
  it.each(["unknown", "not_computed", "not_applicable"] as const)("preserves explicit availability: %s", async status => {
    const x = reseal(r => setAbsent(r, status));
    const r = await parseScientificReceipt(x.raw, x.selected);
    expect(r.payload.rows[0].cells[0].availability).toBe(status);
    expect(r.payload.rows[0].cells[0].observations).toEqual([]);
  });
  it("preserves a typed derived property with both event and property IDs", async () => {
    const x = reseal(r => { const s = r.payload.rows[0].cells[0].observations[0].sources[0]; Object.assign(s, {
      link_type: "derives_from", artifact: null, input_event_id: crypto.randomUUID(), input_property_id: crypto.randomUUID(),
    }); });
    expect((await parseScientificReceipt(x.raw, x.selected)).payload.rows[0].cells[0].observations[0].sources[0].link_type).toBe("derives_from");
  });
  it.each([true, false])("retains every result, with declared conflict = %s", async conflicted => {
    const x = reseal(r => addSecondResult(r, conflicted));
    const checked = await parseScientificReceipt(x.raw, x.selected);
    expect(checked.payload.rows[0].cells[0].observations).toHaveLength(2);
    expect(checked.payload.rows[0].cells[0].availability).toBe(conflicted ? "conflicted" : "reported");
  });
  it("rejects a conflict incorrectly asserted across different components", async () => {
    const x = reseal(r => { addSecondResult(r, true); r.payload.rows[0].cells[0].observations[0].property.component_key = "different_component"; });
    await expect(parseScientificReceipt(x.raw, x.selected)).rejects.toThrow();
  });
  it("hashes Python float spellings and Unicode without JS reserialization", async () => {
    const x = reseal(r => { r.payload.campaign.objective = "δ — 中文 / synthetic only"; });
    let raw = x.raw;
    const payloadStart = raw.indexOf('"payload":') + '"payload":'.length;
    const payloadText = JSON.stringify(x.value.payload);
    // Change one exact scientific scalar's spelling while keeping its numeric value.
    const before = JSON.stringify(x.value.payload.rows[0].cells[0].observations[0].quantity.value);
    const replacements = ["1.0", "-0.0", "1e-05", "5e-324"];
    for (const spelling of replacements) {
      const nextPayload = payloadText.replace(`"value":${before}`, `"value":${spelling}`);
      const sha = checksum(nextPayload);
      raw = x.raw.slice(0, payloadStart) + nextPayload + x.raw.slice(payloadStart + payloadText.length);
      raw = raw.replace(x.selected.payload_sha256, sha);
      const selected = { ...x.selected, payload_sha256: sha };
      const result = await parseScientificReceipt(raw, selected);
      expect(result.payload.rows[0].cells[0].observations[0].quantity.value).toBe(Number(spelling));
      if (spelling === "-0.0") expect(Object.is(result.payload.rows[0].cells[0].observations[0].quantity.value, -0)).toBe(true);
    }
  });
  it.each([
    ["exact", 1e-12, null, null, "1e-12 eV"], ["exact", 0, null, null, "0 eV"],
    ["interval", null, 1e-12, 2e-12, "[1e-12, 2e-12] eV"], ["lt", null, null, 1e-8, "< 1e-8 eV"],
    ["le", null, null, 2, "≤ 2 eV"], ["gt", null, 2, null, "> 2 eV"], ["ge", null, 2, null, "≥ 2 eV"],
    ["unreported", null, null, null, "Unreported"],
  ] as const)("renders %s without inventing precision or imputing zero", (relation, value, lower, upper, expected) => {
    expect(scientificQuantity({ relation, value, lower, upper, unit: "eV" })).toBe(expected);
    expect(scientificNumber(null)).toBe("Unknown"); expect(scientificNumber(-0)).toBe("−0");
  });
});

describe("bounded public scientific client", () => {
  const actualClient = () => vi.importActual<typeof import("@/lib/discovery-scientific")>("@/lib/discovery-scientific");
  const response = (raw = fullWire) => new Response(raw, { headers: { "content-type": "application/json" } });
  it("uses public read-only no-store requests, no credentials or query, and parses exact raw bytes", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response()); vi.stubGlobal("fetch", fetchMock);
    const c = await actualClient(); const selected = catalog().items[0];
    expect((await c.getScientificProjection(selected)).package_id).toBe(selected.package_id);
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe(`${PUBLIC_API_BASE}/discovery/scientific/${selected.package_id}`);
    expect(new URL(url).search).toBe("");
    expect(options).toMatchObject({ method: "GET", credentials: "omit", cache: "no-store", redirect: "error" });
  });
  it.each([404, 409, 503])( "rejects HTTP %s with a static error", async status => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("private source reason", { status })));
    const c = await actualClient(); await expect(c.getScientificProjection(catalog().items[0])).rejects.toThrow(SCIENTIFIC_FAILURE);
  });
  it("rejects oversized declared bodies before reading", async () => {
    const read = vi.fn(); vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true,
      headers: new Headers({ "content-type": "application/json", "content-length": String(SCIENTIFIC_MAX_BYTES + 1) }), body: { getReader: read } }));
    const c = await actualClient(); await expect(c.getScientificProjection(catalog().items[0])).rejects.toThrow(); expect(read).not.toHaveBeenCalled();
  });
  it("rejects oversized streamed bodies even without content-length", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response("x".repeat(SCIENTIFIC_MAX_BYTES + 1))));
    const c = await actualClient(); await expect(c.getScientificProjection(catalog().items[0])).rejects.toThrow();
  });
  it("rejects malformed UTF-8 rather than silently replacing source bytes", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(new Uint8Array([0xc0, 0x80]), { headers: { "content-type": "application/json" } })));
    const c = await actualClient(); await expect(c.getScientificCatalog()).rejects.toThrow();
  });
  it("aborts a stalled request at the 60-second client deadline", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn((_url, options) => new Promise<Response>((_resolve, reject) => options.signal.addEventListener("abort", () => reject(new Error("aborted")))));
    vi.stubGlobal("fetch", fetchMock); const c = await actualClient();
    const result = expect(c.getScientificCatalog()).rejects.toThrow(SCIENTIFIC_FAILURE);
    await vi.advanceTimersByTimeAsync(60000); await result;
    expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(true);
  });
  it("checks caller cancellation after outstanding cryptographic verification", async () => {
    const gate = deferred<ArrayBuffer>(); const subtle = webcrypto.subtle;
    vi.stubGlobal("crypto", { subtle: { digest: vi.fn((algorithm, bytes) => gate.promise.then(() => subtle.digest(algorithm, bytes))) } });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response()));
    const c = await actualClient(), controller = new AbortController();
    const checking = c.getScientificProjection(catalog().items[0], controller.signal);
    const assertion = expect(checking).rejects.toThrow(SCIENTIFIC_FAILURE);
    await waitFor(() => expect(crypto.subtle.digest).toHaveBeenCalledTimes(3));
    controller.abort(); gate.resolve(new ArrayBuffer(0)); await assertion;
  });
});

describe("ScientificDiscoveryMatrix", () => {
  async function show(raw = fullWire, catalogRaw = fullCatalogWire) {
    const c = parseScientificCatalog(catalogRaw), r = await parseScientificReceipt(raw, c.items[0]);
    vi.mocked(getScientificCatalog).mockResolvedValue(c); vi.mocked(getScientificProjection).mockResolvedValue(r);
    render(<ScientificDiscoveryMatrix />);
    await screen.findByRole("option", { name: new RegExp(c.items[0].package_id) });
    expect(getScientificProjection).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Published scientific version"), { target: { value: c.items[0].package_id } });
    await screen.findByRole("table"); return r;
  }
  it("does not select a latest version or make up materials for an empty catalog", async () => {
    const c = catalog(); c.items = []; c.status = "not_published";
    vi.mocked(getScientificCatalog).mockResolvedValue(c); render(<ScientificDiscoveryMatrix />);
    expect(await screen.findByText(/No scientific companion published yet/)).toBeVisible();
    expect(screen.getByText(SCIENTIFIC_DISCLAIMER)).toBeVisible();
    expect(screen.queryByRole("table")).not.toBeInTheDocument(); expect(getScientificProjection).not.toHaveBeenCalled();
  });
  it("shows exactly one material row, scientific units, scope limits, and all eight selectable fields", async () => {
    await show(); const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(2);
    expect(within(table).getByText("7,100")).toBeVisible();
    expect(within(table).getByText("Main barrier not separately declared")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Scientific columns"), { target: { value: "all" } });
    expect(within(table).getByRole("columnheader", { name: /DOS at Fermi level states\/eV\/formula_unit/ })).toBeVisible();
    expect(within(table).getByRole("columnheader", { name: /Superfluid stiffness K/ })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "TEST" }));
    expect(screen.getByRole("heading", { name: "TEST · scientific record" })).toHaveFocus();
    const details = screen.getByRole("region", { name: "TEST scientific details" });
    expect(within(details).getAllByText(/Accepted · sampled phonon minimum only/).length).toBe(1);
    expect(within(details).getAllByText("Unreviewed scientific result")).toHaveLength(7);
    expect(within(details).getAllByText(/not establish full-zone dynamical stability/)).toHaveLength(8);
    expect(within(details).getAllByText("Event revision")).toHaveLength(8);
    expect(screen.getByRole("link", { name: "Evaluation and calibration limits" })).toHaveAttribute("href", "https://github.com/JackZH26/SCLib_JZIS/issues/78");
    fireEvent.click(screen.getByRole("button", { name: "Close details" }));
    expect(screen.getByRole("button", { name: "TEST" })).toHaveFocus();
  });
  it("does not replace the explicit 4400 representative with its 7100 alternative", async () => {
    await show(lowerWire, lowerCatalogWire);
    expect(within(screen.getByRole("table")).getByText("4,400")).toBeVisible();
    expect(within(screen.getByRole("table")).queryByText("7,100")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "TEST" }));
    expect(screen.getByText("Alternative research actions (1)")).toBeVisible();
    expect(screen.getByText(/Frozen policy assessment.*RPS 7,100/)).toBeVisible();
  });
  it("clears a previously visible publication immediately on refresh and hides a revoked response", async () => {
    await show(); const next = deferred<ReturnType<typeof catalog>>(); vi.mocked(getScientificCatalog).mockReturnValueOnce(next.promise);
    fireEvent.click(screen.getByRole("button", { name: "Refresh catalog" }));
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    await act(async () => next.reject(new Error("private revoked source")));
    expect(await screen.findByRole("alert")).toHaveTextContent(SCIENTIFIC_FAILURE);
    expect(screen.queryByText("private revoked source")).not.toBeInTheDocument();
  });
  it("rejects an old detail finishing after a newer selection, including post-hash completion", async () => {
    const a = catalog(), b = parseScientificCatalog(lowerCatalogWire), combined = { ...a, items: [...a.items, ...b.items].sort((x, y) => x.package_id.localeCompare(y.package_id, "en-US")) };
    vi.mocked(getScientificCatalog).mockResolvedValue(combined);
    const first = deferred<ScientificReceipt>(), second = deferred<ScientificReceipt>();
    vi.mocked(getScientificProjection).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    render(<ScientificDiscoveryMatrix />); await screen.findByRole("option", { name: new RegExp(a.items[0].package_id) });
    const selector = screen.getByLabelText("Published scientific version");
    fireEvent.change(selector, { target: { value: a.items[0].package_id } });
    const signal = vi.mocked(getScientificProjection).mock.calls[0][1]!;
    fireEvent.change(selector, { target: { value: b.items[0].package_id } }); expect(signal.aborted).toBe(true);
    await act(async () => second.resolve(await parseScientificReceipt(lowerWire, b.items[0])));
    expect(within(screen.getByRole("table")).getByText("4,400")).toBeVisible();
    await act(async () => first.resolve(await parseScientificReceipt(fullWire, a.items[0])));
    expect(within(screen.getByRole("table")).queryByText("7,100")).not.toBeInTheDocument();
  });
  it("clears on page hide and requires a newly selected publication after return", async () => {
    await show(); fireEvent(window, new Event("pagehide"));
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    fireEvent(window, Object.assign(new Event("pageshow"), { persisted: true }));
    await waitFor(() => expect(getScientificCatalog).toHaveBeenCalledTimes(2));
    expect(screen.getByLabelText("Published scientific version")).toHaveValue("");
    expect(getScientificProjection).toHaveBeenCalledTimes(1);
  });
  it("rechecks all pins after catalog refresh even for the same package UUID", async () => {
    const actual = await vi.importActual<typeof import("@/lib/discovery-scientific")>("@/lib/discovery-scientific");
    vi.mocked(getScientificCatalog).mockImplementation(actual.getScientificCatalog);
    vi.mocked(getScientificProjection).mockImplementation(actual.getScientificProjection);
    const changed = catalog(); changed.items[0].publication_sha256 = "a".repeat(64); changed.items[0].review_sha256 = "b".repeat(64);
    const response = (raw: string) => new Response(raw, { headers: { "content-type": "application/json" } });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(response(fullCatalogWire)).mockResolvedValueOnce(response(fullWire))
      .mockResolvedValueOnce(response(JSON.stringify(changed))).mockResolvedValueOnce(response(fullWire)));
    render(<ScientificDiscoveryMatrix />);
    await screen.findByRole("option", { name: new RegExp(changed.items[0].package_id) });
    fireEvent.change(screen.getByLabelText("Published scientific version"), { target: { value: changed.items[0].package_id } });
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: "Refresh catalog" }));
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    await screen.findByRole("option", { name: new RegExp(changed.items[0].package_id) });
    fireEvent.change(screen.getByLabelText("Published scientific version"), { target: { value: changed.items[0].package_id } });
    expect(await screen.findByRole("alert")).toHaveTextContent(SCIENTIFIC_FAILURE);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
  it.each([true, false])("does not collapse multiple component/results into a compact scalar; conflict = %s", async conflicted => {
    const x = reseal(r => addSecondResult(r, conflicted));
    const c = { ...catalog(), items: [x.selected] };
    await show(x.raw, JSON.stringify(c));
    fireEvent.change(screen.getByLabelText("Scientific columns"), { target: { value: "electronic" } });
    const table = screen.getByRole("table");
    expect(within(table).getByText("2 recorded results · expand to inspect all")).toBeVisible();
    expect(within(table).queryByText("0.25 eV")).not.toBeInTheDocument();
    if (conflicted) expect(within(table).getByText("Conflicted (declared)")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "TEST" }));
    const details = screen.getByRole("region", { name: "TEST scientific details" });
    expect(within(details).getByRole("heading", { name: /0.25 eV/, hidden: true })).toBeInTheDocument();
    expect(within(details).getByRole("heading", { name: /· 0 eV/, hidden: true })).toBeInTheDocument();
  });
  it("keeps controls separate and does not reinterpret a negative-control role as experimental data", async () => {
    const x = reseal(r => { const a = r.payload.rows[0].assessment; a.role = "negative_control"; a.rank = null;
      Object.assign(a.result, { eligibility: "reference_only", score_raw: null, score_display: null, score_upper: null }); });
    const r = await parseScientificReceipt(x.raw, x.selected), c = { ...catalog(), items: [x.selected] };
    vi.mocked(getScientificCatalog).mockResolvedValue(c); vi.mocked(getScientificProjection).mockResolvedValue(r);
    render(<ScientificDiscoveryMatrix />); await screen.findByRole("option", { name: new RegExp(x.selected.package_id) });
    fireEvent.change(screen.getByLabelText("Published scientific version"), { target: { value: x.selected.package_id } });
    expect(await screen.findByText(/No materials match this role/)).toBeVisible();
    fireEvent.change(screen.getByLabelText("Research role"), { target: { value: "controls" } });
    expect(await screen.findByRole("table")).toBeVisible();
    expect(screen.getByText(/does not mean experimentally nonsuperconducting/)).toBeVisible();
  });
});
