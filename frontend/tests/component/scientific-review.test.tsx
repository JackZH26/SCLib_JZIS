import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ScientificReviewPage from "@/app/dashboard/research/review/page";
import { Sidebar } from "@/components/dashboard/Sidebar";
import { ApiError, scientificReviewCapabilities, scientificReviewDossier, scientificReviewQueue } from "@/lib/api";
import { knownReviewCapabilities, knownReviewDossier, knownReviewQueue, reviewQuantity,
  type ReviewCapabilities, type ReviewDossier, type ReviewQueue, type ReviewQueueItem } from "@/lib/scientific-review";
import syntheticHttp from "../fixtures/scientific-review-http.json";

vi.mock("next/navigation", () => ({ usePathname: () => "/dashboard/research/review" }));
vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(),
  scientificReviewCapabilities: vi.fn(), scientificReviewQueue: vi.fn(), scientificReviewDossier: vi.fn() }));

const id = (number: number) => `00000000-0000-4000-8000-${String(number).padStart(12, "0")}`;
const hash = "a".repeat(64);
const countBasis = "Canonical non-Tc, non-RPS properties; review status belongs to each parent event. This page is not a reviewed-result total.";
function capability(): ReviewCapabilities {
  return { version: "scientific-review-capabilities/1.0.0", roles: ["curator"], can_read: true, review_write_available: false };
}
function item(number = 1): ReviewQueueItem {
  return { property_id: id(number), event_id: id(number + 100), event_revision: 1, material_id: `synthetic:${number}`,
    formula: number === 1 ? "AlAs" : "MgB2", property_key: "phonon_min_frequency", unit: "THz", knowledge_origin: "Computed",
    review_status: "pending", validity_status: "pending" };
}
function queue(items = [item(1), item(2)]): ReviewQueue {
  return { version: "scientific-review-queue/1.0.0", items, next_cursor: null, has_more: false, total_count: null, count_basis: countBasis };
}
function dossier(selected = item()): ReviewDossier {
  return { version: "scientific-result-dossier/1.0.0", descriptor_sha256: hash,
    target: { property_id: selected.property_id, event_id: selected.event_id, event_revision: selected.event_revision },
    material: { id: selected.material_id, formula: selected.formula },
    result: { property_key: selected.property_key, registry_version: "rv2/1", component_key: "bulk", relation: "exact", value: -0.003,
      lower: null, upper: null, unit: "THz" },
    event: { event_type: "extraction", knowledge_origin: selected.knowledge_origin, review_status: selected.review_status, validity_status: selected.validity_status },
    state: { id: id(201), resolution: "source_scoped", pressure_status: "not_reported", pressure_gpa: null, temperature_role: "simulation", temperature_k: null },
    structure: { id: id(301), structure_kind: "coordinates", artifact_id: id(401) },
    run: { id: id(501), run_kind: "extraction", status: "completed" },
    sources: [{ artifact_id: id(601), kind: "other", access: "restricted", hash_status: "verified", bytes_sha256: hash,
      evidence_link_ids: [id(701)], locators: [{ scope: "locator_not_disclosed" }] }],
    inventory: { row_count: 8, artifact_count: 1, sha256: hash }, warnings: ["upstream_run_unresolved", "conditions_not_reported"],
    impact: { version: "scientific-result-impact/1.0.0", scope: ["direct_result_dependencies"], unsupported_scopes: ["public_projection_refresh"],
      complete_for_scope: true, counts: { ml_example_inputs: 1, total_nodes: 1, total_relations: 1 }, items: [{ table: "ml_example_inputs", row_id: id(801),
        relation: "exact_property_input", via_table: "event_properties", via_id: selected.property_id }] },
    authority: { scientific_accepted: false, ml_training_approved: false, public_release: false, review_write_available: false } };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}
async function selectFirst() {
  fireEvent.click(await screen.findByRole("button", { name: /AlAs · phonon min frequency/ }));
  return screen.findByRole("heading", { name: "Exact result · AlAs" });
}

