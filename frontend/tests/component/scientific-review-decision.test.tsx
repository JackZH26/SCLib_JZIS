import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ScientificReviewDecisionPanel } from "@/components/ScientificReviewDecisionPanel";
import ScientificReviewPage from "@/app/dashboard/research/review/page";
import { ApiError, scientificAdjudicationCommit, scientificAdjudicationContext, scientificAdjudicationOutcome, scientificAdjudicationPreview,
  scientificReviewCapabilities, scientificReviewDossier, scientificReviewQueue } from "@/lib/api";
import { notifyAuthChange } from "@/lib/auth-session";
import { knownReviewQueue, type ReviewDossier, type ReviewQueueItem } from "@/lib/scientific-review";
import { currentScope, knownAdjudicationContext, knownAdjudicationPreview, knownAdjudicationReceipt, knownAdjudicationRequest,
  REVIEW_CHECKS, REVIEW_LIMITATIONS, REVIEW_PROFILES, type AdjudicationContext, type AdjudicationRequest,
  type AdjudicationPreview, type AdjudicationReceipt } from "@/lib/scientific-review-decision";
import http from "../fixtures/scientific-review-http.json";
import adjudicationHttp from "../fixtures/scientific-adjudication-http.json";

vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(),
  scientificAdjudicationContext: vi.fn(), scientificAdjudicationPreview: vi.fn(),
  scientificAdjudicationCommit: vi.fn(), scientificAdjudicationOutcome: vi.fn(),
  scientificReviewCapabilities: vi.fn(), scientificReviewQueue: vi.fn(), scientificReviewDossier: vi.fn() }));
