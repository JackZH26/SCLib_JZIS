import React from "react";
import { File as NodeFile } from "node:buffer";
import { webcrypto } from "node:crypto";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DiscoveryCalculationReturns } from "@/components/DiscoveryCalculationReturns";
import { ApiError, discoveryCalculationCapabilities, discoveryCalculationCommit, discoveryCalculationContext, discoveryCalculationDetail, discoveryCalculationFile, discoveryCalculationOutcome, discoveryCalculationPage, discoveryCalculationPreview } from "@/lib/api";
import { knownDesignCapabilities, knownDesignDetail } from "@/lib/discovery-designs";
import { notifyAuthChange } from "@/lib/auth-session";
import { knownCalculationRecovery } from "@/lib/discovery-calculations";
import { syntheticCalculationPreview, syntheticCalculationSaved } from "../fixtures/discovery-calculations.synthetic";
import wire from "../fixtures/discovery-calculations-native.synthetic.json";
vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(), discoveryCalculationCapabilities: vi.fn(), discoveryCalculationCommit: vi.fn(), discoveryCalculationContext: vi.fn(), discoveryCalculationDetail: vi.fn(), discoveryCalculationFile: vi.fn(), discoveryCalculationOutcome: vi.fn(), discoveryCalculationPage: vi.fn(), discoveryCalculationPreview: vi.fn() }));
beforeEach(() => { vi.resetAllMocks(); vi.stubGlobal("crypto", webcrypto); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const clone = <T,>(v: T): T => structuredClone(v);
async function setup() {
  const capabilities = knownDesignCapabilities(wire.design_capabilities, wire.capabilities.actor_user_id)!;
  const entry = (await knownDesignDetail(wire.parent, capabilities, wire.parent.design_id))!.entries[0];
  vi.mocked(discoveryCalculationCapabilities).mockResolvedValue(clone(wire.capabilities));
  vi.mocked(discoveryCalculationContext).mockResolvedValue(clone(wire.context));
  vi.mocked(discoveryCalculationPage).mockResolvedValue(clone(wire.page));
  vi.mocked(discoveryCalculationPreview).mockImplementation(body => syntheticCalculationPreview(body.request));
  vi.mocked(discoveryCalculationCommit).mockImplementation(body => syntheticCalculationSaved(body.request));
  const props = { capabilities, entry, onSaveDispatched: vi.fn(), onSaveResolved: vi.fn(), onScopeInvalid: vi.fn() };
  const result = render(<DiscoveryCalculationReturns {...props} />);
  await screen.findByRole("form", { name: "Return original calculation files" });
  return { ...result, props };
}
function chooseFiles() {
  for (const [role, label] of [["input", "QE input (.in)"], ["xml", "QE XML output"], ["stdout", "QE stdout log"], ["upf", "Original UPF files (1–8)"]] as const) {
    const files = wire.upload.request.files.flatMap((f, i) => f.role === role ? [new NodeFile([Buffer.from(wire.upload.files_base64[i], "base64")], f.name)] : []);
    fireEvent.change(screen.getByLabelText(label), { target: { files } });
  }
}
async function preview() {
  chooseFiles();
  fireEvent.change(screen.getByLabelText("Findings"), { target: { value: wire.upload.request.findings } });
  fireEvent.change(screen.getByLabelText("Research decision"), { target: { value: "continue" } });
  fireEvent.change(screen.getByLabelText("Reason for this decision"), { target: { value: wire.upload.request.reason } });
  fireEvent.change(screen.getByLabelText("Remaining unknowns (one per line, up to 16)"), { target: { value: wire.upload.request.unknowns.join("\n") } });
  fireEvent.click(screen.getByRole("checkbox")); fireEvent.click(screen.getByRole("button", { name: "Preview calculation return" }));
  await screen.findByRole("region", { name: "Exact calculation preview" });
}

it("requires deliberate file preview, association and decision, then shows original units and exact scope", async () => {
  await setup(); chooseFiles();
  expect(discoveryCalculationPreview).not.toHaveBeenCalled(); expect(discoveryCalculationCommit).not.toHaveBeenCalled();
  expect(screen.getByLabelText("Research decision")).toHaveValue(""); expect(screen.getByRole("checkbox")).not.toBeChecked();
  expect(screen.getByRole("button", { name: "Preview calculation return" })).toBeDisabled();
  await preview();
  const reading = within(screen.getByRole("region", { name: "Native calculation reading" }));
  expect(reading.getByText("Electronic convergence reported")).toBeInTheDocument();
  expect(reading.getByText("-31.1933454668 Hartree/cell")).toBeInTheDocument();
  expect(reading.getByText(/Basis and k-point convergence/)).toBeInTheDocument();
  expect(discoveryCalculationPreview).toHaveBeenCalledTimes(1);
  expect(vi.mocked(discoveryCalculationPreview).mock.calls[0][0].files_base64).toEqual(wire.upload.files_base64);
  expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]/);
});

