import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MaterialsAmendmentReview } from "@/components/MaterialsAmendmentReview";
import { MaterialsProposalReview } from "@/components/MaterialsProposalReview";
import { ApiError, materialsProposalAmendment, materialsProposalAmendments, materialsProposalCapabilities, materialsProposalDetail, materialsProposalEvidence, materialsProposalRuns } from "@/lib/api";
import { amendmentSelection, proposalAmendment, proposalAmendments, type AmendmentDetail, type Body, type ProposalRow } from "@/lib/materials-proposal-review";
import { syntheticAmendments, type AmendmentCapture } from "../helpers/materials-amendment-test-data";

vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(), materialsProposalAmendment: vi.fn(), materialsProposalAmendments: vi.fn(), materialsProposalCapabilities: vi.fn(), materialsProposalDetail: vi.fn(), materialsProposalEvidence: vi.fn(), materialsProposalRuns: vi.fn() }));
const copy = <T,>(v: T): T => JSON.parse(JSON.stringify(v));
const actual: AmendmentCapture | null = process.env.SCLIB_AMENDMENT_REPLAY ? JSON.parse(readFileSync(process.env.SCLIB_AMENDMENT_REPLAY, "utf8")) : null;
const cases = [...syntheticAmendments.cases, ...(actual?.cases ?? [])];
const selections = cases.flatMap(c => c.amendments.listing.items.flatMap(summary => summary.selected_result_ids.map(id => ({
  work: c.pages[0].run.work_id, id, summary, dto: c.amendments.details[summary.id], detail: c.pages.find(p => p.results.some(r => r.local_id === id))!,
  original: c.pages.flatMap(p => p.results).find(r => r.local_id === id)!, listing: c.amendments.listing,
}))));
const fixture = selections[0];
beforeEach(() => vi.clearAllMocks());
async function openRevision() {
  fireEvent.click(screen.getByRole("button", { name: "Load source-backed amendments" }));
  fireEvent.click(await screen.findByRole("button", { name: /^Inspect amendment/ }));
  return screen.findByTestId("amendment-reading");
}

