import { webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { act } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ResearchCatalogueBoard } from "@/components/ResearchCatalogueBoard";
import { DiscoveryResearchCycle } from "@/components/DiscoveryResearchCycle";
import { DiscoveryTabs } from "@/components/DiscoveryTabs";
import { DiscoveryDisclosure } from "@/components/DiscoveryDisclosure";
import { DiscoveryQeResult } from "@/components/DiscoveryQeResult";
import { DiscoveryQeInput } from "@/components/DiscoveryQeInput";
import { getResearchCatalogue } from "@/lib/discovery-research-catalogue";
import * as researchModel from "@/lib/discovery-research-model";
import { createResearchCaseInput, exportResearchCase, importResearchCase, prepareResearchCase, researchStateFromCatalogue, type ResearchCaseInput } from "@/lib/discovery-research-cycle";
import { generateCombinedCandidates } from "@/lib/discovery-combined-candidates";
import { prepareQeInput, type QeFile } from "@/lib/discovery-qe-input";
import type { QeResultFiles } from "@/lib/discovery-qe-result";

beforeEach(() => { vi.stubGlobal("crypto", webcrypto); window.history.replaceState(null, "", "/discovery"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; };
const definition = () => JSON.parse((screen.getByLabelText("Case definition JSON") as HTMLTextAreaElement).value) as ResearchCaseInput;
const setDefinition = (value: ResearchCaseInput) => fireEvent.change(screen.getByLabelText("Case definition JSON"), { target: { value: JSON.stringify(value) } });
async function ready(stateId?: string) {
  await waitFor(() => { expect((screen.getByLabelText("Case definition JSON") as HTMLTextAreaElement).value).not.toBe(""); if (stateId) expect(definition().state.catalogue_reference?.catalog_state_id).toBe(stateId); });
}
async function prepare() { await ready(); fireEvent.click(screen.getByRole("button", { name: "Prepare research case" })); return screen.findByRole("region", { name: "Current research case" }); }
function fileText(name: string, text: string, read?: () => Promise<string>) { const f = new File([text], name); Object.defineProperty(f, "text", { value: read ?? (async () => text) }); return f; }
function fileBytes(input: QeFile, read?: () => Promise<ArrayBuffer>) { const f = new File([input.bytes], input.name); Object.defineProperty(f, "arrayBuffer", { value: read ?? (async () => new Uint8Array(input.bytes).buffer) }); return f; }
const blobText = (blob: Blob) => new Promise<string>((resolve, reject) => { const r = new FileReader(); r.onload = () => resolve(String(r.result)); r.onerror = reject; r.readAsText(blob); });
function downloads() {
  const blobs: Blob[] = []; vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn((blob: Blob) => { blobs.push(blob); return "blob:research-case"; }) });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() }); return blobs;
}
async function savedCase(catalog = getResearchCatalogue()) { return prepareResearchCase(createResearchCaseInput(await researchStateFromCatalogue(catalog, catalog.states[0].id), "high_bandwidth")); }
function wholeWorkspace(catalog = getResearchCatalogue()) {
  return render(<DiscoveryTabs candidates={<ResearchCatalogueBoard catalog={catalog} />} research={<DiscoveryDisclosure id="discovery-cycle-tools" summary="Research cycle: bandwidth, carriers and geometry"><DiscoveryResearchCycle catalog={catalog} /></DiscoveryDisclosure>} />);
}
// Synthetic header-only UPFs exercise local custody and are never executed by a solver.
const pseudo = (element: string, valence: number): QeFile => ({ name: `${element}.test.UPF`, bytes: new TextEncoder().encode(`<UPF version="2.0.1"><PP_HEADER element="${element}" functional="PBE" relativistic="scalar" has_so="false" is_coulomb="false" pseudo_type="PAW" z_valence="${valence}"/></UPF>`) });
function uploadInputPseudos(elements: string[]) { fireEvent.change(screen.getByLabelText("UPF files"), { target: { files: elements.map(e => fileBytes(pseudo(e, e === "Mg" ? 2 : 3))) } }); }
function fillQe(elements: string[]) {
  for (const [label, value] of [["Wavefunction cutoff (Ry)", "60"], ["Charge-density cutoff (Ry)", "480"], ...elements.map(e => [`${e} atomic mass (u)`, e === "Mg" ? "24.305" : e === "Al" ? "26.9815" : "10.81"])]) fireEvent.change(screen.getByLabelText(label), { target: { value } });
  for (const axis of ["a", "b", "c"]) fireEvent.change(screen.getByLabelText(`K-point mesh ${axis}`), { target: { value: "2" } });
}

