import { webcrypto } from "node:crypto";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DashboardUserProvider } from "@/components/dashboard/user-context";
import { MaterialTableFieldWorkbench } from "@/components/MaterialTableFieldWorkbench";
import * as api from "@/lib/api";
import { notifyAuthChange } from "@/lib/auth-session";
import { compileTablePackage, readTableRecovery, type TableCaseRequest } from "@/lib/material-table-fields";
import { tableActor, tableCaseCap, tableSourceCap, tableMaterial, tablePackage, tableContext, tableDetail, tableSourceReceipt, tableCaseReceipt } from "../helpers/material-table-field-test-data";

vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(), materialTableFieldCaseCapabilities: vi.fn(), sourceTableExpressionCapabilities: vi.fn(), materialFieldCaseContext: vi.fn(), materialFieldCasePreview: vi.fn(), materialFieldCaseCommit: vi.fn(), materialFieldCaseOutcome: vi.fn(), sourceExpressionPreview: vi.fn(), sourceExpressionCommit: vi.fn(), sourceExpressionOutcome: vi.fn(), sourceTableExpressionList: vi.fn(), sourceTableExpressionDetail: vi.fn(), materialTableFieldCaseMaterial: vi.fn(), materialTableFieldCaseDetail: vi.fn() }));
const user = { id: tableActor, name: "Synthetic table curator", email: "curator@example.invalid", is_admin: false, is_reviewer: false } as api.User;
const field = "electronic_specific_heat_coefficient_source_value";
async function mount() {
  render(<DashboardUserProvider value={{ user, setUser: vi.fn() }}><MaterialTableFieldWorkbench initialMaterialId={tableMaterial} /></DashboardUserProvider>);
  await screen.findByText("Curator access");
}
async function upload() {
  const content = JSON.stringify(await tablePackage());
  const file = { size: content.length, name: "table.json", text: async () => content };
  fireEvent.change(screen.getByLabelText("Table package file"), { target: { files: [file] } });
  await screen.findByText("4 checked source cells");
}
beforeEach(() => {
  vi.stubGlobal("crypto", webcrypto); vi.clearAllMocks(); sessionStorage.clear();
  vi.mocked(api.materialTableFieldCaseCapabilities).mockResolvedValue(tableCaseCap);
  vi.mocked(api.sourceTableExpressionCapabilities).mockResolvedValue(tableSourceCap);
  vi.mocked(api.materialFieldCaseContext).mockImplementation(async () => tableContext());
  vi.mocked(api.sourceExpressionPreview).mockImplementation(async request => tableSourceReceipt(await compileTablePackage(request.package), request.request_key));
  vi.mocked(api.sourceExpressionCommit).mockImplementation(async request => tableSourceReceipt(await compileTablePackage(request.package), request.request_key, false));
  vi.mocked(api.materialFieldCasePreview).mockImplementation(async request => tableCaseReceipt(request as TableCaseRequest, true, field));
  vi.mocked(api.materialFieldCaseCommit).mockImplementation(async request => tableCaseReceipt(request as TableCaseRequest, false, field));
  vi.mocked(api.materialTableFieldCaseDetail).mockImplementation(async () => tableDetail());
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("shows all original cells and row units, then previews and saves once", async () => {
  await mount(); await upload();
  expect(screen.getByText("3.16 mJ/mol-at./K2")).toBeInTheDocument();
  expect(screen.getByText("501 K")).toBeInTheDocument();
  expect(api.sourceExpressionPreview).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Preview source import" }));
  fireEvent.click(await screen.findByRole("button", { name: "Save pending operation" }));
  await screen.findByRole("region", { name: "Saved pending operation" });
  expect(api.sourceExpressionCommit).toHaveBeenCalledOnce();
  expect(readTableRecovery(tableActor)).toEqual({ status: "empty" });
});

it("creates an exact pending target only after loading the retained record", async () => {
  await mount();
  expect(screen.getByRole("button", { name: "Preview field target" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Load exact record" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Preview field target" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Preview field target" }));
  fireEvent.click(await screen.findByRole("button", { name: "Save pending operation" }));
  await screen.findByRole("region", { name: "Saved pending operation" });
  expect(api.materialFieldCaseCommit).toHaveBeenCalledOnce();
  expect((vi.mocked(api.materialFieldCaseCommit).mock.calls[0][0] as TableCaseRequest).version).toBe("material-field-case-operation/1.2.0");
});

it("retains an unknown save for GET recovery without retrying POST", async () => {
  await mount(); await upload();
  vi.mocked(api.sourceExpressionCommit).mockRejectedValueOnce(new api.ApiError(503, null, "Unknown outcome"));
  fireEvent.click(screen.getByRole("button", { name: "Preview source import" }));
  fireEvent.click(await screen.findByRole("button", { name: "Save pending operation" }));
  await screen.findByRole("region", { name: "Original save recovery" });
  const request = vi.mocked(api.sourceExpressionPreview).mock.calls[0][0];
  const saved = await tableSourceReceipt(await compileTablePackage(request.package), request.request_key, false);
  saved.replayed = true;
  vi.mocked(api.sourceExpressionOutcome).mockResolvedValueOnce(saved);
  fireEvent.click(screen.getByRole("button", { name: "Check original request" }));
  await screen.findByRole("region", { name: "Original receipt confirmed" });
  expect(api.sourceExpressionCommit).toHaveBeenCalledOnce();
  expect(readTableRecovery(tableActor)).toEqual({ status: "empty" });
});

it("clears source text on an auth change and ignores a late file read", async () => {
  await mount();
  let finish!: (v: string) => void;
  const pending = new Promise<string>(done => { finish = done; });
  fireEvent.change(screen.getByLabelText("Table package file"), { target: { files: [{ size: 100, text: () => pending }] } });
  act(() => notifyAuthChange());
  await act(async () => finish(JSON.stringify(await tablePackage())));
  expect(screen.queryByText("4 checked source cells")).not.toBeInTheDocument();
  expect(api.sourceExpressionPreview).not.toHaveBeenCalled();
});

it("refuses a tampered table before any source operation", async () => {
  await mount();
  const p = await tablePackage(); p.expressions[0].table_binding.column_index = 2;
  const content = JSON.stringify(p);
  fireEvent.change(screen.getByLabelText("Table package file"), { target: { files: [{ size: content.length, text: async () => content }] } });
  await screen.findByText(/original source proof could not be verified/);
  expect(api.sourceExpressionPreview).not.toHaveBeenCalled();
  expect(api.sourceExpressionCommit).not.toHaveBeenCalled();
});
