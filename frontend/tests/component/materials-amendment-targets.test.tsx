import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MaterialsAmendmentReview } from "@/components/MaterialsAmendmentReview";
import { materialsAmendmentTargets, materialsClaimReviewContext, materialsProposalAmendment, materialsProposalAmendments } from "@/lib/api";
import { amendmentTargets, claimSourceContext, type AmendmentTargets, type Body } from "@/lib/materials-proposal-review";
import { syntheticAmendments, type AmendmentCapture } from "../helpers/materials-amendment-test-data";

vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(), materialsAmendmentTargets: vi.fn(), materialsClaimReviewContext: vi.fn(), materialsProposalAmendment: vi.fn(), materialsProposalAmendments: vi.fn() }));
const copy = <T,>(v: T): T => JSON.parse(JSON.stringify(v));
const actual: AmendmentCapture | null = process.env.SCLIB_AMENDMENT_REPLAY ? JSON.parse(readFileSync(process.env.SCLIB_AMENDMENT_REPLAY, "utf8")) : null;
type CanonicalReplay = { cases: { work_id: string; result_id: string; targets: AmendmentTargets; context: Body }[] };
const canonical: CanonicalReplay | null = process.env.SCLIB_CANONICAL_REPLAY ? JSON.parse(readFileSync(process.env.SCLIB_CANONICAL_REPLAY, "utf8")) : null;
const c = syntheticAmendments.cases[0], summary = c.amendments.listing.items[0], dto = c.amendments.details[summary.id];
const resultId = summary.selected_result_ids[0];
const target = { id: "00000000-0000-5000-8000-000000000001", event_id: "00000000-0000-5000-8000-000000000002", state_id: "00000000-0000-5000-8000-000000000003", sample_id: "00000000-0000-5000-8000-000000000004", material_id: "mat:test", work_id: "00000000-0000-5000-8000-000000000005", source_snapshot_id: "00000000-0000-5000-8000-000000000006", interpretation_revision: 1, source_record_hash: "a".repeat(64), identity_status: "candidate_requires_independent_identity_review" as const };
const targets: AmendmentTargets = { version: "materials-amendment-targets/1", parent_run_id: dto.amendment.parent_run_id, amendment_id: dto.amendment.amendment_id, storage_hash: dto.storage_hash, result_id: resultId, items: [target], authority: dto.authority };
const context: Body = { version: "materials-result-review-context/1.6.0", subject_sha256: "b".repeat(64), result_row_sha256: "c".repeat(64), target: { result_kind: "claim", result_id: target.id, event_id: target.event_id, state_id: target.state_id, sample_id: target.sample_id, material_id: target.material_id }, review_write_available: false, source_text_disclosed: false, authority: { scientific_accepted: false, ml_training_approved: false, public_release: false }, source_occurrences: [{ occurrence_id: "00000000-0000-5000-8000-000000000007", source_revision_id: "00000000-0000-5000-8000-000000000008", capture_id: "00000000-0000-5000-8000-000000000009", bytes_sha256: "d".repeat(64), binding_status: "pending", version_status: "pinned", provider_revision: "v2", representation: "arxiv_source" }] };
const cases = [{ work_id: c.pages[0].run.work_id, result_id: resultId, targets, context }, ...(canonical?.cases ?? [])];
beforeEach(() => vi.clearAllMocks());
async function open(f = cases[0]) {
  const source = [c, ...(actual?.cases ?? [])].find(x => x.pages[0].run.work_id === f.work_id)!;
  const detail = source.pages.find(p => p.results.some(r => r.local_id === f.result_id))!;
  const amendment = Object.values(source.amendments.details).find(d => d.amendment.selected_result_ids.includes(f.result_id))!;
  vi.mocked(materialsProposalAmendments).mockResolvedValue(source.amendments.listing);
  vi.mocked(materialsProposalAmendment).mockResolvedValue(amendment);
  vi.mocked(materialsAmendmentTargets).mockResolvedValue(f.targets);
  vi.mocked(materialsClaimReviewContext).mockResolvedValue(f.context);
  const refused = vi.fn(), rendered = render(<MaterialsAmendmentReview detail={detail} original={detail.results.find(r => r.local_id === f.result_id)!} onRefusal={refused} />);
  fireEvent.click(screen.getByRole("button", { name: "Load source-backed amendments" }));
  fireEvent.click(await screen.findByRole("button", { name: /^Inspect amendment/ }));
  await screen.findByTestId("amendment-reading");
  expect(materialsAmendmentTargets).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Find stored candidates" }));
  return { refused, rendered };
}
async function inspect() { fireEvent.click(await screen.findByRole("button", { name: /^Read registered sources/ })); }

