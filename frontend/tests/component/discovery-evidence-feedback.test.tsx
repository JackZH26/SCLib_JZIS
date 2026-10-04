import { webcrypto } from "node:crypto";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DiscoveryEvidenceFeedback } from "@/components/DiscoveryEvidenceFeedback";
import { ApiError, discoveryDesignDetail, discoveryFeedbackCapabilities, discoveryFeedbackCommit, discoveryFeedbackContext, discoveryFeedbackOutcome, discoveryFeedbackPage, discoveryFeedbackPreview } from "@/lib/api";
import { notifyAuthChange } from "@/lib/auth-session";
import { expressionCanonical, expressionSha } from "@/lib/source-expressions";
import { nativeFeedbackWithChildDetail, syntheticChild, syntheticFeedbackReceipt, syntheticFeedbackWire } from "../fixtures/discovery-feedback.synthetic";
import type { FeedbackRequest } from "@/lib/discovery-feedback";

vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(), discoveryDesignDetail: vi.fn(), discoveryFeedbackCapabilities: vi.fn(), discoveryFeedbackContext: vi.fn(), discoveryFeedbackPreview: vi.fn(), discoveryFeedbackCommit: vi.fn(), discoveryFeedbackOutcome: vi.fn(), discoveryFeedbackPage: vi.fn() }));
beforeEach(() => { vi.resetAllMocks(); vi.stubGlobal("crypto", webcrypto); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const clone = <T,>(value: T): T => structuredClone(value);
async function setup(overrides: Partial<Parameters<typeof DiscoveryEvidenceFeedback>[0]> = {}, native = false) {
  const wire = native ? nativeFeedbackWithChildDetail() : await syntheticFeedbackWire();
  vi.mocked(discoveryFeedbackCapabilities).mockResolvedValue(clone(wire.cap));
  vi.mocked(discoveryFeedbackContext).mockResolvedValue(clone(wire.context));
  vi.mocked(discoveryFeedbackPage).mockResolvedValue(clone(wire.page));
  vi.mocked(discoveryFeedbackPreview).mockImplementation(request => syntheticFeedbackReceipt(request, wire.cap, wire.context.design, wire.context.projection_sha256));
  const onSaveDispatched = vi.fn(), onSaveResolved = vi.fn(), onStartLinkedProposal = vi.fn(), onOpenChild = vi.fn();
  const props = { capabilities: wire.designCapabilities, entry: wire.entry, onSaveDispatched, onSaveResolved, onStartLinkedProposal, onOpenChild, ...overrides };
  const rendered = render(<DiscoveryEvidenceFeedback {...props} />);
  await screen.findByRole("region", { name: "Pinned research action" });
  return { wire, props, ...rendered, onSaveDispatched, onSaveResolved, onStartLinkedProposal, onOpenChild };
}
async function loadEvidence() {
  fireEvent.change(screen.getByLabelText("Evidence material ID"), { target: { value: "synthetic-comparative-material" } });
  fireEvent.change(screen.getByLabelText("Evidence retained record index"), { target: { value: "2" } });
  fireEvent.click(screen.getByRole("button", { name: "Load exact evidence" }));
  await screen.findByRole("region", { name: "Existing retained evidence reading" });
}
async function previewReturn() {
  await loadEvidence();
  fireEvent.change(screen.getByLabelText("Findings from this source review"), { target: { value: "Source onset is retained; the Hc2 field has a distinct scope." } });
  fireEvent.change(screen.getByLabelText("Actual researcher decision"), { target: { value: "redirect" } });
  fireEvent.change(screen.getByLabelText("Reason for this decision"), { target: { value: "Sample relevance is unestablished." } });
  fireEvent.change(screen.getByLabelText("Remaining unknowns (one per line)"), { target: { value: "Physical relationship remains unknown" } });
  fireEvent.click(screen.getByRole("button", { name: "Preview evidence return" }));
  await screen.findByRole("region", { name: "Exact evidence preview" });
}

it("shows the pinned action/question and anticipated outcomes beside faithful criteria, methods and Hc2 scope", async () => {
  await setup(); await loadEvidence();
  const reading = within(screen.getByRole("region", { name: "Existing retained evidence reading" }));
  expect(screen.getByText("Does an existing comparative record resolve the requested criterion?")).toBeInTheDocument();
  expect(reading.getByText("onset")).toBeInTheDocument(); expect(reading.getByText("onset of resistive drop")).toBeInTheDocument(); expect(reading.getByText("rho onset")).toBeInTheDocument();
  expect(reading.getByText("primary_experimental")).toBeInTheDocument(); expect(reading.queryByText("Observed")).not.toBeInTheDocument();
  expect(reading.getByText("resistivity")).toBeInTheDocument(); expect(reading.getByText("four-probe")).toBeInTheDocument();
  expect(reading.getByText("65 T")).toBeInTheDocument(); expect(reading.getByText("Hc2 conditions: 0 K, extrapolation model not supplied")).toBeInTheDocument();
  expect(reading.getByRole("link", { name: "Open exact retained record" })).toHaveAttribute("href", "/materials/synthetic-comparative-material#retained-record-2");
  expect(reading.getByRole("link", { name: "Open source paper" })).toHaveAttribute("href", "/paper/synthetic-paper");
  expect(screen.getByText(/Cross-material references are allowed/)).toBeInTheDocument();
  expect(screen.getByText("Inspect exact design and action pins", { selector: "summary" }).closest("details")).not.toHaveAttribute("open");
  expect(screen.getByText("Inspect exact evidence projection and original value tokens", { selector: "summary" }).closest("details")).not.toHaveAttribute("open");
  expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]/);
  expect(discoveryFeedbackCommit).not.toHaveBeenCalled();
});

