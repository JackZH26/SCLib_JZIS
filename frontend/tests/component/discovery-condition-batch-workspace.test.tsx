import { webcrypto } from "node:crypto";
import { Blob as NodeBlob } from "node:buffer";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DiscoveryConditionBatchWorkspace } from "@/components/DiscoveryConditionBatchWorkspace";
import { ApiError, discoveryConditionBatchCapabilities, discoveryConditionBatchPreview, discoveryConditionBatchCommit, discoveryConditionBatchOutcome, discoveryConditionBatchPage, discoveryConditionBatchDetail, discoveryConditionBatchManifest } from "@/lib/api";
import { notifyAuthChange } from "@/lib/auth-session";
import { expressionSha } from "@/lib/source-expressions";
import { copy, syntheticBatch, TEST_UUID } from "./discovery-condition-batches.synthetic";

vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(), discoveryConditionBatchCapabilities: vi.fn(), discoveryConditionBatchPreview: vi.fn(), discoveryConditionBatchCommit: vi.fn(), discoveryConditionBatchOutcome: vi.fn(), discoveryConditionBatchPage: vi.fn(), discoveryConditionBatchDetail: vi.fn(), discoveryConditionBatchManifest: vi.fn() }));
beforeEach(() => { vi.resetAllMocks(); vi.stubGlobal("crypto", { subtle: webcrypto.subtle, randomUUID: () => TEST_UUID }); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function setup(generated = true) {
  const f = await syntheticBatch(), onOpenChild = vi.fn();
  vi.mocked(discoveryConditionBatchCapabilities).mockResolvedValue(copy(f.cap));
  vi.mocked(discoveryConditionBatchPreview).mockImplementation(request => Promise.resolve(copy(request.operation === "retain_batch" ? f.preview : f.childPreview)));
  vi.mocked(discoveryConditionBatchCommit).mockImplementation(request => Promise.resolve(copy(request.operation === "retain_batch" ? f.commit : f.childCommit)));
  vi.mocked(discoveryConditionBatchOutcome).mockResolvedValue(copy(f.outcome));
  vi.mocked(discoveryConditionBatchPage).mockResolvedValue(copy(f.page));
  vi.mocked(discoveryConditionBatchDetail).mockImplementation((_id, offset) => Promise.resolve(copy(f.detail(offset))));
  vi.mocked(discoveryConditionBatchManifest).mockResolvedValue(f.text);
  const onScopeInvalid = vi.fn(), onSaveDispatched = vi.fn(), onSaveResolved = vi.fn();
  const props = { capabilities: f.design, generated: generated ? f.manifest : null, onOpenChild, onScopeInvalid, onSaveDispatched, onSaveResolved }, view = render(<DiscoveryConditionBatchWorkspace {...props} />);
  await screen.findByRole("button", { name: "Load saved batches" });
  return { f, props, view, onOpenChild };
}
async function inspect() { fireEvent.click(screen.getByRole("button", { name: "Load saved batches" })); fireEvent.click(await screen.findByRole("button", { name: "Inspect batch" })); await screen.findByRole("region", { name: "Retained batch scenarios" }); }
it("requires separate explicit preview and retention clicks with exact request pins", async () => {
  const { f, props } = await setup();
  expect(discoveryConditionBatchPreview).not.toHaveBeenCalled(); expect(discoveryConditionBatchCommit).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Preview batch retention" }));
  const save = await screen.findByRole("button", { name: "Retain private batch" });
  expect(discoveryConditionBatchCommit).not.toHaveBeenCalled();
  expect(vi.mocked(discoveryConditionBatchPreview).mock.calls[0][0]).toEqual(f.request);
  fireEvent.click(save); await screen.findByText("Recorded batch retention");
  expect(discoveryConditionBatchCommit).toHaveBeenCalledTimes(1); expect(vi.mocked(discoveryConditionBatchCommit).mock.calls[0].slice(0, 2)).toEqual([f.request, f.preview.preview_sha256]);
  const minimal = { actorId: f.cap.actor_user_id, requestKey: f.request.request_key, requestSha: f.preview.request_sha256, previewSha: f.preview.preview_sha256, receiptSha: f.preview.receipt_sha256, receiptId: f.preview.receipt_id, inputSha: f.preview.input_sha256 };
  expect(props.onSaveDispatched).toHaveBeenCalledWith(minimal); expect(props.onSaveResolved).toHaveBeenCalledWith(minimal);
  expect(Object.keys(props.onSaveDispatched.mock.calls[0][0]).sort()).toEqual(Object.keys(minimal).sort());
});
it("pages eight exact retained scenarios and exports original bytes and a labeled body checksum", async () => {
  const { f } = await setup(false); await inspect();
  expect(within(screen.getByRole("region", { name: "Retained scenario window" })).getAllByRole("row")).toHaveLength(9);
  fireEvent.click(screen.getByRole("button", { name: "Next retained scenarios" }));
  await waitFor(() => expect(vi.mocked(discoveryConditionBatchDetail).mock.calls.at(-1)![1]).toBe(8));
  await screen.findByText("9–12 of 12");
  expect(within(screen.getByRole("region", { name: "Retained scenario window" })).getAllByRole("row")).toHaveLength(5);
  const downloads: NodeBlob[] = []; vi.stubGlobal("Blob", NodeBlob);
  vi.spyOn(URL, "createObjectURL").mockImplementation(blob => { downloads.push(blob as NodeBlob); return "blob:test-owned-batch"; }); vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {}); vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  fireEvent.click(screen.getByRole("button", { name: "Export exact manifest" })); fireEvent.click(screen.getByRole("button", { name: "Export file checksum" }));
  expect(await downloads[0].text()).toBe(f.text); expect(await downloads[1].text()).toBe(`${await expressionSha(f.text)}  sclib-condition-batch-${f.manifest.manifest_sha256.slice(0, 12)}.json\n`);
  expect(JSON.parse(await downloads[0].text()).batch_saved).toBe(false);
  expect(screen.getByText(/Manifest body SHA-256:/)).toBeInTheDocument(); expect(discoveryConditionBatchCommit).not.toHaveBeenCalled();
});
it("previews an exact candidate and explicitly saves its child before opening native history", async () => {
  const { f, onOpenChild } = await setup(false); await inspect();
  fireEvent.click(screen.getAllByRole("button", { name: /^Preview child for/ })[0]);
  const save = await screen.findByRole("button", { name: "Save candidate child" }); expect(discoveryConditionBatchCommit).not.toHaveBeenCalled(); expect(onOpenChild).not.toHaveBeenCalled();
  expect(vi.mocked(discoveryConditionBatchPreview).mock.calls[0][0]).toEqual(f.childRequest);
  fireEvent.click(save); fireEvent.click(await screen.findByRole("button", { name: "Open saved child history" }));
  expect(onOpenChild).toHaveBeenCalledWith(f.pin); expect(discoveryConditionBatchCommit).toHaveBeenCalledTimes(1);
});
it("recovers an uncertain save using only the original GET key and SHA", async () => {
  const { f } = await setup(); vi.mocked(discoveryConditionBatchCommit).mockRejectedValue(new ApiError(0, null, "Synthetic interrupted response"));
  fireEvent.click(screen.getByRole("button", { name: "Preview batch retention" })); fireEvent.click(await screen.findByRole("button", { name: "Retain private batch" }));
  const check = await screen.findByRole("button", { name: "Check original batch request" });
  expect(screen.queryByRole("button", { name: "Retain private batch" })).not.toBeInTheDocument(); expect(screen.getByRole("button", { name: "Preview batch retention" })).toBeDisabled();
  fireEvent.click(check); await screen.findByText("Recorded batch retention");
  expect(vi.mocked(discoveryConditionBatchOutcome).mock.calls[0].slice(0, 2)).toEqual([f.request.request_key, f.preview.request_sha256]);
  expect(discoveryConditionBatchCommit).toHaveBeenCalledTimes(1); expect(discoveryConditionBatchPreview).toHaveBeenCalledTimes(1);
});
it("keeps held artifacts inspectable and permits opening existing children without a new preview", async () => {
  const { f, onOpenChild } = await setup(false), detail = copy(f.detail());
  detail.entry.eligibility = { eligible: false, reason_codes: ["parent_withdrawn"] }; detail.scenarios[0].child = f.pin as never;
  vi.mocked(discoveryConditionBatchDetail).mockResolvedValue(detail); await inspect();
  expect(screen.getByRole("button", { name: "Export exact manifest" })).toBeEnabled();
  expect(screen.getAllByRole("button", { name: /^Preview child for/ }).every(b => b.hasAttribute("disabled"))).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: /^Open child history for/ })); expect(onOpenChild).toHaveBeenCalledWith(f.pin); expect(discoveryConditionBatchPreview).not.toHaveBeenCalled();
});
it.each(["pagehide", "auth", "edit", "actor"])("clears prepared batch state and ignores late previews after %s", async cause => {
  const { props, view } = await setup(); let resolve!: (value: unknown) => void;
  vi.mocked(discoveryConditionBatchPreview).mockImplementation(() => new Promise(r => { resolve = r; }));
  fireEvent.click(screen.getByRole("button", { name: "Preview batch retention" })); await waitFor(() => expect(resolve).toBeTypeOf("function"));
  if (cause === "pagehide") act(() => { window.dispatchEvent(new Event("pagehide")); });
  else if (cause === "auth") act(() => notifyAuthChange());
  else if (cause === "edit") view.rerender(<DiscoveryConditionBatchWorkspace {...props} generated={null} invalidationKey={1} />);
  else view.rerender(<DiscoveryConditionBatchWorkspace {...props} capabilities={{ ...props.capabilities, actor_user_id: "00000000-0000-0000-0000-000000000001" }} />);
  await act(async () => { resolve((await syntheticBatch()).preview); });
  expect(screen.queryByRole("button", { name: "Retain private batch" })).not.toBeInTheDocument(); expect(discoveryConditionBatchCommit).not.toHaveBeenCalled();
});
it("withholds child preview if the detail differs from the exact retained artifact", async () => {
  const { f } = await setup(false), detail = copy(f.detail()); detail.scenarios[0].proposal.next_action.question = "Unsealed action";
  vi.mocked(discoveryConditionBatchDetail).mockResolvedValue(detail); fireEvent.click(screen.getByRole("button", { name: "Load saved batches" })); fireEvent.click(await screen.findByRole("button", { name: "Inspect batch" }));
  await screen.findByText(/batch response could not be verified/i); expect(screen.queryByRole("button", { name: /^Preview child for/ })).not.toBeInTheDocument(); expect(discoveryConditionBatchPreview).not.toHaveBeenCalled();
});
it("clears a prepared operation on draft edits without repeating capability reads", async () => {
  const { props, view } = await setup(); fireEvent.click(screen.getByRole("button", { name: "Preview batch retention" })); await screen.findByRole("button", { name: "Retain private batch" });
  view.rerender(<DiscoveryConditionBatchWorkspace {...props} invalidationKey={1} />);
  expect(screen.queryByRole("button", { name: "Retain private batch" })).not.toBeInTheDocument(); expect(discoveryConditionBatchCapabilities).toHaveBeenCalledTimes(1);
});
it("uses English default copy without repeating source-policy prose in each scenario", async () => {
  const { view } = await setup(false); await inspect();
  expect(view.container.textContent).not.toMatch(/[\u4e00-\u9fff]/);
  expect(screen.getAllByText(/Requested conditions remain proposals/)).toHaveLength(1);
  const table = screen.getByRole("region", { name: "Retained scenario window" }); expect(table).toHaveClass("max-w-full", "overflow-x-auto");
  for (const row of within(table).getAllByRole("row").slice(1)) expect(row).toHaveClass("block", "sm:table-row");
});
it.each([401, 403, 409])("propagates scope status %s to clear the parent private reference", async status => {
  const { props } = await setup(); const error = new ApiError(status, null, "Synthetic changed scope"); vi.mocked(discoveryConditionBatchPreview).mockRejectedValue(error);
  fireEvent.click(screen.getByRole("button", { name: "Preview batch retention" })); await waitFor(() => expect(props.onScopeInvalid).toHaveBeenCalledWith(error));
  expect(screen.queryByRole("button", { name: "Retain private batch" })).not.toBeInTheDocument();
});