describe("Discovery catalogue and exact-state navigation", () => {
  it("starts with eight closed rows, then exposes 19 exact-state links without RPS or Tc scores", () => {
    const catalog = getResearchCatalogue(), view = render(<ResearchCatalogueBoard catalog={catalog} />), table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(9);
    expect(screen.queryByRole("link", { name: "Start a research case" })).not.toBeInTheDocument();
    for (const g of catalog.groups) fireEvent.click(screen.getByRole("button", { name: g.formula, expanded: false }));
    const links = screen.getAllByRole("link", { name: "Start a research case" }); expect(links).toHaveLength(19);
    expect(new Set(links.map(l => l.getAttribute("href")))).toEqual(new Set(catalog.states.map(s => `#research-state-${s.id.split(":")[1]}`)));
    expect(screen.getAllByText("Unranked", { exact: true })).toHaveLength(8);
    expect(within(table).queryByRole("columnheader", { name: /Tc|RPS score/ })).not.toBeInTheDocument();
    expect(view.container.textContent).not.toMatch(/(?:predicted|calculated) Tc:\s*\d|RPS:\s*\d/);
  });
  it("opens the exact state through tabs and disclosure, including a repeat of the current fragment", async () => {
    const catalog = getResearchCatalogue(); wholeWorkspace(catalog); await ready();
    fireEvent.click(screen.getByRole("button", { name: catalog.groups[1].formula }));
    const link = screen.getByRole("link", { name: "Start a research case" }), target = catalog.groups[1].state_ids[0];
    fireEvent.click(link); await waitFor(() => expect(screen.getByLabelText("Coordinate state")).toHaveValue(target));
    expect(screen.getByRole("tab", { name: "Research & tools" })).toHaveAttribute("aria-selected", "true");
    expect(document.getElementById("discovery-cycle-tools")).toHaveAttribute("open");
    await waitFor(() => expect(window.location.hash).toBe(link.getAttribute("href")));
    fireEvent.change(screen.getByLabelText("Coordinate state"), { target: { value: catalog.states[0].id } }); await ready(catalog.states[0].id);
    expect(window.location.hash).toBe(link.getAttribute("href")); fireEvent.click(link);
    await waitFor(() => expect(screen.getByLabelText("Coordinate state")).toHaveValue(target));
  });
});

