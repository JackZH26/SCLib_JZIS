import { webcrypto } from "node:crypto";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DiscoveryDesignWorkbench } from "@/components/DiscoveryDesignWorkbench";
import { ApiError, discoveryConditionBatchCapabilities, discoveryConditionBatchCommit, discoveryConditionBatchDetail, discoveryConditionBatchManifest, discoveryConditionBatchOutcome, discoveryConditionBatchPage, discoveryConditionBatchPreview, discoveryDesignCapabilities, discoveryDesignCommit, discoveryDesignContext, discoveryDesignDetail, discoveryDesignPage, discoveryDesignPreview } from "@/lib/api";
import { notifyAuthChange } from "@/lib/auth-session";
import { copy, syntheticBatch, TEST_UUID } from "./discovery-condition-batches.synthetic";
import parentWire from "../fixtures/discovery-designs-native.synthetic.json";

const actor = vi.hoisted(() => ({ id: "" }));
vi.mock("@/components/dashboard/user-context", () => ({ useDashboardUser: () => ({ user: actor }) }));
vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(), discoveryDesignCapabilities: vi.fn(), discoveryDesignContext: vi.fn(), discoveryDesignPreview: vi.fn(), discoveryDesignCommit: vi.fn(), discoveryDesignOutcome: vi.fn(), discoveryDesignPage: vi.fn(), discoveryDesignDetail: vi.fn(), discoveryConditionBatchCapabilities: vi.fn(), discoveryConditionBatchPreview: vi.fn(), discoveryConditionBatchCommit: vi.fn(), discoveryConditionBatchOutcome: vi.fn(), discoveryConditionBatchPage: vi.fn(), discoveryConditionBatchDetail: vi.fn(), discoveryConditionBatchManifest: vi.fn() }));
beforeEach(() => { vi.resetAllMocks(); vi.stubGlobal("crypto", { subtle: webcrypto.subtle, randomUUID: () => TEST_UUID }); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function setup() {
  const f = await syntheticBatch(); actor.id = f.design.actor_user_id;
  vi.mocked(discoveryDesignCapabilities).mockResolvedValue(copy(f.design));
  vi.mocked(discoveryDesignContext).mockResolvedValue(copy(parentWire.context));
  vi.mocked(discoveryDesignPage).mockResolvedValue(copy(parentWire.page));
  vi.mocked(discoveryDesignDetail).mockResolvedValue(copy(parentWire.detail));
  vi.mocked(discoveryConditionBatchCapabilities).mockResolvedValue(copy(f.cap));
  vi.mocked(discoveryConditionBatchPreview).mockImplementation(request => Promise.resolve(copy(request.operation === "retain_batch" ? f.preview : f.childPreview)));
  vi.mocked(discoveryConditionBatchPage).mockResolvedValue(copy(f.page));
  vi.mocked(discoveryConditionBatchDetail).mockImplementation((_id, offset) => Promise.resolve(copy(f.detail(offset))));
  vi.mocked(discoveryConditionBatchManifest).mockResolvedValue(f.text);
  const view = render(<DiscoveryDesignWorkbench />);
  await screen.findByRole("button", { name: "Load saved batches" });
  fireEvent.change(screen.getByLabelText("Research hypothesis"), { target: { value: "Private draft that must be cleared on departure" } });
  return { f, view };
}
async function prepare(child: boolean) {
  if (child) {
    fireEvent.click(screen.getByRole("button", { name: "Load saved batches" }));
    fireEvent.click(await screen.findByRole("button", { name: "Inspect batch" }));
    await screen.findByRole("region", { name: "Retained batch scenarios" });
    fireEvent.click(screen.getAllByRole("button", { name: /^Preview child for/ })[0]);
  } else {
    fireEvent.click(screen.getByRole("button", { name: "Load saved designs" }));
    fireEvent.click(await screen.findByRole("button", { name: "Inspect history" }));
    fireEvent.click(await screen.findByText("Plan a bounded condition sweep"));
    fireEvent.change(screen.getByLabelText("Pressure choices (GPa, one per line)"), { target: { value: "10\n10.0\n50\n100\n200" } });
    fireEvent.change(screen.getByLabelText("Temperature choices (K, one per line)"), { target: { value: "250\n300\n350" } });
    fireEvent.click(screen.getByRole("button", { name: "Estimate combinations" }));
    fireEvent.click(screen.getByRole("button", { name: "Generate scenarios" }));
    fireEvent.click(await screen.findByRole("button", { name: "Preview batch retention" }));
  }
  return screen.findByRole("button", { name: child ? "Save candidate child" : "Retain private batch" });
}
it.each([{ child: false, late: "receipt" }, { child: false, late: "failure" }, { child: true, late: "receipt" }, { child: true, late: "failure" }])("keeps the original GET identity across held draft edits, pagehide and late $late (child=$child)", async ({ child, late }) => {
  const { f } = await setup();
  let resolve!: (value: unknown) => void, reject!: (reason: unknown) => void;
  vi.mocked(discoveryConditionBatchCommit).mockImplementation(() => new Promise((done, failed) => { resolve = done; reject = failed; }));
  vi.mocked(discoveryConditionBatchOutcome).mockResolvedValue(copy(child ? f.childOutcome : f.outcome));
  fireEvent.click(await prepare(child));
  await waitFor(() => expect(discoveryConditionBatchCommit).toHaveBeenCalledTimes(1));
  const draft = screen.getByLabelText("Research hypothesis"); expect(draft).toBeDisabled();
  fireEvent.change(draft, { target: { value: "Attempted edit during an already sent save" } });
  expect(draft).toHaveValue("Private draft that must be cleared on departure");
  expect(screen.getByRole("button", { name: "Preview private proposal" })).toBeDisabled();
  expect(discoveryConditionBatchPreview).toHaveBeenCalledTimes(1);
  act(() => window.dispatchEvent(new Event("pagehide")));
  expect(screen.queryByRole("region", { name: "Private condition batches" })).not.toBeInTheDocument();
  expect(document.body.textContent).not.toContain("Private draft that must be cleared");
  await act(async () => { if (late === "receipt") resolve(copy(child ? f.childCommit : f.commit)); else reject(new ApiError(0, null, "Synthetic interrupted save response")); });
  expect(screen.queryByText(child ? "Recorded candidate child" : "Recorded batch retention")).not.toBeInTheDocument();
  const grant = "00000000-0000-0000-0000-000000000008";
  vi.mocked(discoveryDesignCapabilities).mockResolvedValue({ ...copy(f.design), session_version: f.design.session_version + 1, curator_grant_id: grant });
  vi.mocked(discoveryConditionBatchCapabilities).mockResolvedValue({ ...copy(f.cap), session_version: f.cap.session_version + 1, curator_grant_id: grant });
  fireEvent.click(screen.getByRole("button", { name: "Refresh access" }));
  const check = await screen.findByRole("button", { name: "Check original batch request" });
  expect(screen.getByLabelText("Research hypothesis")).toHaveValue("");
  expect(screen.getByLabelText("Research hypothesis")).toBeDisabled();
  expect(discoveryConditionBatchOutcome).not.toHaveBeenCalled();
  fireEvent.click(check);
  await screen.findByText(child ? "Recorded candidate child" : "Recorded batch retention");
  const preview = child ? f.childPreview : f.preview, request = child ? f.childRequest : f.request;
  expect(vi.mocked(discoveryConditionBatchOutcome).mock.calls[0].slice(0, 2)).toEqual([request.request_key, preview.request_sha256]);
  expect(discoveryConditionBatchCommit).toHaveBeenCalledTimes(1);
  expect(discoveryConditionBatchPreview).toHaveBeenCalledTimes(1);
  expect(discoveryDesignCommit).not.toHaveBeenCalled(); expect(discoveryDesignPreview).not.toHaveBeenCalled();
  expect(screen.getByLabelText("Research hypothesis")).toBeEnabled();
});
it.each(["auth", "actor"])("clears the finite pending save identity on %s changes", async cause => {
  const { f, view } = await setup(); let resolve!: (value: unknown) => void;
  vi.mocked(discoveryConditionBatchCommit).mockImplementation(() => new Promise(done => { resolve = done; }));
  fireEvent.click(await prepare(true)); await waitFor(() => expect(resolve).toBeTypeOf("function"));
  if (cause === "auth") { act(() => notifyAuthChange()); fireEvent.click(screen.getByRole("button", { name: "Refresh access" })); }
  else {
    actor.id = "00000000-0000-0000-0000-000000000001";
    vi.mocked(discoveryDesignCapabilities).mockResolvedValue({ ...copy(f.design), actor_user_id: actor.id });
    vi.mocked(discoveryConditionBatchCapabilities).mockResolvedValue({ ...copy(f.cap), actor_user_id: actor.id });
    view.rerender(<DiscoveryDesignWorkbench />);
  }
  await screen.findByRole("button", { name: "Load saved batches" });
  await act(async () => resolve(copy(f.childCommit)));
  expect(screen.queryByRole("button", { name: "Check original batch request" })).not.toBeInTheDocument();
  expect(screen.queryByText("Recorded candidate child")).not.toBeInTheDocument();
  expect(discoveryConditionBatchOutcome).not.toHaveBeenCalled(); expect(discoveryConditionBatchCommit).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText("Research hypothesis")).toHaveValue(""); expect(screen.getByLabelText("Research hypothesis")).toBeEnabled();
});