it("requires an actual researcher decision instead of defaulting to Continue", async () => {
  await setup(); await loadEvidence();
  expect(screen.getByLabelText("Actual researcher decision")).toHaveValue("");
  fireEvent.click(screen.getByRole("button", { name: "Preview evidence return" }));
  expect(screen.getByText("Choose your actual researcher decision before previewing the return.")).toBeInTheDocument();
  expect(discoveryFeedbackPreview).not.toHaveBeenCalled();
});

it("sends only an explicit association request and recovers a lost save receipt through GET without POST retry", async () => {
  const state = await setup(); await previewReturn();
  vi.mocked(discoveryFeedbackCommit).mockRejectedValue(new TypeError("connection lost after dispatch"));
  fireEvent.click(screen.getByRole("button", { name: "Save evidence association" }));
  await screen.findByRole("region", { name: "Original evidence save recovery" });
  expect(state.onSaveDispatched).toHaveBeenCalledTimes(1); expect(state.onSaveResolved).not.toHaveBeenCalled(); expect(discoveryFeedbackCommit).toHaveBeenCalledTimes(1);
  const request = vi.mocked(discoveryFeedbackCommit).mock.calls[0][0];
  expect(request.operation).toBe("return_evidence"); expect(request.payload).not.toHaveProperty("experiment_executed"); expect(request.payload).not.toHaveProperty("sample_id");
  expect(screen.queryByRole("region", { name: "Existing retained evidence reading" })).not.toBeInTheDocument();
  const preview = await syntheticFeedbackReceipt(request, state.wire.cap, state.wire.context.design, state.wire.context.projection_sha256);
  vi.mocked(discoveryFeedbackOutcome).mockResolvedValue({ ...preview, dry_run: false, pending_ledger_written: true, replayed: true });
  fireEvent.click(screen.getByRole("button", { name: "Check original evidence request" }));
  await screen.findByRole("region", { name: "Saved evidence receipt" });
  expect(discoveryFeedbackCommit).toHaveBeenCalledTimes(1); expect(discoveryFeedbackOutcome).toHaveBeenCalledWith(request.request_key, await expressionSha(expressionCanonical(request)), expect.any(AbortSignal));
  expect(state.onSaveResolved).toHaveBeenCalledWith(state.onSaveDispatched.mock.calls[0][0]);
});