describe("scientific evidence workbench", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(scientificReviewCapabilities).mockResolvedValue(capability());
    vi.mocked(scientificReviewQueue).mockResolvedValue(queue());
    vi.mocked(scientificReviewDossier).mockImplementation(async property => dossier(item(property === id(1) ? 1 : 2)));
  });

  it("checks explicit capabilities before requesting any scientific rows", async () => {
    const pending = deferred<unknown>();
    vi.mocked(scientificReviewCapabilities).mockReturnValue(pending.promise);
    render(<ScientificReviewPage />);
    expect(scientificReviewQueue).not.toHaveBeenCalled();
    await act(async () => pending.resolve(capability()));
    await screen.findByRole("heading", { name: "Result inventory" });
    expect(scientificReviewQueue).toHaveBeenCalledWith(null, expect.any(AbortSignal));
    expect(scientificReviewDossier).not.toHaveBeenCalled();
  });

  it("shows exact result, unknown conditions and retained provenance without approval or exports", async () => {
    const storage = vi.spyOn(window.localStorage, "setItem");
    render(<ScientificReviewPage />);
    await selectFirst();
    expect(screen.getByText("phonon min frequency: -0.003 THz")).toBeVisible();
    expect(screen.getByText(/Not reported \/ unresolved · not reported/)).toBeVisible();
    expect(screen.queryByText("0 GPa")).not.toBeInTheDocument();
    expect(screen.getByText("Locator not disclosed")).toBeVisible();
    expect(screen.getByText(/An extraction run is not an attested upstream calculation/)).toBeVisible();
    expect(screen.getByText(/Scientific adjudication is not available/)).toBeVisible();
    expect(screen.getByText(/browser has not independently verified original files/)).toBeVisible();
    expect(screen.getByText(/database relationship inventory, not a prediction/)).toBeVisible();
    expect(screen.getByText(/no global total is reported/)).toBeVisible();
    expect(screen.queryByRole("button", { name: /approve|accept|reject|clarif|publish|export|download/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(storage).not.toHaveBeenCalled();
    storage.mockRestore();
  });

  it("renders the exact captured disposable SQL-to-HTTP synthetic wire without manufacturing approval", async () => {
    const capturedQueue = knownReviewQueue(syntheticHttp.queue);
    expect(knownReviewCapabilities(syntheticHttp.capabilities)).not.toBeNull();
    expect(capturedQueue).not.toBeNull();
    expect(knownReviewDossier(syntheticHttp.dossier, capturedQueue!.items[0])).not.toBeNull();
    vi.mocked(scientificReviewCapabilities).mockResolvedValue(syntheticHttp.capabilities);
    vi.mocked(scientificReviewQueue).mockResolvedValue(syntheticHttp.queue);
    vi.mocked(scientificReviewDossier).mockResolvedValue(syntheticHttp.dossier);
    render(<ScientificReviewPage />);
    await selectFirst();
    expect(screen.getByText("phonon min frequency: -0.0299792458 THz")).toBeVisible();
    expect(screen.getByText("Line 3; byte range 51–58")).toBeVisible();
    expect(screen.getByText("22 rows; 9 artifacts")).toBeVisible();
    expect(screen.getByText(/Membership does not establish support for this property/)).toBeVisible();
    expect(screen.getByText(/Raw source text, metadata payloads and file exports are withheld/)).toBeVisible();
    expect(screen.queryByRole("button", { name: /approve|accept|reject|publish|export|download/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("does not infer read permission from publisher-only or missing grants", async () => {
    vi.mocked(scientificReviewCapabilities).mockResolvedValue({ ...capability(), roles: ["publisher"], can_read: false });
    render(<ScientificReviewPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Ordinary administrator or legacy reviewer flags do not grant access");
    expect(scientificReviewQueue).not.toHaveBeenCalled();
    expect(scientificReviewDossier).not.toHaveBeenCalled();
  });

  it("renders an honest empty page and no global reviewed-result count", async () => {
    vi.mocked(scientificReviewQueue).mockResolvedValue(queue([]));
    render(<ScientificReviewPage />);
    expect(await screen.findByText("No results were returned in this bounded inventory page.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
  });

  it.each([401, 403, 404, 503, 0])("clears all retained evidence after detail refusal %s without surfacing raw errors", async status => {
    render(<ScientificReviewPage />);
    await selectFirst();
    vi.mocked(scientificReviewDossier).mockRejectedValue(new ApiError(status, { detail: "SECRET SOURCE" }, "SECRET DATABASE"));
    fireEvent.click(screen.getByRole("button", { name: /MgB2 · phonon min frequency/ }));
    await screen.findByRole("alert");
    expect(screen.queryByRole("heading", { name: "Result inventory" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /Exact result/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/SECRET/)).not.toBeInTheDocument();
    expect(screen.queryByText(hash)).not.toBeInTheDocument();
  });

  it("clears the prior detail immediately when another selection is pending", async () => {
    render(<ScientificReviewPage />);
    await selectFirst();
    const pending = deferred<unknown>();
    vi.mocked(scientificReviewDossier).mockReturnValue(pending.promise);
    fireEvent.click(screen.getByRole("button", { name: /MgB2 · phonon min frequency/ }));
    expect(screen.queryByRole("heading", { name: "Exact result · AlAs" })).not.toBeInTheDocument();
    expect(screen.queryByText(hash)).not.toBeInTheDocument();
    expect(screen.getByText(/Previous detail has been cleared/)).toBeVisible();
    await act(async () => pending.resolve(dossier(item(2))));
    expect(await screen.findByRole("heading", { name: "Exact result · MgB2" })).toBeVisible();
  });

  it("ignores an old selected result after a newer selection completes", async () => {
    const old = deferred<unknown>();
    vi.mocked(scientificReviewDossier).mockReturnValueOnce(old.promise).mockResolvedValueOnce(dossier(item(2)));
    render(<ScientificReviewPage />);
    fireEvent.click(await screen.findByRole("button", { name: /AlAs · phonon min frequency/ }));
    const signal = vi.mocked(scientificReviewDossier).mock.calls[0][1];
    fireEvent.click(screen.getByRole("button", { name: /MgB2 · phonon min frequency/ }));
    await screen.findByRole("heading", { name: "Exact result · MgB2" });
    expect(signal?.aborted).toBe(true);
    await act(async () => old.resolve(dossier()));
    expect(screen.queryByRole("heading", { name: "Exact result · AlAs" })).not.toBeInTheDocument();
  });

  it("rechecks capabilities on refresh and ignores the previous delayed queue", async () => {
    const old = deferred<unknown>();
    vi.mocked(scientificReviewQueue).mockReturnValueOnce(old.promise).mockResolvedValueOnce(queue([item(2)]));
    render(<ScientificReviewPage />);
    await waitFor(() => expect(scientificReviewQueue).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "Restart access check" }));
    await screen.findByRole("button", { name: /MgB2 · phonon min frequency/ });
    await act(async () => old.resolve(queue([item(1)])));
    expect(screen.queryByRole("button", { name: /AlAs · phonon min frequency/ })).not.toBeInTheDocument();
    expect(scientificReviewCapabilities).toHaveBeenCalledTimes(2);
  });

  it("clears sensitive display before a refresh and stays cleared when permission is revoked", async () => {
    render(<ScientificReviewPage />);
    await selectFirst();
    const check = deferred<unknown>();
    vi.mocked(scientificReviewCapabilities).mockReturnValue(check.promise);
    fireEvent.click(screen.getByRole("button", { name: "Refresh access" }));
    expect(screen.queryByText(hash)).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Result inventory" })).not.toBeInTheDocument();
    await act(async () => check.resolve({ ...capability(), roles: [], can_read: false }));
    await screen.findByRole("alert");
    expect(scientificReviewQueue).toHaveBeenCalledTimes(1);
  });

  it("rechecks access and uses an exact cursor for the next page", async () => {
    vi.mocked(scientificReviewQueue).mockResolvedValueOnce({ ...queue([item(1)]), has_more: true, next_cursor: id(1) })
      .mockResolvedValueOnce(queue([item(2)]));
    render(<ScientificReviewPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Next page" }));
    await screen.findByRole("button", { name: /MgB2 · phonon min frequency/ });
    expect(scientificReviewQueue).toHaveBeenLastCalledWith(id(1), expect.any(AbortSignal));
    expect(scientificReviewCapabilities).toHaveBeenCalledTimes(2);
  });

  it("refuses detail from a changed revision and clears its queue", async () => {
    const changed = dossier(); changed.target.event_revision = 2;
    vi.mocked(scientificReviewDossier).mockResolvedValue(changed);
    render(<ScientificReviewPage />);
    fireEvent.click(await screen.findByRole("button", { name: /AlAs · phonon min frequency/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Evidence could not be checked");
    expect(screen.queryByRole("heading", { name: "Result inventory" })).not.toBeInTheDocument();
  });

  it("aborts outstanding work on unmount", async () => {
    const pending = deferred<unknown>();
    vi.mocked(scientificReviewCapabilities).mockReturnValue(pending.promise);
    const mounted = render(<ScientificReviewPage />);
    const signal = vi.mocked(scientificReviewCapabilities).mock.calls[0][0];
    mounted.unmount();
    expect(signal?.aborted).toBe(true);
    await act(async () => pending.resolve(capability()));
    expect(scientificReviewQueue).not.toHaveBeenCalled();
  });

  it("keeps the evidence navigation keyboard-accessible and responsive without a legacy-role condition", () => {
    render(<Sidebar items={[{ href: "/dashboard/research/review", label: "Scientific evidence" }]} />);
    const nav = screen.getByRole("navigation", { name: "Dashboard navigation" });
    expect(nav.parentElement).toHaveClass("w-full", "md:w-56");
    expect(nav).toHaveClass("flex-wrap", "md:flex-col");
    const link = screen.getByRole("link", { name: "Scientific evidence" });
    link.focus(); expect(link).toHaveFocus();
    expect(link).toHaveAttribute("href", "/dashboard/research/review");
  });
});

describe("closed scientific review display guards", () => {
  it("accepts the bounded non-authoritative declared shapes", () => {
    expect(knownReviewCapabilities(capability())).not.toBeNull();
    expect(knownReviewQueue(queue())).not.toBeNull();
    expect(knownReviewDossier(dossier(), item())).not.toBeNull();
  });
  it.each([
    { ...capability(), review_write_available: true }, { ...capability(), scientific_accepted: true },
    { ...capability(), can_read: 1 }, { ...capability(), roles: ["admin"] },
    { ...capability(), roles: [] }, { ...capability(), roles: ["curator", "curator"] },
  ])("rejects false capability authority or malformed roles %j", value => expect(knownReviewCapabilities(value)).toBeNull());
  it.each([
    { ...queue(), total_count: 2 }, { ...queue(), items: [item(), item()] },
    { ...queue(), has_more: true }, { ...queue(), count_basis: "Scientifically verified results" },
    { ...queue(), items: [{ ...item(), property_key: "tc" }] },
    { ...queue(), items: [{ ...item(), property_key: "rps_score" }] },
    { ...queue(), items: [{ ...item(), unit: "cm^-1" }] },
    { ...queue(), items: [{ ...item(), event_revision: true }] },
    { ...queue(), items: Array.from({ length: 51 }, (_, index) => item(index + 1)) },
  ])("rejects contradictory queue wire %#", value => expect(knownReviewQueue(value)).toBeNull());
  it.each([
    (value: ReviewDossier) => { value.authority.scientific_accepted = true as false; },
    (value: ReviewDossier) => { value.authority.ml_training_approved = 0 as unknown as false; },
    (value: ReviewDossier) => { value.target.property_id = id(99); },
    (value: ReviewDossier) => { value.material.formula = "DIFFERENT"; },
    (value: ReviewDossier) => { value.event.review_status = "approved"; },
    (value: ReviewDossier) => { value.result.value = NaN; },
    (value: ReviewDossier) => { value.result.value = true as unknown as number; },
    (value: ReviewDossier) => { value.result.relation = "lt"; },
    (value: ReviewDossier) => { value.state.pressure_gpa = 0; },
    (value: ReviewDossier) => { value.state.temperature_k = -1; },
    (value: ReviewDossier) => { value.descriptor_sha256 = "bad hash"; },
    (value: ReviewDossier) => { value.result.registry_version = "unreviewed-new-registry"; },
    (value: ReviewDossier) => { value.sources.push(value.sources[0]); },
    (value: ReviewDossier) => { value.sources[0].bytes_sha256 = null; },
    (value: ReviewDossier) => { Object.assign(value.sources[0], { text: "PRIVATE SOURCE" }); },
    (value: ReviewDossier) => { Object.assign(value.result, { raw: { secret: "PRIVATE SOURCE" } }); },
    (value: ReviewDossier) => { value.inventory.row_count = 1001; },
    (value: ReviewDossier) => { value.impact.complete_for_scope = false as true; },
    (value: ReviewDossier) => { value.impact.counts.total_nodes = 8; },
    (value: ReviewDossier) => { value.impact.items.push(value.impact.items[0]); },
    (value: ReviewDossier) => { value.inventory.artifact_count = 2; },
  ])("withholds malformed or mismatched dossier %#", mutate => {
    const value = dossier(); mutate(value); expect(knownReviewDossier(value, item())).toBeNull();
  });
  it("retains signed frequencies, exact zero, censored and interval shapes", () => {
    const value = dossier();
    value.state.pressure_status = "explicit_ambient"; value.state.pressure_gpa = 0;
    value.sources[0].locators = [{ line: 3, start_byte: 12, end_byte: 20 }];
    expect(knownReviewDossier(value, item())).not.toBeNull();
    expect(reviewQuantity(value.result)).toBe("-0.003 THz");
    value.result = { ...value.result, relation: "le", value: null, upper: 0 };
    expect(knownReviewDossier(value, item())).not.toBeNull();
    expect(reviewQuantity(value.result)).toBe("≤ 0 THz");
    value.result = { ...value.result, relation: "interval", lower: -1, upper: 2 };
    expect(reviewQuantity(value.result)).toBe("-1–2 THz");
    value.result.lower = 3;
    expect(knownReviewDossier(value, item())).toBeNull();
  });
});

describe("real private API client wrappers", () => {
  it("uses credentialled no-store GET requests with abort signals and encoded inputs", async () => {
    const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
    const fetcher = vi.fn().mockResolvedValue(new Response("{}", { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetcher);
    const controller = new AbortController();
    try {
      await real.scientificReviewCapabilities(controller.signal);
      await real.scientificReviewQueue(id(1), controller.signal);
      await real.scientificReviewDossier("unsafe/segment?", controller.signal);
      expect(fetcher.mock.calls[0][0]).toContain("/ml/scientific-review/capabilities");
      expect(fetcher.mock.calls[1][0]).toContain(`/ml/scientific-review/results?limit=25&after=${id(1)}`);
      expect(fetcher.mock.calls[2][0]).toContain("/ml/scientific-review/results/unsafe%2Fsegment%3F");
      for (const [, options] of fetcher.mock.calls) expect(options).toMatchObject({ cache: "no-store", credentials: "include", signal: controller.signal });
    } finally { vi.unstubAllGlobals(); }
  });
});