describe("Canonical candidate ownership and registered versions", () => {
  it.each(cases)("reads $work_id $result_id with explicit pending authority", async f => {
    const { refused } = await open(f); await inspect();
    const view = within(await screen.findByTestId("canonical-source-reading"));
    for (const version of new Set((f.context.source_occurrences as Body[]).map(x => x.provider_revision))) {
      expect(view.getAllByText(new RegExp(`Registered version: ${version}`)).length).toBeGreaterThan(0);
    }
    expect(view.getByText(/Identity review: pending/)).toBeVisible();
    expect(view.getByText(/Candidate material:/).textContent).toContain(f.targets.items[0].material_id);
    expect(screen.queryByRole("button", { name: /approve|promote|publish/i })).toBeNull();
    expect(refused).not.toHaveBeenCalled();
  });
  it.each(["parent_run_id", "amendment_id", "storage_hash", "result_id"])("refuses mismatched %s", field => {
    expect(amendmentTargets({ ...targets, [field]: "wrong" }, dto, resultId)).toBeNull();
  });
  it.each(["result_id", "event_id", "state_id", "sample_id", "material_id"])("refuses a source context owned by another %s", field => {
    expect(claimSourceContext({ ...context, target: { ...(context.target as Body), [field]: "wrong" } }, target)).toBeNull();
  });
  it("refuses duplicate targets and unearned approval", () => {
    expect(amendmentTargets({ ...targets, items: [target, target] }, dto, resultId)).toBeNull();
    expect(claimSourceContext({ ...context, authority: { scientific_accepted: true, ml_training_approved: false, public_release: false } }, target)).toBeNull();
  });
  it("keeps missing canonical identity unresolved", async () => {
    await open({ ...cases[0], targets: { ...targets, items: [] } });
    expect(await screen.findByText(/No stored candidate is linked/)).toBeVisible();
    expect(materialsClaimReviewContext).not.toHaveBeenCalled();
  });
  it("does not choose between multiple retained candidates", async () => {
    const second = { ...target, id: "00000000-0000-5000-8000-000000000010" };
    await open({ ...cases[0], targets: { ...targets, items: [target, second] } });
    const buttons = await screen.findAllByRole("button", { name: /^Read registered sources/ });
    expect(buttons).toHaveLength(2); expect(materialsClaimReviewContext).not.toHaveBeenCalled();
    vi.mocked(materialsClaimReviewContext).mockResolvedValue({ ...context, target: { ...(context.target as Body), result_id: second.id } });
    fireEvent.click(buttons[1]); await screen.findByTestId("canonical-source-reading");
    expect(vi.mocked(materialsClaimReviewContext).mock.calls[0][0]).toBe(second.id);
  });
  it("propagates fresh access refusal without revealing a private error", async () => {
    const { refused } = await open();
    vi.mocked(materialsClaimReviewContext).mockRejectedValue(new Error("PRIVATE_DETAIL")); await inspect();
    await waitFor(() => expect(refused).toHaveBeenCalledOnce());
    expect(screen.queryByText("PRIVATE_DETAIL")).toBeNull(); expect(screen.queryByTestId("canonical-source-reading")).toBeNull();
  });
  it("aborts stale source reads when the amendment is unmounted", async () => {
    const { rendered, refused } = await open(); let resolve!: (v: unknown) => void;
    vi.mocked(materialsClaimReviewContext).mockImplementation(() => new Promise(r => { resolve = r; }));
    await inspect(); const signal = vi.mocked(materialsClaimReviewContext).mock.calls[0][1]!;
    rendered.unmount(); await act(async () => resolve(context));
    expect(signal.aborted).toBe(true); expect(refused).not.toHaveBeenCalled(); expect(screen.queryByTestId("canonical-source-reading")).toBeNull();
  });
  it.skipIf(!canonical)("covers all 22 actual targets in five development works", () => {
    expect(canonical!.cases).toHaveLength(22); expect(new Set(canonical!.cases.map(x => x.work_id)).size).toBe(5);
  });
});