it("shows source drift and researcher notes while withholding source numbers and new linked-proposal actions", async () => {
  const { wire } = await setup(), page = clone(wire.page);
  page.entries[0].eligibility = { eligible: false, reason_codes: ["design_revision_changed", "evidence_source_context_changed"] }; page.entries[0].projection = null; page.entries[0].projection_canonical_json = null;
  vi.mocked(discoveryFeedbackPage).mockResolvedValue(page);
  fireEvent.click(screen.getByRole("button", { name: "Load return history" }));
  const history = within(await screen.findByRole("region", { name: "Saved evidence return history" }));
  expect(history.getByText(wire.item.findings)).toBeInTheDocument(); expect(history.getByText(/design revision changed.*evidence source context changed/)).toBeInTheDocument();
  expect(history.queryByText("65 T")).not.toBeInTheDocument(); expect(history.queryByText("Inspect retained evidence readings")).not.toBeInTheDocument();
  expect(history.getByRole("button", { name: "Start proposal from return" })).toBeDisabled();
  expect(history.getByText("Inspect immutable return receipt", { selector: "summary" }).closest("details")).not.toHaveAttribute("open");
});

it("starts a linked draft from verified feedback and explicitly links only its saved initial child", async () => {
  const state = await setup(); fireEvent.click(screen.getByRole("button", { name: "Load return history" }));
  await screen.findByRole("region", { name: "Saved evidence return history" });
  fireEvent.click(screen.getByRole("button", { name: "Start proposal from return" }));
  const selection = state.onStartLinkedProposal.mock.calls[0][0];
  expect(selection).toEqual({ feedback: { id: state.wire.item.id, record_sha256: state.wire.item.record_sha256 }, design: state.wire.context.design });
  expect(discoveryFeedbackCommit).not.toHaveBeenCalled();
  state.rerender(<DiscoveryEvidenceFeedback {...state.props} followUpSelection={selection} savedChild={syntheticChild} />);
  fireEvent.click(screen.getByRole("button", { name: "Preview follow-up link" }));
  await screen.findByRole("region", { name: "Exact evidence preview" });
  const request = vi.mocked(discoveryFeedbackPreview).mock.calls.at(-1)![0] as FeedbackRequest;
  expect(request.operation).toBe("link_follow_up"); expect(request.payload).toEqual({ feedback: selection.feedback, child: syntheticChild });
  expect(discoveryFeedbackCommit).not.toHaveBeenCalled();
});

it("reloads an already-saved initial child from actual immutable proof without creating another design", async () => {
  const state = await setup({}, true), native = nativeFeedbackWithChildDetail();
  // Model the pre-link window while retaining the actual native return and child proofs.
  const page = clone(state.wire.page); page.entries[0].follow_ups = [];
  vi.mocked(discoveryFeedbackPage).mockResolvedValue(page);
  vi.mocked(discoveryDesignDetail).mockResolvedValue(native.childDetail);
  fireEvent.click(screen.getByRole("button", { name: "Load return history" }));
  await screen.findByRole("region", { name: "Saved evidence return history" });
  fireEvent.click(screen.getByRole("button", { name: "Start proposal from return" }));
  const selection = state.onStartLinkedProposal.mock.calls[0][0];
  state.rerender(<DiscoveryEvidenceFeedback {...state.props} followUpSelection={selection} savedChild={null} />);
  fireEvent.change(screen.getByLabelText("Existing child design ID"), { target: { value: native.childDetail.design_id } });
  fireEvent.click(screen.getByRole("button", { name: "Load saved child" }));
  await screen.findByText(/Existing initial child verified against the exact parent/);
  expect(discoveryDesignDetail).toHaveBeenCalledWith(native.childDetail.design_id, expect.any(AbortSignal));
  expect(screen.getByText("Inspect exact saved child pins", { selector: "summary" }).closest("details")).not.toHaveAttribute("open");
  expect(discoveryFeedbackPreview).not.toHaveBeenCalled(); expect(discoveryFeedbackCommit).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Preview follow-up link" }));
  await screen.findByRole("region", { name: "Exact evidence preview" });
  const request = vi.mocked(discoveryFeedbackPreview).mock.calls[0][0] as FeedbackRequest;
  expect(request.operation).toBe("link_follow_up"); expect(request.payload).toEqual({ feedback: selection.feedback, child: { design_id: native.childDetail.design_id, revision_id: native.childDetail.entries[0].id, record_sha256: native.childDetail.entries[0].record_sha256 } });
  expect(discoveryFeedbackCommit).not.toHaveBeenCalled();
});

