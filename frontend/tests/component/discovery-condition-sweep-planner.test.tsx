import { webcrypto } from "node:crypto";
import { Blob as NodeBlob } from "node:buffer";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DiscoveryConditionSweepPlanner } from "@/components/DiscoveryConditionSweepPlanner";
import { knownDesignCapabilities, type DesignEntry } from "@/lib/discovery-designs";
import wire from "../fixtures/discovery-designs-native.synthetic.json";

beforeEach(() => { vi.stubGlobal("crypto", webcrypto); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const cap = () => knownDesignCapabilities(wire.capabilities, wire.capabilities.actor_user_id)!;
const entry = () => structuredClone(wire.page.entries[0]) as DesignEntry;
function choices(pressure = "ambient\n0\n0.0\n10", temperature = "unspecified\n300") {
  fireEvent.click(screen.getByText("Plan a bounded condition sweep"));
  fireEvent.change(screen.getByLabelText("Pressure choices (GPa, one per line)"), { target: { value: pressure } });
  fireEvent.change(screen.getByLabelText("Temperature choices (K, one per line)"), { target: { value: temperature } });
  fireEvent.click(screen.getByRole("button", { name: "Estimate combinations" }));
}
it("estimates explicit aliases without generating or selecting a proposal", () => {
  const onSelect = vi.fn(); render(<DiscoveryConditionSweepPlanner entry={entry()} capabilities={cap()} onSelect={onSelect} />);
  choices();
  expect(screen.getByRole("region", { name: "Condition sweep estimate" })).toHaveTextContent("6 unique condition combinations from 8 raw combinations");
  expect(screen.getByText(/1 duplicate pressure choices/)).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Prepared condition scenarios" })).not.toBeInTheDocument();
  expect(onSelect).not.toHaveBeenCalled();
});
it("refuses empty and oversized axes without substituting zero or truncating", () => {
  render(<DiscoveryConditionSweepPlanner entry={entry()} capabilities={cap()} onSelect={vi.fn()} />);
  choices("", "300"); expect(screen.getByRole("alert")).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Condition sweep estimate" })).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Pressure choices (GPa, one per line)"), { target: { value: "0\n1\n2\n3\n4\n5\n6\n7\n8" } });
  fireEvent.click(screen.getByRole("button", { name: "Estimate combinations" }));
  expect(screen.getByRole("alert")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Generate scenarios" })).not.toBeInTheDocument();
});
it("selects requested conditions while preserving user action and leaving source values separate", async () => {
  const parent = entry(), original = structuredClone(parent), onSelect = vi.fn();
  render(<DiscoveryConditionSweepPlanner entry={parent} capabilities={cap()} onSelect={onSelect} />);
  choices(); fireEvent.click(screen.getByRole("button", { name: "Generate scenarios" }));
  fireEvent.click(await screen.findByRole("button", { name: "Use 10 GPa target · 300 K target" }));
  expect(onSelect).toHaveBeenCalledTimes(1);
  expect(onSelect.mock.calls[0][0]).toEqual({ ...original.design, target_conditions: { pressure: { kind: "specified", raw_gpa: "10" }, temperature_k: "300" } });
  expect(parent).toEqual(original);
  expect(screen.getByText(/The batch manifest remains local/)).toBeInTheDocument();
  expect(screen.queryByText(/band gap:/)).not.toBeInTheDocument();
});
it("downloads the actual bounded local manifest with source pins and no source values", async () => {
  let downloaded!: NodeBlob;
  vi.stubGlobal("Blob", NodeBlob);
  vi.spyOn(URL, "createObjectURL").mockImplementation(blob => { downloaded = blob as NodeBlob; return "blob:local-synthetic-test"; });
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  render(<DiscoveryConditionSweepPlanner entry={entry()} capabilities={cap()} onSelect={vi.fn()} />);
  choices("10\n20", "250\n300"); fireEvent.click(screen.getByRole("button", { name: "Generate scenarios" }));
  fireEvent.click(await screen.findByRole("button", { name: "Download sweep manifest" }));
  const data = JSON.parse(await downloaded.text());
  expect(data.scenarios).toHaveLength(4); expect(data.batch_saved).toBe(false); expect(data.atomic_sites_generated).toBe(false);
  expect(data.calculation_executed).toBe(false); expect(data.parent.record_sha256).toBe(wire.page.entries[0].record_sha256);
  expect(data.source_pins).not.toHaveProperty("values"); expect(data.source_pins).not.toHaveProperty("projection");
  expect(data.scenarios.every((row: { proposal: unknown }) => !Object.hasOwn(row.proposal as object, "values"))).toBe(true);
});
it("clears choices and ignores a late manifest after pagehide", async () => {
  let release!: () => Promise<void>, first = true;
  vi.stubGlobal("crypto", { subtle: { digest: vi.fn((algorithm: string, bytes: Uint8Array) => {
    const captured = new Uint8Array(bytes);
    if (!first) return webcrypto.subtle.digest(algorithm, captured);
    first = false; return new Promise<ArrayBuffer>(resolve => { release = async () => resolve(await webcrypto.subtle.digest(algorithm, captured)); });
  }) } });
  render(<DiscoveryConditionSweepPlanner entry={entry()} capabilities={cap()} onSelect={vi.fn()} />);
  choices("10", "300"); fireEvent.click(screen.getByRole("button", { name: "Generate scenarios" }));
  await waitFor(() => expect(release).toBeTypeOf("function"));
  act(() => { window.dispatchEvent(new Event("pagehide")); }); await act(async () => { await release(); });
  expect(screen.getByLabelText("Pressure choices (GPa, one per line)")).toHaveValue("");
  expect(screen.queryByRole("region", { name: "Prepared condition scenarios" })).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Condition sweep estimate" })).not.toBeInTheDocument();
});