describe("Research case custody through the user workflow", () => {
  it("rejects wrong return pins, records a decision, round-trips a file and derives a clean follow-up", async () => {
    render(<DiscoveryResearchCycle catalog={getResearchCatalogue()} />); await prepare();
    fireEvent.click(screen.getByText("Retain a pinned source or calculation return"));
    const original = JSON.parse((screen.getByLabelText("Return JSON") as HTMLTextAreaElement).value);
    const returned = { ...original, artifacts: definition().state.source_pins, findings: "Host coordinates remain a reference; electronic applicability is unresolved." };
    fireEvent.change(screen.getByLabelText("Return JSON"), { target: { value: JSON.stringify({ ...returned, binding: { ...returned.binding, action_sha256: "0".repeat(64) } }) } });
    fireEvent.click(screen.getByRole("button", { name: "Retain return" })); expect(await screen.findByRole("alert")).toHaveTextContent(/pins do not match/);
    expect(screen.getByRole("region", { name: "Current research case" })).toHaveTextContent("0 retained returns");
    fireEvent.change(screen.getByLabelText("Return JSON"), { target: { value: JSON.stringify(returned) } }); fireEvent.click(screen.getByRole("button", { name: "Retain return" }));
    await screen.findByLabelText("Decision branch"); fireEvent.change(screen.getByLabelText("Decision branch"), { target: { value: "contradictory_or_incompatible" } });
    fireEvent.change(screen.getByLabelText("Decision reason"), { target: { value: "Review source applicability before using the host as a comparison." } });
    fireEvent.click(screen.getByRole("button", { name: "Record research decision" })); await screen.findByRole("button", { name: "Prepare linked follow-up" });
    const blobs = downloads(); fireEvent.click(screen.getByRole("button", { name: "Export research case" })); await waitFor(() => expect(blobs).toHaveLength(1));
    const json = await blobText(blobs[0]), saved = await importResearchCase(json);
    expect(saved.decision?.decision).toBe("redirect"); expect(saved.returns).toHaveLength(1); expect(saved.authority.scientific_acceptance).toBe(false);
    fireEvent.change(screen.getByLabelText("Research case JSON file"), { target: { files: [fileText("saved.json", json)] } }); await screen.findByText("Imported and verified the exact research-case bytes.");
    fireEvent.click(screen.getByRole("button", { name: "Prepare linked follow-up" })); await screen.findByText("Prepared a linked follow-up source review. Previous physical evidence was not inherited.");
    expect(screen.getByRole("region", { name: "Current research case" })).toHaveTextContent("0 retained returns");
    expect(Object.values(definition().evidence).every(e => e.status === "unknown" && e.readings.length === 0)).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Export research case" })); await waitFor(() => expect(blobs).toHaveLength(2));
    const next = await importResearchCase(await blobText(blobs[1])); expect(next.parent).toMatchObject({ case_id: saved.binding.case_id, decision_sha256: saved.decision!.decision_sha256, properties_inherited: false });
    expect(next.returns).toHaveLength(0); expect(next.decision).toBeNull();
  });
  it("rejects an edited coordinate pin with an unchanged selected catalogue identity", async () => {
    render(<DiscoveryResearchCycle catalog={getResearchCatalogue()} />); await ready(); const changed = definition(); changed.state.structure!.sha256 = "0".repeat(64); setDefinition(changed);
    fireEvent.click(screen.getByRole("button", { name: "Prepare research case" })); await screen.findByRole("alert");
    expect(screen.queryByRole("region", { name: "Current research case" })).not.toBeInTheDocument();
  });
  it("rejects a self-consistent imported case with another source pin", async () => {
    const catalog = getResearchCatalogue(), state = await researchStateFromCatalogue(catalog, catalog.states[0].id); state.source_pins[0].sha256 = "0".repeat(64);
    const forged = await exportResearchCase(await prepareResearchCase(createResearchCaseInput(state, "high_bandwidth")));
    render(<DiscoveryResearchCycle catalog={catalog} />); await ready();
    fireEvent.change(screen.getByLabelText("Research case JSON file"), { target: { files: [fileText("self-hashed.json", forged.json)] } }); await screen.findByRole("alert");
    expect(screen.queryByRole("region", { name: "Current research case" })).not.toBeInTheDocument();
  });
  it("discards a valid delayed import after selecting another coordinate state", async () => {
    const catalog = getResearchCatalogue(), exported = await exportResearchCase(await savedCase(catalog)), delayed = deferred<string>();
    render(<DiscoveryResearchCycle catalog={catalog} />); await ready();
    fireEvent.change(screen.getByLabelText("Research case JSON file"), { target: { files: [fileText("old-state.json", exported.json, () => delayed.promise)] } });
    fireEvent.change(screen.getByLabelText("Coordinate state"), { target: { value: catalog.states[1].id } }); await ready(catalog.states[1].id);
    await act(async () => { delayed.resolve(exported.json); await new Promise(r => setTimeout(r, 30)); });
    expect(screen.queryByRole("region", { name: "Current research case" })).not.toBeInTheDocument(); expect(definition().state.catalogue_reference?.catalog_state_id).toBe(catalog.states[1].id);
  });
  it("discards a model that completes after selection changes", async () => {
    const catalog = getResearchCatalogue(), actual = await researchModel.prepareResearchModel(catalog, catalog.states[0].id), delayed = deferred<typeof actual>();
    vi.spyOn(researchModel, "prepareResearchModel").mockImplementationOnce(() => delayed.promise);
    render(<DiscoveryResearchCycle catalog={catalog} />); await ready(); fireEvent.click(screen.getByRole("button", { name: "Prepare model for QE" }));
    fireEvent.change(screen.getByLabelText("Coordinate state"), { target: { value: catalog.states[1].id } }); await ready(catalog.states[1].id);
    await act(async () => { delayed.resolve(actual); }); expect(screen.queryByText("Prepare Quantum ESPRESSO input")).not.toBeInTheDocument();
  });
  it("does not let an obsolete import borrow the newer action's valid generation", async () => {
    const catalog = getResearchCatalogue(), exported = await exportResearchCase(await savedCase(catalog));
    const nextModel = await researchModel.prepareResearchModel(catalog, catalog.states[1].id);
    const oldFile = deferred<string>(), nextWork = deferred<typeof nextModel>();
    vi.spyOn(researchModel, "prepareResearchModel").mockImplementationOnce(() => nextWork.promise);
    render(<DiscoveryResearchCycle catalog={catalog} />); await ready();
    fireEvent.change(screen.getByLabelText("Research case JSON file"), { target: { files: [fileText("obsolete.json", exported.json, () => oldFile.promise)] } });
    fireEvent.change(screen.getByLabelText("Coordinate state"), { target: { value: catalog.states[1].id } }); await ready(catalog.states[1].id);
    fireEvent.click(screen.getByRole("button", { name: "Prepare model for QE" }));
    await act(async () => { oldFile.resolve(exported.json); await new Promise(r => setTimeout(r, 30)); });
    expect(screen.queryByRole("region", { name: "Current research case" })).not.toBeInTheDocument();
    expect(definition().state.catalogue_reference?.catalog_state_id).toBe(catalog.states[1].id);
    await act(async () => { nextWork.resolve(nextModel); });
    expect(await screen.findByText("Prepare Quantum ESPRESSO input")).toBeInTheDocument();
  });
  it("invalidates prepared QE data on editing settings and removes local files for a new state", async () => {
    const catalog = getResearchCatalogue(); render(<DiscoveryResearchCycle catalog={catalog} />); await ready(); fireEvent.click(screen.getByRole("button", { name: "Prepare model for QE" }));
    fireEvent.click(await screen.findByText("Prepare Quantum ESPRESSO input")); const elements = Object.keys(catalog.states[0].composition).sort(); fillQe(elements); uploadInputPseudos(elements);
    const button = screen.getByRole("button", { name: "Prepare QE inputs" }); await waitFor(() => expect(button).toBeEnabled()); fireEvent.click(button);
    fireEvent.click(await screen.findByRole("button", { name: "Prepare case for this QE manifest" }));
    await screen.findByRole("region", { name: "Current research case" });
    expect(definition().action.kind).toBe("calculation");
    expect(definition().state.relation_to_catalogue).toBe("proposed_conditions");
    expect(definition().state.conditions).toEqual({ pressure_gpa: null, temperature_k: null, charge_state: 0, magnetic_state: "nonmagnetic" });
    const blobs = downloads(); fireEvent.click(screen.getByRole("button", { name: "Export research case" }));
    await waitFor(() => expect(blobs).toHaveLength(1)); const exported = await blobText(blobs[0]);
    fireEvent.change(screen.getByLabelText("Research case JSON file"), { target: { files: [fileText("qe-case.json", exported)] } });
    await screen.findByText("Imported and verified the exact research-case bytes.");
    fireEvent.change(screen.getByLabelText("Wavefunction cutoff (Ry)"), { target: { value: "65" } }); expect(screen.queryByRole("button", { name: "Prepare case for this QE manifest" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Coordinate state"), { target: { value: catalog.states[1].id } }); await ready(catalog.states[1].id);
    expect(screen.queryByText("Prepare Quantum ESPRESSO input")).not.toBeInTheDocument(); expect(screen.queryByRole("button", { name: "Download QE manifest" })).not.toBeInTheDocument();
  });
});

async function localOutputFiles(): Promise<QeResultFiles> {
  const fixture = (ext: string) => readFileSync(`tests/fixtures/qe-output/scf.${ext}`, "utf8"), old = JSON.parse(fixture("json"));
  const pseudos = old.pseudopotentials.map((p: { element: string; valence_electrons: number; filename: string }) => ({ ...pseudo(p.element, p.valence_electrons), name: p.filename }));
  const batch = await generateCombinedCandidates(old.construction_request), prepared = await prepareQeInput(batch, old.candidate.id, old.settings, pseudos);
  const bytes = (name: string, text: string) => ({ name, bytes: new TextEncoder().encode(text) }), prefix = (id: string) => `sclib_${id.split(":")[1].slice(0, 16)}`;
  return { manifest: bytes(prepared.filename, prepared.json), input: bytes(prepared.manifest.files.execution.filename, prepared.executionInput), xml: bytes("data-file-schema.xml", fixture("xml").replaceAll(prefix(old.id), prefix(prepared.manifest.id))), stdout: bytes("pw.out", fixture("out")), pseudos };
}
function uploadOutput(files: QeResultFiles, xml?: File) {
  for (const [role, label] of [["manifest", "Preparation manifest"], ["input", "Executed input"], ["xml", "QE XML output"], ["stdout", "QE stdout log"]] as const) fireEvent.change(screen.getByLabelText(label), { target: { files: [role === "xml" && xml ? xml : fileBytes(files[role])] } });
  fireEvent.change(screen.getByLabelText("Original UPF files"), { target: { files: files.pseudos.map(p => fileBytes(p)) } });
}

describe("QE callbacks cannot revive obsolete evidence", () => {
  it("refuses a readable output from a different preparation in the current calculation case", async () => {
    const catalog = getResearchCatalogue(); render(<DiscoveryResearchCycle catalog={catalog} />); await ready();
    fireEvent.click(screen.getByRole("button", { name: "Prepare model for QE" })); fireEvent.click(await screen.findByText("Prepare Quantum ESPRESSO input"));
    const elements = Object.keys(catalog.states[0].composition).sort(); fillQe(elements); uploadInputPseudos(elements);
    const button = screen.getByRole("button", { name: "Prepare QE inputs" }); await waitFor(() => expect(button).toBeEnabled()); fireEvent.click(button);
    fireEvent.click(await screen.findByRole("button", { name: "Prepare case for this QE manifest" })); await screen.findByRole("region", { name: "Current research case" });
    fireEvent.click(screen.getByText("Read original QE output")); uploadOutput(await localOutputFiles());
    fireEvent.click(screen.getByRole("button", { name: "Read QE output" })); await screen.findByRole("heading", { name: "QE reports electronic convergence" });
    fireEvent.click(screen.getByRole("button", { name: "Retain reading in this case" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/different preparation manifest/);
    expect(screen.getByRole("region", { name: "Current research case" })).toHaveTextContent("0 retained returns");
  });
  it("does not emit a stale output context after clearing an in-flight original-file read", async () => {
    const files = await localOutputFiles(), onContext = vi.fn(), delayed = deferred<ArrayBuffer>();
    render(<DiscoveryQeResult onContext={onContext} />); uploadOutput(files, fileBytes(files.xml, () => delayed.promise));
    fireEvent.click(screen.getByRole("button", { name: "Read QE output" })); fireEvent.click(screen.getByRole("button", { name: "Clear files" }));
    await act(async () => { delayed.resolve(new Uint8Array(files.xml.bytes).buffer); await new Promise(r => setTimeout(r, 30)); });
    expect(onContext.mock.calls.every(([value]) => value === null)).toBe(true); expect(screen.queryByRole("button", { name: "Download reading" })).not.toBeInTheDocument();
  });
  it("does not emit a preparation after the candidate component unmounts", async () => {
    const catalog = getResearchCatalogue(), model = await researchModel.prepareResearchModel(catalog, catalog.states[0].id), onPrepared = vi.fn();
    const view = render(<DiscoveryQeInput batch={model.batch} candidateId={model.candidateId} onPrepared={onPrepared} />);
    fireEvent.click(screen.getByText("Prepare Quantum ESPRESSO input")); const elements = Object.keys(catalog.states[0].composition).sort(); fillQe(elements); uploadInputPseudos(elements);
    const button = screen.getByRole("button", { name: "Prepare QE inputs" }); await waitFor(() => expect(button).toBeEnabled());
    const delayed = deferred<void>(); let first = true;
    vi.stubGlobal("crypto", { subtle: { digest: async (algorithm: AlgorithmIdentifier, input: BufferSource) => { if (first) { first = false; await delayed.promise; } return webcrypto.subtle.digest(algorithm, input as never); } } });
    fireEvent.click(button); view.unmount(); await act(async () => { delayed.resolve(); await new Promise(r => setTimeout(r, 30)); });
    expect(onPrepared.mock.calls.every(([value]) => value === null)).toBe(true);
  });
});