describe("Amendments retain source ownership and review boundaries", () => {
  it.each(selections)("reads $work $id with scientific values and literal anchors intact", async f => {
    expect(proposalAmendments(f.listing, f.detail.run)).not.toBeNull();
    const parsed = proposalAmendment(f.dto, f.detail.run, f.summary);
    expect(parsed).not.toBeNull();
    const selected = amendmentSelection(parsed!, f.id)!;
    expect(selected.sample.id).toBe(selected.result.sample_id);
    expect(selected.state.sample_id).toBe(selected.sample.id);
    vi.mocked(materialsProposalAmendments).mockResolvedValue(f.listing);
    vi.mocked(materialsProposalAmendment).mockResolvedValue(f.dto);
    const refused = vi.fn(); render(<MaterialsAmendmentReview detail={f.detail} original={f.original} onRefusal={refused} />);
    const reading = within(await openRevision());
    const quantity = selected.result.quantity as Body;
    expect(reading.getByRole("region", { name: "Quantity", exact: true }).textContent).toContain(quantity.raw);
    const conditions = selected.state.conditions;
    if (Array.isArray(conditions) && conditions.length) expect(reading.getByRole("region", { name: "Conditions", exact: true }).textContent).toContain(JSON.stringify(conditions));
    const uncertainty = quantity.uncertainty;
    if (uncertainty) expect(reading.getByRole("region", { name: "Uncertainty", exact: true }).textContent).toContain(JSON.stringify(uncertainty));
    if (selected.sample.substrate_raw) expect(reading.getByRole("region", { name: "Substrate", exact: true }).textContent).toContain(selected.sample.substrate_raw);
    expect(reading.getByText(/Retained source descriptors can differ/)).toBeVisible();
    expect(reading.getByText(/Canonical identity: independent review pending/)).toBeVisible();
    fireEvent.click(reading.getByText(/^quantity · /));
    const anchor = selected.review.fields.quantity.anchors[0];
    expect(Array.from(screen.getByTestId("amendment-reading").querySelectorAll("blockquote")).some(x => x.textContent === anchor.quote)).toBe(true);
    expect(screen.queryByRole("button", { name: /approve|publish|promote/i })).toBeNull();
    expect(refused).not.toHaveBeenCalled();
  });

  it("uses Unicode code-point offsets and refuses wrong literal quotes", () => {
    expect(proposalAmendment(fixture.dto, fixture.detail.run, fixture.summary)).not.toBeNull();
    const changed = copy(fixture.dto); changed.amendment.reviews[0].fields.quantity.anchors[0].start_char += 1;
    expect(proposalAmendment(changed, fixture.detail.run, fixture.summary)).toBeNull();
  });
  it.each([
    (d: AmendmentDetail) => { d.amendment.parent_packet_hash = "0".repeat(64); },
    (d: AmendmentDetail) => { d.mapping.records[0].sample_pointer = "/graph/samples/99"; },
    (d: AmendmentDetail) => { d.mapping.records[0].review_pointer = "/reviews/1"; },
    (d: AmendmentDetail) => { d.amendment.graph.states[0].sample_id = "unrelated"; },
    (d: AmendmentDetail) => { d.amendment.scientific_acceptance = true; },
    (d: AmendmentDetail) => { d.mapping.records[0].target_id = "invented-canonical-id"; },
  ])("refuses mismatched ownership, pointers or asserted approval %#", mutate => {
    const changed = copy(fixture.dto); mutate(changed);
    expect(proposalAmendment(changed, fixture.detail.run, fixture.summary)).toBeNull();
  });
  it("does not reopen an amendment after its selected result unmounts", async () => {
    let resolve!: (v: unknown) => void;
    vi.mocked(materialsProposalAmendments).mockResolvedValue(fixture.listing);
    vi.mocked(materialsProposalAmendment).mockImplementation(() => new Promise(r => { resolve = r; }));
    const refused = vi.fn(), rendered = render(<MaterialsAmendmentReview detail={fixture.detail} original={fixture.original} onRefusal={refused} />);
    fireEvent.click(screen.getByRole("button", { name: "Load source-backed amendments" }));
    fireEvent.click(await screen.findByRole("button", { name: /^Inspect amendment/ }));
    const signal = vi.mocked(materialsProposalAmendment).mock.calls[0][2]!;
    rendered.unmount(); await act(async () => resolve(fixture.dto));
    expect(signal.aborted).toBe(true); expect(screen.queryByTestId("amendment-reading")).toBeNull(); expect(refused).not.toHaveBeenCalled();
  });
  it("clears original evidence and amendments together when a fresh download is refused", async () => {
    vi.mocked(materialsProposalCapabilities).mockResolvedValue(syntheticAmendments.capabilities);
    vi.mocked(materialsProposalRuns).mockResolvedValue(syntheticAmendments.queue);
    vi.mocked(materialsProposalDetail).mockResolvedValue(fixture.detail);
    vi.mocked(materialsProposalEvidence).mockResolvedValue(syntheticAmendments.cases[0].evidence[fixture.id][0]);
    vi.mocked(materialsProposalAmendments).mockResolvedValue(fixture.listing);
    vi.mocked(materialsProposalAmendment).mockResolvedValue(fixture.dto);
    render(<MaterialsProposalReview />);
    fireEvent.click(await screen.findByRole("button", { name: /arxiv:0001.00001 · Synthetic/ }));
    fireEvent.click(await screen.findByRole("button", { name: "I1 · tc", exact: true }));
    await screen.findByRole("heading", { name: "Captured source passages" }); await openRevision();
    vi.mocked(materialsProposalAmendment).mockRejectedValue(new ApiError(403, null, "PRIVATE_ERROR"));
    fireEvent.click(screen.getByRole("button", { name: "Download amendment (JSON)" }));
    await screen.findByRole("alert");
    expect(screen.queryByTestId("amendment-reading")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Captured source passages" })).toBeNull();
    expect(screen.queryByText("PRIVATE_ERROR")).toBeNull();
  });
  it("rechecks immutable storage identity before download", async () => {
    vi.mocked(materialsProposalAmendments).mockResolvedValue(fixture.listing); vi.mocked(materialsProposalAmendment).mockResolvedValue(fixture.dto);
    const refused = vi.fn(); render(<MaterialsAmendmentReview detail={fixture.detail} original={fixture.original} onRefusal={refused} />); await openRevision();
    vi.mocked(materialsProposalAmendment).mockResolvedValue({ ...fixture.dto, storage_hash: "9".repeat(64) });
    fireEvent.click(screen.getByRole("button", { name: "Download amendment (JSON)" }));
    await waitFor(() => expect(refused).toHaveBeenCalledOnce());
  });
  it("does not present unselected retained results as reviewed", async () => {
    vi.mocked(materialsProposalAmendments).mockResolvedValue(fixture.listing);
    const original: ProposalRow = { ...fixture.original, local_id: "unselected" };
    render(<MaterialsAmendmentReview detail={fixture.detail} original={original} onRefusal={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Load source-backed amendments" }));
    expect(await screen.findByText(/No amendment selects this result/)).toBeVisible();
    expect(screen.queryByRole("button", { name: /^Inspect amendment/ })).toBeNull();
  });
  it.skipIf(!actual)("includes all 22 selected development results from five actual source works", () => {
    expect(actual!.cases).toHaveLength(5);
    expect(actual!.cases.flatMap(c => c.amendments.listing.items.flatMap(x => x.selected_result_ids))).toHaveLength(22);
  });
});