const id = (n: number) => "00000000-0000-4000-8000-" + n.toString().padStart(12, "0");
const hash = (letter = "a") => letter.repeat(64);
const profile = "native-sampled-frequency-extraction/1.0.0" as const;
function item(n = 1): ReviewQueueItem {
  return { property_id: id(n), event_id: id(n + 100), event_revision: 1, material_id: "synthetic:" + n,
    formula: "AlAs", property_key: "phonon_min_frequency", unit: "THz", knowledge_origin: "Computed", review_status: "pending", validity_status: "pending" };
}
function evidence(selected: ReviewQueueItem, n: number): ReviewDossier {
  const value = structuredClone(http.dossier) as ReviewDossier;
  value.target = { property_id: selected.property_id, event_id: selected.event_id, event_revision: selected.event_revision };
  value.material = { id: selected.material_id, formula: selected.formula };
  value.result.property_key = selected.property_key; value.result.unit = selected.unit;
  value.event = { ...value.event, knowledge_origin: selected.knowledge_origin, review_status: selected.review_status, validity_status: selected.validity_status };
  value.sources = [{ artifact_id: id(300 + n), kind: "other", access: "restricted", hash_status: "verified", bytes_sha256: hash("c"),
    evidence_link_ids: [id(400 + n)], locators: [{ line: 3, start_byte: 51, end_byte: 58 }] }];
  value.inventory = { row_count: 8, artifact_count: 1, sha256: hash("b") };
  value.impact = { version: "scientific-result-impact/1.0.0", scope: ["exact_property_relations"], unsupported_scopes: ["automatic_publication"],
    complete_for_scope: true, counts: { total_nodes: 0, total_relations: 0 }, items: [] };
  return value;
}
function context(items = [item()]): AdjudicationContext {
  return { version: "scientific-adjudication-context/1.0.0", actor_user_id: id(900), actor_grant_id: id(901), can_review: true, max_items: 20,
    targets: items.map((selected, n) => ({ property_id: selected.property_id, event_id: selected.event_id, event_revision: selected.event_revision,
      subject_id: id(200 + n), subject_sha256: hash(), impact_sha256: hash("b"),
      available_profiles: [profile, "sampled-phonon-minimum-review/1.0.0"],
      required_artifacts: [{ artifact_id: id(300 + n), bytes_sha256: hash("c") }],
      heads: [{ scope: "extraction_fidelity", decision_id: null }, { scope: "scientific_result", decision_id: null }],
      status: { version: "scientific-result-review-status/1.0.0", property_id: selected.property_id, subject_sha256: hash(),
        scopes: (["extraction_fidelity", "scientific_result"] as const).map(scope => ({ scope, profile_version: null,
          decision_id: null, decision_sha256: null, decision: null, effective_status: "unreviewed", reason_codes: [], scientific_scope_accepted: false })),
        revision_sha256: hash("d"), ml_training_approved: false, public_release_authorized: false },
      impact: evidence(selected, n).impact, dossier: evidence(selected, n), reason_codes: [] })),
  };
}
function request(ctx = context()): AdjudicationRequest {
  return { version: "scientific-result-adjudication/1.0.0", request_key: "synthetic:request-1",
    items: ctx.targets.map((target, n) => ({ decision_id: id(500 + n), subject_id: target.subject_id, property_id: target.property_id,
      scope: "extraction_fidelity", profile_version: profile, expected_subject_sha256: target.subject_sha256,
      expected_previous_decision_id: null, expected_impact_sha256: target.impact_sha256,
      decision: "request_clarification", reason_code: "insufficient_evidence", rationale: "Synthetic review: the method remains unresolved.",
      proposition: REVIEW_PROFILES[profile].proposition, limitations: [...REVIEW_LIMITATIONS],
      checks: { source_match: "unresolved", quantity_and_units: "unresolved", state_association: "unresolved", method_and_scope: "unresolved" },
      evidence_refs: [], source_inspection_attested: false, resolves_decision_id: null, extraction_decision_id: null })) };
}
function preview(body = request(), ctx = context()): AdjudicationPreview {
  return { version: "scientific-adjudication-preview/1.0.0", actor_user_id: ctx.actor_user_id, actor_grant_id: ctx.actor_grant_id!,
    request_key: body.request_key, request_sha256: hash("e"), preview_sha256: hash("f"), can_commit: true,
    items: body.items.map(row => ({ decision_id: row.decision_id, subject_id: row.subject_id, property_id: row.property_id, scope: row.scope,
      profile_version: row.profile_version, decision: row.decision, subject_sha256: row.expected_subject_sha256,
      expected_previous_decision_id: row.expected_previous_decision_id, impact_sha256: row.expected_impact_sha256 })),
    database_mutated: false, ml_training_approved: false, public_release_authorized: false };
}
function receipt(body = request(), prev = preview(body)): AdjudicationReceipt {
  return { version: "scientific-adjudication-receipt/1.0.0", request_id: id(950), request_key: body.request_key,
    request_sha256: prev.request_sha256, preview_sha256: prev.preview_sha256, committed: true, replayed: false,
    items: body.items.map(row => ({ decision_id: row.decision_id, subject_id: row.subject_id, property_id: row.property_id,
      scope: row.scope, profile_version: row.profile_version, decision: row.decision, decision_sha256: hash("b") })),
    ml_training_approved: false, public_release_authorized: false };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve };
}
function mount(items = [item()]) {
  const onInvalidate = vi.fn(), onBusyChange = vi.fn();
  const rendered = render(<ScientificReviewDecisionPanel selected={items} onInvalidate={onInvalidate} onBusyChange={onBusyChange} />);
  return { ...rendered, onInvalidate, onBusyChange };
}
async function fillClarification(items = [item()]) {
  for (const selected of items) fireEvent.change(await screen.findByLabelText("Profile for " + selected.property_id), { target: { value: profile } });
  fireEvent.change(screen.getByLabelText(/Shared rationale/), { target: { value: "Synthetic reviewer note: upstream method remains unknown." } });
}
async function prepare() {
  await fillClarification();
  fireEvent.click(screen.getByRole("button", { name: "Preview complete request" }));
  return screen.findByRole("heading", { name: "Exact request preview · no database mutation" });
}
describe("exact-property review component", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(scientificAdjudicationContext).mockResolvedValue(context());
    vi.mocked(scientificAdjudicationPreview).mockImplementation(async body => preview(body));
    vi.mocked(scientificAdjudicationCommit).mockImplementation(async body => receipt(body));
    vi.mocked(scientificAdjudicationOutcome).mockResolvedValue(receipt());
  });
  it("admits the actual disposable SQL-to-HTTP context, request, preview and committed receipt", () => {
    const dossier = adjudicationHttp.context.targets[0].dossier;
    const selected: ReviewQueueItem = { ...dossier.target, material_id: dossier.material.id, formula: dossier.material.formula,
      property_key: dossier.result.property_key, unit: dossier.result.unit, knowledge_origin: "Computed", review_status: "pending", validity_status: "pending" };
    const ctx = knownAdjudicationContext(adjudicationHttp.context, [selected]);
    expect(ctx).not.toBeNull();
    const body = knownAdjudicationRequest(adjudicationHttp.request, ctx!);
    expect(body).not.toBeNull();
    const prev = knownAdjudicationPreview(adjudicationHttp.preview, body!, ctx!);
    expect(prev).not.toBeNull();
    expect(knownAdjudicationReceipt(adjudicationHttp.receipt, body!, prev!)).not.toBeNull();
  });
  it("renders same-snapshot evidence from the actual HTTP context without treating the extraction as DFPT", async () => {
    const dossier = adjudicationHttp.context.targets[0].dossier;
    const selected: ReviewQueueItem = { ...dossier.target, material_id: dossier.material.id, formula: dossier.material.formula,
      property_key: dossier.result.property_key, unit: dossier.result.unit, knowledge_origin: "Computed", review_status: "pending", validity_status: "pending" };
    vi.mocked(scientificAdjudicationContext).mockResolvedValue(adjudicationHttp.context);
    mount([selected]);
    await screen.findByLabelText("Profile for " + selected.property_id);
    expect(screen.getByText("phonon min frequency: -0.0299792458 THz")).toBeVisible();
    expect(screen.getByText(/producer is extraction not native calculation/)).toBeVisible();
    expect(screen.getByText(/same server read snapshot|one server read snapshot/)).toBeVisible();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(scientificAdjudicationPreview).not.toHaveBeenCalled();
  });
  it("checks a real action context and never auto-previews or commits", async () => {
    const pending = deferred<unknown>(); vi.mocked(scientificAdjudicationContext).mockReturnValue(pending.promise);
    mount();
    expect(scientificAdjudicationContext).toHaveBeenCalledWith([id(1)], expect.any(AbortSignal));
    expect(scientificAdjudicationPreview).not.toHaveBeenCalled();
    await act(async () => pending.resolve(context()));
    await screen.findByLabelText("Profile for " + id(1));
    expect(scientificAdjudicationCommit).not.toHaveBeenCalled();
    expect(screen.getByText(/Unknown pressure, temperature and method remain unknown/)).toBeVisible();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
  it("requires explicit profile and rationale before previewing", async () => {
    mount(); fireEvent.click(await screen.findByRole("button", { name: "Preview complete request" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Complete every selected profile");
    expect(scientificAdjudicationPreview).not.toHaveBeenCalled();
  });
  it("commits only the exact successful preview and then checks current status separately", async () => {
    mount(); await prepare();
    expect(scientificAdjudicationCommit).not.toHaveBeenCalled();
    const body = vi.mocked(scientificAdjudicationPreview).mock.calls[0][0];
    expect(body.items[0].checks.method_and_scope).toBe("unresolved");
    expect(body.items[0].source_inspection_attested).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Commit exactly these 1 decisions" }));
    await screen.findByRole("heading", { name: "Committed review receipt · historical record" });
    expect(scientificAdjudicationCommit).toHaveBeenCalledWith(body, hash("f"), expect.any(AbortSignal));
    await waitFor(() => expect(scientificAdjudicationContext).toHaveBeenCalledTimes(2));
    expect(screen.getByText(/receipt is not a current scientific-approval badge/)).toBeVisible();
  });
  it("warns before browser unload only while the original write outcome is unresolved", async () => {
    const write = deferred<unknown>();
    vi.mocked(scientificAdjudicationCommit).mockReturnValue(write.promise);
    mount(); await prepare();
    const idle = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(idle);
    expect(idle.defaultPrevented).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Commit exactly these 1 decisions" }));
    const busy = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(busy);
    expect(busy.defaultPrevented).toBe(true);
    expect(screen.getByText(/Recovery information is held only in memory/)).toBeVisible();
    const body = vi.mocked(scientificAdjudicationCommit).mock.calls[0][0];
    await act(async () => write.resolve(receipt(body)));
    await screen.findByRole("heading", { name: "Committed review receipt · historical record" });
    const completed = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(completed);
    expect(completed.defaultPrevented).toBe(false);
  });
  it.each(["rationale", "scope", "decision", "reason", "check"])("invalidates a preview when %s changes", async field => {
    mount(); await prepare();
    if (field === "rationale") fireEvent.change(screen.getByLabelText(/Shared rationale/), { target: { value: "A different explicit rationale with sufficient length." } });
    if (field === "scope") fireEvent.change(screen.getByLabelText("Review scope"), { target: { value: "scientific_result" } });
    if (field === "decision") fireEvent.change(screen.getByLabelText("Decision"), { target: { value: "reject" } });
    if (field === "reason") fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "unresolved_method" } });
    if (field === "check") fireEvent.change(screen.getByLabelText("source match · " + id(1)), { target: { value: "satisfied" } });
    expect(screen.queryByRole("button", { name: /Commit exactly/ })).not.toBeInTheDocument();
    expect(scientificAdjudicationCommit).not.toHaveBeenCalled();
  });
  it("requires every acceptance check and source attestation to be chosen by the reviewer", async () => {
    mount(); await screen.findByLabelText("Decision");
    fireEvent.change(screen.getByLabelText("Decision"), { target: { value: "accept" } });
    await fillClarification();
    for (const checkbox of screen.getAllByRole("checkbox", { hidden: true })) expect(checkbox).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Preview complete request" }));
    expect(scientificAdjudicationPreview).not.toHaveBeenCalled();
    for (const check of REVIEW_CHECKS) fireEvent.change(screen.getByLabelText(check.replaceAll("_", " ") + " · " + id(1)), { target: { value: "satisfied" } });
    fireEvent.click(screen.getByText(/Required retained artifact references/));
    fireEvent.click(screen.getByLabelText(/I inspected artifact/));
    fireEvent.click(screen.getByLabelText(/I attest that I inspected/));
    fireEvent.click(screen.getByRole("button", { name: "Preview complete request" }));
    await screen.findByRole("heading", { name: /Exact request preview/ });
    const body = vi.mocked(scientificAdjudicationPreview).mock.calls[0][0];
    expect(body.items[0].evidence_refs).toEqual(context().targets[0].required_artifacts);
    expect(Object.values(body.items[0].checks)).toEqual(["satisfied", "satisfied", "satisfied", "satisfied"]);
  });
  it("does not infer write capability from read-only curator access", async () => {
    vi.mocked(scientificAdjudicationContext).mockResolvedValue({ ...context(), can_review: false, actor_grant_id: null });
    mount(); expect(await screen.findByText(/no current reviewer grant permits these writes/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Preview complete request" })).toBeDisabled();
  });
  it("keeps unsupported targets explicit and never drops them from a batch", async () => {
    const ctx = context([item(1), item(2)]); ctx.targets[1].available_profiles = [];
    vi.mocked(scientificAdjudicationContext).mockResolvedValue(ctx);
    mount([item(1), item(2)]);
    expect(await screen.findByText(/no supported profile/)).toBeVisible();
    await fillClarification([item()]);
    fireEvent.click(screen.getByRole("button", { name: "Preview complete request" }));
    expect(scientificAdjudicationPreview).not.toHaveBeenCalled();
  });
  it.each([401, 403, 409, 503])("clears preview and evidence after refusal %s", async status => {
    vi.mocked(scientificAdjudicationPreview).mockRejectedValue(new ApiError(status, { secret: "PRIVATE_SOURCE" }, "PRIVATE_SOURCE"));
    const view = mount(); await fillClarification(); fireEvent.click(screen.getByRole("button", { name: "Preview complete request" }));
    await waitFor(() => expect(view.onInvalidate).toHaveBeenCalledWith(false));
    expect(screen.queryByLabelText(/Shared rationale/)).not.toBeInTheDocument();
    expect(screen.queryByText(/PRIVATE_SOURCE/)).not.toBeInTheDocument();
  });
  it("treats timeout as unknown, does not retry writes, and checks the same request read-only", async () => {
    vi.mocked(scientificAdjudicationCommit).mockRejectedValue(new ApiError(0, null, "PRIVATE_NETWORK"));
    const view = mount(); await prepare();
    const body = vi.mocked(scientificAdjudicationPreview).mock.calls[0][0];
    vi.mocked(scientificAdjudicationOutcome).mockResolvedValue(receipt(body));
    fireEvent.click(screen.getByRole("button", { name: "Commit exactly these 1 decisions" }));
    await screen.findByRole("button", { name: "Check outcome" });
    expect(view.onInvalidate).toHaveBeenCalledWith(true);
    expect(screen.queryByLabelText(/Shared rationale/)).not.toBeInTheDocument();
    expect(scientificAdjudicationCommit).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Check outcome" }));
    await screen.findByRole("heading", { name: /Committed review receipt/ });
    expect(scientificAdjudicationOutcome).toHaveBeenCalledWith(body.request_key, expect.any(AbortSignal));
    expect(scientificAdjudicationCommit).toHaveBeenCalledTimes(1);
  });
  it("bounds a stalled context request and discards its late response", async () => {
    const pendingContext = deferred<unknown>();
    vi.mocked(scientificAdjudicationContext).mockReturnValue(pendingContext.promise);
    vi.useFakeTimers();
    try {
      const view = mount();
      await act(async () => vi.advanceTimersByTimeAsync(30_001));
      expect(view.onInvalidate).toHaveBeenCalledWith(false);
      expect(vi.mocked(scientificAdjudicationContext).mock.calls[0][1]!.aborted).toBe(true);
      await act(async () => pendingContext.resolve(context()));
      expect(screen.queryByLabelText(/Shared rationale/)).not.toBeInTheDocument();
    } finally { vi.useRealTimers(); }
  });
  it("bounds a stalled preview without accepting its late successful response", async () => {
    const pendingPreview = deferred<unknown>();
    vi.mocked(scientificAdjudicationPreview).mockReturnValue(pendingPreview.promise);
    const view = mount(); await fillClarification();
    vi.useFakeTimers();
    try {
      fireEvent.click(screen.getByRole("button", { name: "Preview complete request" }));
      const body = vi.mocked(scientificAdjudicationPreview).mock.calls[0][0];
      await act(async () => vi.advanceTimersByTimeAsync(30_001));
      expect(view.onInvalidate).toHaveBeenCalledWith(false);
      await act(async () => pendingPreview.resolve(preview(body)));
      expect(screen.queryByRole("button", { name: /Commit exactly/ })).not.toBeInTheDocument();
    } finally { vi.useRealTimers(); }
  });
  it("bounds stalled commit and recovery reads while retaining the same unresolved request", async () => {
    const write = deferred<unknown>(), read = deferred<unknown>();
    vi.mocked(scientificAdjudicationCommit).mockReturnValue(write.promise);
    vi.mocked(scientificAdjudicationOutcome).mockReturnValue(read.promise);
    const view = mount(); await prepare();
    const body = vi.mocked(scientificAdjudicationPreview).mock.calls[0][0];
    vi.useFakeTimers();
    try {
      fireEvent.click(screen.getByRole("button", { name: "Commit exactly these 1 decisions" }));
      await act(async () => vi.advanceTimersByTimeAsync(30_001));
      expect(view.onInvalidate).toHaveBeenCalledWith(true);
      expect(screen.getByRole("button", { name: "Check outcome" })).toBeEnabled();
      await act(async () => write.resolve(receipt(body)));
      expect(screen.queryByRole("heading", { name: /Committed review receipt/ })).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Check outcome" }));
      await act(async () => vi.advanceTimersByTimeAsync(30_001));
      expect(screen.getByRole("button", { name: "Check outcome" })).toBeEnabled();
      expect(screen.getByRole("alert")).toHaveTextContent("No write was retried");
      await act(async () => read.resolve(receipt(body)));
      expect(screen.queryByRole("heading", { name: /Committed review receipt/ })).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Check outcome" }));
      await act(async () => {});
      expect(scientificAdjudicationOutcome).toHaveBeenCalledTimes(2);
      for (const call of vi.mocked(scientificAdjudicationOutcome).mock.calls) expect(call[0]).toBe(body.request_key);
      expect(scientificAdjudicationCommit).toHaveBeenCalledTimes(1);
    } finally { vi.useRealTimers(); }
  });
  it("does not treat missing outcome as proof of rollback or permission to re-submit", async () => {
    vi.mocked(scientificAdjudicationCommit).mockRejectedValue(new ApiError(503, null, "unavailable"));
    vi.mocked(scientificAdjudicationOutcome).mockRejectedValue(new ApiError(404, null, "not found"));
    mount(); await prepare(); fireEvent.click(screen.getByRole("button", { name: "Commit exactly these 1 decisions" }));
    fireEvent.click(await screen.findByRole("button", { name: "Check outcome" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("not proof that the original request cannot still complete");
    expect(scientificAdjudicationCommit).toHaveBeenCalledTimes(1);
  });
  it("withdraws a late preview on session change", async () => {
    const pending = deferred<unknown>(); vi.mocked(scientificAdjudicationPreview).mockReturnValue(pending.promise);
    const view = mount(); await fillClarification(); fireEvent.click(screen.getByRole("button", { name: "Preview complete request" }));
    const body = vi.mocked(scientificAdjudicationPreview).mock.calls[0][0];
    act(() => notifyAuthChange());
    await act(async () => pending.resolve(preview(body)));
    expect(view.onInvalidate).toHaveBeenCalledWith(false);
    expect(screen.queryByRole("button", { name: /Commit exactly/ })).not.toBeInTheDocument();
  });
  it("ignores a previous target's late preview after explicit selection changes", async () => {
    const old = deferred<unknown>(); vi.mocked(scientificAdjudicationPreview).mockReturnValue(old.promise);
    vi.mocked(scientificAdjudicationContext).mockResolvedValueOnce(context()).mockResolvedValueOnce(context([item(2)]));
    const view = mount(); await fillClarification(); fireEvent.click(screen.getByRole("button", { name: "Preview complete request" }));
    const body = vi.mocked(scientificAdjudicationPreview).mock.calls[0][0];
    view.rerender(<ScientificReviewDecisionPanel selected={[item(2)]} onInvalidate={view.onInvalidate} onBusyChange={view.onBusyChange} />);
    await screen.findByLabelText("Profile for " + id(2));
    await act(async () => old.resolve(preview(body)));
    expect(screen.queryByRole("button", { name: /Commit exactly/ })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Profile for " + id(1))).not.toBeInTheDocument();
  });
  it("treats a malformed commit receipt as unknown rather than success", async () => {
    vi.mocked(scientificAdjudicationCommit).mockResolvedValue({ committed: true, ml_training_approved: true });
    mount(); await prepare(); fireEvent.click(screen.getByRole("button", { name: "Commit exactly these 1 decisions" }));
    await screen.findByRole("button", { name: "Check outcome" });
    expect(screen.queryByRole("heading", { name: /Committed review receipt/ })).not.toBeInTheDocument();
    expect(scientificAdjudicationCommit).toHaveBeenCalledTimes(1);
  });
  it("clears a historical receipt if the fresh context belongs to a different session actor", async () => {
    vi.mocked(scientificAdjudicationContext).mockResolvedValueOnce(context()).mockResolvedValueOnce({ ...context(), actor_user_id: id(999) });
    const view = mount(); await prepare(); fireEvent.click(screen.getByRole("button", { name: "Commit exactly these 1 decisions" }));
    await waitFor(() => expect(view.onInvalidate).toHaveBeenCalledWith(false));
    expect(screen.queryByRole("heading", { name: /Committed review receipt/ })).not.toBeInTheDocument();
  });
});

describe("strict adjudication wire", () => {
  it("accepts the exact non-public request, preview and historical receipt", () => {
    expect(knownAdjudicationContext(context(), [item()])).not.toBeNull();
    expect(knownAdjudicationRequest(request(), context())).not.toBeNull();
    expect(knownAdjudicationPreview(preview(), request(), context())).not.toBeNull();
    expect(knownAdjudicationReceipt(receipt(), request(), preview())).not.toBeNull();
  });
  it.each([
    (c: AdjudicationContext) => { c.targets[0].event_revision++; },
    (c: AdjudicationContext) => { c.targets[0].subject_sha256 = hash("f"); },
    (c: AdjudicationContext) => { c.targets[0].heads[0].decision_id = id(501); },
    (c: AdjudicationContext) => { c.targets[0].status.scopes[0].scientific_scope_accepted = true; },
    (c: AdjudicationContext) => { c.targets[0].status.ml_training_approved = true as false; },
    (c: AdjudicationContext) => { c.actor_grant_id = null; },
    (c: AdjudicationContext) => { c.can_review = 1 as unknown as boolean; },
    (c: AdjudicationContext) => { c.targets[0].required_artifacts.push(c.targets[0].required_artifacts[0]); },
    (c: AdjudicationContext) => { c.targets[0].available_profiles = ["unknown" as typeof profile]; },
    (c: AdjudicationContext) => { Object.assign(c.targets[0], { source_text: "PRIVATE" }); },
    (c: AdjudicationContext) => { c.targets[0].dossier.target.property_id = id(999); },
    (c: AdjudicationContext) => { c.targets[0].dossier.material.formula = "STALE"; },
    (c: AdjudicationContext) => { c.targets[0].dossier.sources[0].bytes_sha256 = hash("f"); },
    (c: AdjudicationContext) => { c.targets[0].dossier.impact.scope = ["different_scope"]; },
  ])("rejects context inconsistencies %#", mutate => {
    const c = context(); mutate(c); expect(knownAdjudicationContext(c, [item()])).toBeNull();
  });
  it.each([
    (r: AdjudicationRequest) => { r.items[0].expected_subject_sha256 = hash("f"); },
    (r: AdjudicationRequest) => { r.items[0].expected_impact_sha256 = hash("f"); },
    (r: AdjudicationRequest) => { r.items[0].scope = "scientific_result"; },
    (r: AdjudicationRequest) => { r.items[0].rationale = "too short"; },
    (r: AdjudicationRequest) => { r.items[0].rationale = "x".repeat(2001); },
    (r: AdjudicationRequest) => { r.items[0].rationale += "\u0085"; },
    (r: AdjudicationRequest) => { r.items[0].limitations.reverse(); },
    (r: AdjudicationRequest) => { r.items[0].reason_code = "scientific_concern"; },
    (r: AdjudicationRequest) => { r.items[0].source_inspection_attested = 1 as unknown as boolean; },
    (r: AdjudicationRequest) => { r.items[0].decision = "accept"; r.items[0].reason_code = "evidence_and_scope_match"; },
    (r: AdjudicationRequest) => { r.items[0].evidence_refs = [{ artifact_id: id(999), bytes_sha256: hash() }]; },
    (r: AdjudicationRequest) => { Object.assign(r.items[0], { actor_user_id: id(900) }); },
  ])("rejects altered request scope, pins or authority %#", mutate => {
    const r = request(); mutate(r); expect(knownAdjudicationRequest(r, context())).toBeNull();
  });
  it("supports 20 unique explicit targets but rejects 21 and duplicate IDs", () => {
    const rows = Array.from({ length: 20 }, (_, n) => item(n + 1));
    const ctx = context(rows);
    expect(knownAdjudicationContext(ctx, rows)).not.toBeNull();
    expect(knownAdjudicationRequest(request(ctx), ctx)).not.toBeNull();
    const tooMany = [...rows, item(21)];
    expect(knownAdjudicationContext(context(tooMany), tooMany)).toBeNull();
    expect(knownAdjudicationContext(context([item(), item()]), [item(), item()])).toBeNull();
  });
  it("rejects reordered preview and receipt items rather than mixing subjects", () => {
    const ctx = context([item(1), item(2)]), r = request(ctx), p = preview(r, ctx), committed = receipt(r, p);
    const reordered = structuredClone(p); reordered.items.reverse();
    expect(knownAdjudicationPreview(reordered, r, ctx)).toBeNull();
    committed.items.reverse();
    expect(knownAdjudicationReceipt(committed, r, p)).toBeNull();
  });
  it("preserves multilingual reviewer prose and rejects unpaired UTF-16 surrogates", () => {
    const r = request(); r.items[0].rationale = "这是保留原文的合成审核说明；条件与上游方法仍然未知，不代表实验或科学认可。";
    expect(knownAdjudicationRequest(r, context())).not.toBeNull();
    r.items[0].rationale += "\ud800";
    expect(knownAdjudicationRequest(r, context())).toBeNull();
  });
  it("requires exact current accepted fidelity and explicit negative-resolution pins", () => {
    const ctx = context(), r = request(ctx), target = ctx.targets[0];
    Object.assign(r.items[0], { scope: "scientific_result", profile_version: "sampled-phonon-minimum-review/1.0.0",
      proposition: "sampled_frequency_minimum_only", decision: "accept", reason_code: "evidence_and_scope_match",
      checks: Object.fromEntries(REVIEW_CHECKS.map(k => [k, "satisfied"])), source_inspection_attested: true,
      evidence_refs: target.required_artifacts, extraction_decision_id: id(600) });
    expect(knownAdjudicationRequest(r, ctx)).toBeNull();
    Object.assign(currentScope(target, "extraction_fidelity"), { profile_version: profile, decision_id: id(600), decision_sha256: hash(),
      decision: "accept", effective_status: "accepted" });
    target.heads[0].decision_id = id(600);
    expect(knownAdjudicationRequest(r, ctx)).not.toBeNull();
    Object.assign(currentScope(target, "scientific_result"), { profile_version: "sampled-phonon-minimum-review/1.0.0", decision_id: id(700),
      decision_sha256: hash(), decision: "reject", effective_status: "rejected" });
    r.items[0].expected_previous_decision_id = id(700);
    expect(knownAdjudicationRequest(r, ctx)).toBeNull();
    r.items[0].resolves_decision_id = id(700);
    expect(knownAdjudicationRequest(r, ctx)).not.toBeNull();
  });
  it.each(["actor", "head", "property", "scope", "count", "mutation", "extra"])("rejects preview mismatch %s", kind => {
    const p = preview();
    if (kind === "actor") p.actor_user_id = id(999);
    if (kind === "head") p.items[0].expected_previous_decision_id = id(999);
    if (kind === "property") p.items[0].property_id = id(999);
    if (kind === "scope") p.items[0].scope = "scientific_result";
    if (kind === "count") p.items = [];
    if (kind === "mutation") p.database_mutated = true as false;
    if (kind === "extra") Object.assign(p, { source_text: "PRIVATE" });
    expect(knownAdjudicationPreview(p, request(), context())).toBeNull();
  });
  it.each(["request", "preview", "decision", "scope", "count", "approval"])("rejects receipt mismatch %s", kind => {
    const value = receipt();
    if (kind === "request") value.request_sha256 = hash("a");
    if (kind === "preview") value.preview_sha256 = hash("a");
    if (kind === "decision") value.items[0].decision_id = id(999);
    if (kind === "scope") value.items[0].scope = "scientific_result";
    if (kind === "count") value.items = [];
    if (kind === "approval") value.ml_training_approved = true as false;
    expect(knownAdjudicationReceipt(value, request(), preview())).toBeNull();
  });
});

describe("page selection and private wrappers", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(scientificReviewCapabilities).mockResolvedValue(http.capabilities);
    vi.mocked(scientificReviewQueue).mockResolvedValue(http.queue);
    vi.mocked(scientificReviewDossier).mockResolvedValue(http.dossier);
  });
  it("does not open action context until a checkbox explicitly selects an exact property", async () => {
    const selected = knownReviewQueue(http.queue)!.items[0];
    vi.mocked(scientificAdjudicationContext).mockResolvedValue(context([selected]));
    render(<ScientificReviewPage />);
    fireEvent.click(await screen.findByRole("button", { name: /AlAs · phonon min frequency/ }));
    await screen.findByRole("heading", { name: /Exact result · AlAs/ });
    expect(scientificAdjudicationContext).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("checkbox", { name: /Select for review: AlAs/ }));
    expect(scientificAdjudicationContext).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Load review context for 1 selected results" }));
    await screen.findByLabelText("Profile for " + selected.property_id);
    expect(scientificAdjudicationContext).toHaveBeenCalledWith([selected.property_id], expect.any(AbortSignal));
    expect(screen.queryByRole("checkbox", { name: /select all/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh access" }));
    expect(screen.queryByRole("heading", { name: "Exact-property review" })).not.toBeInTheDocument();
  });
  it("caps explicit page selection at 20 and clears it on pagination without a request storm", async () => {
    const rows = Array.from({ length: 25 }, (_, n) => item(n + 1));
    vi.mocked(scientificReviewQueue).mockResolvedValueOnce({ ...http.queue, items: rows, has_more: true, next_cursor: id(25) })
      .mockResolvedValueOnce({ ...http.queue, items: [item(26)] });
    render(<ScientificReviewPage />);
    await screen.findByRole("button", { name: "Next page" });
    const boxes = screen.getAllByRole("checkbox", { name: /Select for review:/ });
    for (const checkbox of boxes.slice(0, 20)) fireEvent.click(checkbox);
    expect(screen.getByRole("button", { name: "Load review context for 20 selected results" })).toBeEnabled();
    expect(boxes[20]).toBeDisabled();
    expect(scientificAdjudicationContext).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(await screen.findByRole("button", { name: "Load review context for 0 selected results" })).toBeDisabled();
    expect(screen.queryByRole("heading", { name: "Exact-property review" })).not.toBeInTheDocument();
  });
  it("locks refresh, pagination and browsing controls until the original commit outcome is known", async () => {
    const selected = knownReviewQueue(http.queue)!.items[0];
    const ctx = context([selected]);
    vi.mocked(scientificReviewQueue).mockResolvedValue({ ...http.queue, has_more: true, next_cursor: selected.property_id });
    vi.mocked(scientificAdjudicationContext).mockResolvedValue(ctx);
    vi.mocked(scientificAdjudicationPreview).mockImplementation(async body => preview(body, ctx));
    const write = deferred<unknown>();
    vi.mocked(scientificAdjudicationCommit).mockReturnValue(write.promise);
    render(<ScientificReviewPage />);
    fireEvent.click(await screen.findByRole("checkbox", { name: /Select for review: AlAs/ }));
    fireEvent.click(screen.getByRole("button", { name: "Load review context for 1 selected results" }));
    await fillClarification([selected]);
    fireEvent.click(screen.getByRole("button", { name: "Preview complete request" }));
    fireEvent.click(await screen.findByRole("button", { name: "Commit exactly these 1 decisions" }));
    for (const name of ["Refresh access", "First page", "Next page"]) expect(screen.getByRole("button", { name })).toBeDisabled();
    expect(screen.getByRole("button", { name: /AlAs · phonon min frequency/ })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: /Select for review: AlAs/ })).toBeDisabled();
    await act(async () => write.resolve({ invalid: "outcome" }));
    expect(await screen.findByRole("button", { name: "Check outcome" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Refresh access" })).toBeDisabled();
    expect(scientificReviewCapabilities).toHaveBeenCalledTimes(1);
    expect(scientificAdjudicationCommit).toHaveBeenCalledTimes(1);
  });
  it("posts bounded JSON only and queries outcomes with encoded keys and credentialled no-store", async () => {
    const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
    const fetcher = vi.fn().mockImplementation(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    const controller = new AbortController(), r = request();
    try {
      await real.scientificAdjudicationContext([id(1)], controller.signal);
      await real.scientificAdjudicationPreview(r, controller.signal);
      await real.scientificAdjudicationCommit(r, hash("f"), controller.signal);
      await real.scientificAdjudicationOutcome("review:key/unsafe?", controller.signal);
      expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ property_ids: [id(1)] });
      expect(JSON.parse(fetcher.mock.calls[2][1].body)).toEqual({ request: r, expected_preview_sha256: hash("f") });
      expect(fetcher.mock.calls[3][0]).toContain("/requests/review%3Akey%2Funsafe%3F");
      for (const [, options] of fetcher.mock.calls) expect(options).toMatchObject({ credentials: "include", cache: "no-store", signal: controller.signal });
    } finally { vi.unstubAllGlobals(); }
  });
});