it("saves a byte-pinned return and replays the saved report before downloading an original", async () => {
  const { props } = await setup(); await preview();
  fireEvent.click(screen.getByRole("button", { name: "Save original files and decision" }));
  await screen.findByRole("region", { name: "Saved calculation receipt" });
  expect(props.onSaveDispatched).toHaveBeenCalledTimes(1); expect(props.onSaveResolved).toHaveBeenCalledWith(props.onSaveDispatched.mock.calls[0][0]);
  const saved = await syntheticCalculationSaved(vi.mocked(discoveryCalculationCommit).mock.calls[0][0].request);
  vi.mocked(discoveryCalculationDetail).mockResolvedValue({ ...clone(wire.detail), receipt: saved });
  fireEvent.click(screen.getByRole("button", { name: "Read saved calculation" }));
  await screen.findByRole("region", { name: "Saved calculation detail" });
  const create = vi.fn(() => "blob:owned-test-file"), revoke = vi.fn(); vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke }));
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  vi.mocked(discoveryCalculationFile).mockResolvedValue(new Uint8Array(Buffer.from(wire.upload.files_base64[0], "base64")));
  fireEvent.click(screen.getByRole("button", { name: "Download input" }));
  await screen.findByText(/size and SHA-256 match the saved original/);
  expect(create).toHaveBeenCalledTimes(1); expect(click).toHaveBeenCalledTimes(1); await waitFor(() => expect(revoke).toHaveBeenCalledWith("blob:owned-test-file"), { timeout: 1500 });
  expect(discoveryCalculationFile).toHaveBeenCalledWith(saved.receipt_id, 0, wire.upload.request.files[0].size_bytes, expect.any(AbortSignal));
});

it("recovers a lost commit through GET, retains only hashes on hide and never repeats the upload", async () => {
  const { props, unmount } = await setup(); await preview();
  vi.mocked(discoveryCalculationCommit).mockRejectedValue(new TypeError("lost response after server save"));
  fireEvent.click(screen.getByRole("button", { name: "Save original files and decision" }));
  await screen.findByText(/Save outcome is unknown/);
  const pins = props.onSaveDispatched.mock.calls[0][0]; expect(knownCalculationRecovery(pins)).toBe(true);
  expect(JSON.stringify(pins)).not.toMatch(/files|findings|base64|Hartree/);
  const body = vi.mocked(discoveryCalculationCommit).mock.calls[0][0];
  act(() => { window.dispatchEvent(new Event("pagehide")); });
  expect(screen.queryByRole("region", { name: "Native calculation reading" })).not.toBeInTheDocument();
  unmount();
  render(<DiscoveryCalculationReturns {...props} entry={null} saveRecovery={pins} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Check original calculation request" })).toBeEnabled());
  vi.mocked(discoveryCalculationOutcome).mockResolvedValue(await syntheticCalculationSaved(body.request, true));
  fireEvent.click(screen.getByRole("button", { name: "Check original calculation request" }));
  await screen.findByRole("region", { name: "Saved calculation receipt" });
  expect(discoveryCalculationOutcome).toHaveBeenCalledWith(pins.requestKey, pins.requestSha, expect.any(AbortSignal));
  expect(discoveryCalculationCommit).toHaveBeenCalledTimes(1); expect(discoveryCalculationPreview).toHaveBeenCalledTimes(1);
});

it("withholds native numbers and downloads after a saved plan is withdrawn", async () => {
  await setup(); fireEvent.click(screen.getByRole("button", { name: "Load calculation history" }));
  await screen.findByRole("region", { name: "Calculation return history" });
  vi.mocked(discoveryCalculationDetail).mockResolvedValue(clone(wire.held_detail));
  fireEvent.click(screen.getByRole("button", { name: "Inspect return" }));
  await screen.findByRole("region", { name: "Saved calculation detail" });
  expect(screen.getByText(/Original files and quantities are withheld/)).toBeInTheDocument();
  expect(screen.queryByText(/-3.119334/)).not.toBeInTheDocument(); expect(screen.queryByRole("button", { name: "Download input" })).not.toBeInTheDocument();
});

it("rejects corrupted downloaded bytes and clears private readings after access loss", async () => {
  const { props } = await setup(); fireEvent.click(screen.getByRole("button", { name: "Load calculation history" }));
  await screen.findByRole("region", { name: "Calculation return history" });
  vi.mocked(discoveryCalculationDetail).mockResolvedValue(clone(wire.detail)); fireEvent.click(screen.getByRole("button", { name: "Inspect return" }));
  await screen.findByRole("region", { name: "Saved calculation detail" });
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  vi.mocked(discoveryCalculationFile).mockResolvedValue(new Uint8Array([1, 2]));
  fireEvent.click(screen.getByRole("button", { name: "Download input" }));
  await screen.findByText(/response could not be verified/); expect(click).not.toHaveBeenCalled();
  vi.mocked(discoveryCalculationCapabilities).mockRejectedValue(new ApiError(403, null, "access changed"));
  fireEvent.click(screen.getByRole("button", { name: "Refresh calculation access" }));
  await screen.findByText(/Private files and notes have been cleared/);
  expect(props.onScopeInvalid).toHaveBeenCalled(); expect(screen.queryByRole("region", { name: "Saved calculation detail" })).not.toBeInTheDocument();
});

it("invalidates a preview on proposal edits and ignores a late response after session changes", async () => {
  const { props, rerender } = await setup(); await preview();
  rerender(<DiscoveryCalculationReturns {...props} invalidationKey={1} />);
  expect(screen.queryByRole("button", { name: "Save original files and decision" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Refresh calculation access" }));
  await screen.findByRole("form", { name: "Return original calculation files" });
  let resolve!: (v: unknown) => void; vi.mocked(discoveryCalculationPage).mockImplementation(() => new Promise(r => { resolve = r; }));
  fireEvent.click(screen.getByRole("button", { name: "Load calculation history" }));
  act(() => notifyAuthChange()); await act(async () => resolve(clone(wire.page)));
  expect(screen.queryByRole("region", { name: "Calculation return history" })).not.toBeInTheDocument();
});