it("renders decimal source values and original decimal proof tokens without an integer-only serializer", async () => {
  const { wire } = await setup(), context = clone(wire.context), projection = context.projection!;
  projection.record.tc_kelvin = 21.5;
  projection.record.scientific_values = { hc2_tesla: { raw_value: 65, input_unit: "T", raw_unit: "T", normalized_value: 65.25, normalized_unit: "T", status: "source_reported" } };
  context.projection_canonical_json = JSON.stringify(projection).replace('"raw_value":65', '"raw_value":65.0'); context.projection_sha256 = await expressionSha(context.projection_canonical_json);
  vi.mocked(discoveryFeedbackContext).mockResolvedValue(context); await loadEvidence();
  const reading = within(screen.getByRole("region", { name: "Existing retained evidence reading" }));
  expect(reading.getByText("21.5")).toBeInTheDocument();
  fireEvent.click(reading.getByText("Inspect exact evidence projection and original value tokens", { selector: "summary" }));
  expect(reading.getByText(context.projection_canonical_json, { selector: "pre" })).toBeInTheDocument();
  expect(context.projection_canonical_json).toContain('"raw_value":65.0'); expect(reading.queryByText("65.25 T")).not.toBeInTheDocument();
});

it("suppresses implied tesla after invalid unit withholding and never substitutes normalized values for raw tokens", async () => {
  const { wire } = await setup(), context = clone(wire.context), projection = context.projection!;
  projection.record.hc2_tesla_unit = null; projection.withheld_fields = ["hc2_tesla_unit"];
  projection.record.scientific_values = { tc_kelvin: { raw_value: "< 23", input_unit: "K", raw_unit: "K", normalized_value: 999, normalized_unit: "K", status: "unresolved" } };
  context.projection_canonical_json = expressionCanonical(projection); context.projection_sha256 = await expressionSha(context.projection_canonical_json);
  vi.mocked(discoveryFeedbackContext).mockResolvedValue(context); await loadEvidence();
  const reading = within(screen.getByRole("region", { name: "Existing retained evidence reading" }));
  expect(reading.getByText("65")).toBeInTheDocument(); expect(reading.queryByText("65 T")).not.toBeInTheDocument(); expect(reading.getByText("Unit metadata unresolved")).toBeInTheDocument();
  expect(reading.getByText("< 23")).toBeInTheDocument();
  expect(reading.getByText("Retained Tc source token")).toBeInTheDocument();
  // The normalized token exists only inside the folded exact-token proof, never as the visible reading.
  expect(reading.queryByText("999 K")).not.toBeInTheDocument();
});

it("clears private readings and notes on authentication or page visibility changes", async () => {
  await setup(); await previewReturn();
  await act(async () => notifyAuthChange());
  expect(screen.queryByRole("region", { name: "Pinned research action" })).not.toBeInTheDocument(); expect(screen.queryByRole("region", { name: "Existing retained evidence reading" })).not.toBeInTheDocument(); expect(screen.queryByRole("region", { name: "Exact evidence preview" })).not.toBeInTheDocument();
  expect(document.body).not.toHaveTextContent("Source onset is retained; the Hc2 field has a distinct scope.");
  cleanup(); await setup(); await previewReturn();
  await act(async () => window.dispatchEvent(new Event("pagehide")));
  expect(screen.queryByRole("region", { name: "Existing retained evidence reading" })).not.toBeInTheDocument(); expect(document.body).not.toHaveTextContent("Physical relationship remains unknown");
});

it("invalidates a prepared evidence operation when the parent draft changes", async () => {
  const state = await setup(); await previewReturn();
  state.rerender(<DiscoveryEvidenceFeedback {...state.props} invalidationKey={1} />);
  await waitFor(() => expect(screen.queryByRole("region", { name: "Exact evidence preview" })).not.toBeInTheDocument());
  expect(discoveryFeedbackCommit).not.toHaveBeenCalled();
});

it("does not retain a rejected source-change commit as a saved association", async () => {
  const state = await setup(); await previewReturn();
  vi.mocked(discoveryFeedbackCommit).mockRejectedValue(new ApiError(409, null, "source changed"));
  fireEvent.click(screen.getByRole("button", { name: "Save evidence association" }));
  await screen.findByText(/The design, evidence source or linked child changed/);
  expect(screen.queryByRole("region", { name: "Saved evidence receipt" })).not.toBeInTheDocument(); expect(state.onSaveResolved).toHaveBeenCalledTimes(1); expect(discoveryFeedbackOutcome).not.toHaveBeenCalled();
});
