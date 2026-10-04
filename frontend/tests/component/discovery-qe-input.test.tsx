import { createHash, webcrypto } from "node:crypto";
import { runInNewContext } from "node:vm";
import { act } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DiscoveryQeInput } from "@/components/DiscoveryQeInput";
import { generateCombinedCandidates, type CombinedBatch } from "@/lib/discovery-combined-candidates";
import { supercellModel } from "@/lib/discovery-site-candidates";
import { inspectQeUpf, prepareQeInput, qeCellVectors, qeFileSha256, UPF_BYTE_LIMIT, type QeFile, type QeSettings } from "@/lib/discovery-qe-input";

beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const sha = (text: string | Uint8Array) => createHash("sha256").update(text).digest("hex");
// Header-only synthetic fixtures exercise the reader, never represent solver-validated pseudopotentials.
const pseudo = (element: string, valence: number, attributes = ""): QeFile => ({ name: `${element}.fixture.UPF`, bytes: new TextEncoder().encode(`<UPF version="2.0.1"><PP_HEADER element=" ${element} " functional=" SLA  PW   PBX  PBC " relativistic="scalar" has_so="false" is_coulomb="false" pseudo_type="PAW" z_valence="${valence}" wfc_cutoff="60.0D0" rho_cutoff="480" ${attributes}/></UPF>`) });
const files = () => [pseudo("Mg", 10), pseudo("B", 3), pseudo("Al", 3), pseudo("C", 4)];
const settings = (): QeSettings => ({ calculation: "scf", ecutwfc: 60, ecutrho: 480, mesh: [2, 3, 4], shifts: [0, 1, 0], charge: 1, nspin: 1,
  smearing: "mv", degauss: 0.02, conv_thr: 1e-8, electron_maxstep: 100, mixing_beta: 0.3, max_seconds: 600, ionic_steps: 50, etot_conv_thr: 1e-5, forc_conv_thr: 1e-4,
  species: [{ element: "Mg", mass_amu: 24.305, starting_magnetization: null }, { element: "B", mass_amu: 10.81, starting_magnetization: null }, { element: "Al", mass_amu: 26.9815, starting_magnetization: null }, { element: "C", mass_amu: 12.011, starting_magnetization: null }] });
const batch = () => { const model = supercellModel("cod-1526507", [2, 2, 2]); return generateCombinedCandidates({ referenceId: model.reference.id, repeats: model.repeats, strain: "2",
  sites: [{ targetId: model.atoms.find(atom => atom.element === "Mg")!.id, replacements: "Al", vacancy: false, unchanged: false }, { targetId: model.atoms.find(atom => atom.element === "B")!.id, replacements: "C", vacancy: true, unchanged: false }] }); };
const co = (batch: CombinedBatch) => batch.candidates.find(item => item.composition.C)!;

describe("Explicit Quantum ESPRESSO input preparation", () => {
  it("hashes exact binary views across realms without including surrounding bytes or decoding text", async () => {
    const files = [new Uint8Array(), Uint8Array.from({ length: 256 }, (_, i) => i),
      new Uint8Array([99, 0, 255, 128, 13, 10, 77]).subarray(1, 6),
      runInNewContext("new Uint8Array([99, 0, 255, 128, 13, 10, 77]).subarray(1, 6)") as Uint8Array];
    for (const bytes of files) {
      const before = Array.from(bytes);
      expect(await qeFileSha256(bytes)).toBe(sha(Buffer.from(bytes)));
      expect(Array.from(bytes)).toEqual(before);
    }
    expect(await qeFileSha256(files[3])).toBe("6171db06a1c89b1ff8ab77e479d5df976ccd88a7b63567b4b18f413649e12ff3");
  });

  it("reconstructs the changed geometry and matches species order, valence, units and exact file hashes", async () => {
    const source = await batch(), candidate = co(source), config = settings();
    const result = await prepareQeInput(source, candidate.id, config, files());
    expect(result.manifest.candidate).toEqual(candidate);
    expect(result.manifest.expected_valence_electrons).toBe(121);
    expect(result.executionInput).toContain("nat = 24,"); expect(result.executionInput).toContain("ntyp = 4,");
    expect(result.executionInput).toContain("ATOMIC_SPECIES\nAl 26.9815 Al.fixture.UPF\nB 10.81 B.fixture.UPF\nC 12.011 C.fixture.UPF\nMg 24.305 Mg.fixture.UPF");
    expect(result.executionInput).toContain("K_POINTS automatic\n2 3 4 0 1 0\n");
    expect(result.executionInput).toContain("CELL_PARAMETERS angstrom\n6.287892 0 0\n-3.143946");
    expect(result.executionInput).toContain("ATOMIC_POSITIONS crystal\n");
    const positions = result.executionInput.split("ATOMIC_POSITIONS crystal\n")[1].split("K_POINTS")[0].trim().split("\n").map(line => line.split(" "));
    expect(positions.map(row => row[0])).toEqual(candidate.atoms.map(atom => atom.element));
    positions.forEach((row, i) => row.slice(1).forEach((value, j) => expect(Number(value)).toBeCloseTo(candidate.atoms[i].fractional[j], 13)));
    expect(result.executionInput).toMatch(/^[\x00-\x7f]*$/); expect(result.executionInput).not.toContain("\r");
    expect(result.executionInput).not.toMatch(/input_dft|press\s*=|temperature\s*=/);
    expect(result.initializationInput).toContain("nstep = 0,"); expect(result.executionInput).toContain("nstep = 1,");
    expect(result.manifest.files.execution.sha256).toBe(sha(result.executionInput));
    expect(result.manifest.files.initialization.sha256).toBe(sha(result.initializationInput));
    expect(result.sha256).toBe(sha(result.json));
    expect(result.manifest.pseudopotentials.map(item => item.sha256).sort()).toEqual(files().map(file => sha(file.bytes)).sort());
    expect(result.manifest.scope).toMatchObject({ calculation_executed: false, initialization_checked: false, target_pressure_gpa: null, stability_validated: false, tc_calculated: false, database_write: false });
    expect(config.species[0].element).toBe("Mg");
  });

  it("uses the actual vacancy composition and emits fixed-cell relaxation with explicit magnetic seeds", async () => {
    const source = await batch(), vacancy = source.candidates.find(item => !item.composition.C)!;
    const config = settings(); config.calculation = "relax"; config.nspin = 2; config.charge = 0;
    config.species = config.species.filter(item => item.element !== "C").map(item => ({ ...item, starting_magnetization: item.element === "Mg" ? 0.1 : -0.05 }));
    const result = await prepareQeInput(source, vacancy.id, config, files().filter(file => !file.name.startsWith("C.")));
    expect(result.executionInput).toContain("nat = 23,"); expect(result.executionInput).toContain("ntyp = 3,");
    expect(result.executionInput).toContain("&IONS\n ion_dynamics = 'bfgs',\n/"); expect(result.executionInput).not.toContain("&CELL");
    expect(result.executionInput).toContain("nstep = 50,"); expect(result.executionInput).toContain("starting_magnetization(3) = 0.1,");
    expect(result.manifest.expected_valence_electrons).toBe(118);
  });

  it("preserves all three cell angles in a general Cartesian basis", () => {
    const cell = { a: 4, b: 5, c: 6, alpha: 80, beta: 75, gamma: 110 };
    const vectors = qeCellVectors(cell), norm = (v: number[]) => Math.hypot(...v);
    expect(vectors.map(norm)).toEqual([4, 5, 6]);
    const angle = (a: number[], b: number[]) => Math.acos(a.reduce((n, value, i) => n + value * b[i], 0) / norm(a) / norm(b)) * 180 / Math.PI;
    expect(angle(vectors[1], vectors[2])).toBeCloseTo(80, 12); expect(angle(vectors[0], vectors[2])).toBeCloseTo(75, 12); expect(angle(vectors[0], vectors[1])).toBeCloseTo(110, 12);
  });

  it("rejects tampered coordinates, provenance and candidate identities", async () => {
    const source = await batch(), id = co(source).id;
    for (const edit of [(b: CombinedBatch) => { b.candidates[0].atoms[0].element = "H"; }, (b: CombinedBatch) => { b.source_reference.formula = "invented"; }, (b: CombinedBatch) => { b.boundary.energy_calculated = true; }]) {
      const changed = structuredClone(source); edit(changed);
      await expect(prepareQeInput(changed, id, settings(), files())).rejects.toThrow(/reproducible source/);
    }
    await expect(prepareQeInput(source, "foreign", settings(), files())).rejects.toThrow(/current batch/);
  });

  it("rejects missing, extra, duplicate and incorrectly identified pseudopotentials", async () => {
    const source = await batch(), id = co(source).id;
    for (const inputs of [files().slice(1), [...files(), pseudo("H", 1)], [pseudo("B", 3), ...files().slice(1)], [files()[0], { ...files()[1], name: files()[0].name }, ...files().slice(2)]]) {
      await expect(prepareQeInput(source, id, settings(), inputs)).rejects.toThrow(/exactly one/);
    }
  });

  it("rejects invalid settings, zero-electron cells and ambiguous spin endpoints", async () => {
    const source = await batch(), id = co(source).id;
    for (const change of [{ ecutwfc: NaN }, { ecutrho: 1 }, { mesh: [1, 0, 2] }, { shifts: [1, 2, 0] }, { conv_thr: 0 }, { electron_maxstep: 0 }, { nspin: 4 }, { smearing: "bad" }, { degauss: 0 }, { ionic_steps: 0 }]) {
      await expect(prepareQeInput(source, id, { ...settings(), ...change } as QeSettings, files())).rejects.toThrow();
    }
    const config = settings(); config.nspin = 2; config.species.forEach(item => { item.starting_magnetization = 0; });
    await expect(prepareQeInput(source, id, config, files())).rejects.toThrow(/nonzero/);
    config.species[0].starting_magnetization = 1;
    await expect(prepareQeInput(source, id, config, files())).rejects.toThrow(/starting spin/);
    const lowValence = files().map(file => ({ ...file, bytes: new TextEncoder().encode(new TextDecoder().decode(file.bytes).replace(/z_valence="\d+"/, 'z_valence="1"')) }));
    await expect(prepareQeInput(source, id, { ...settings(), charge: 24 }, lowValence)).rejects.toThrow(/no valence electrons/);
  });

  it("reports sub-header cutoffs without pretending that larger values establish convergence", async () => {
    const source = await batch();
    const result = await prepareQeInput(source, co(source).id, { ...settings(), ecutwfc: 20, ecutrho: 80 }, files());
    expect(result.manifest.warnings).toHaveLength(8);
    expect(result.manifest.scope.numerical_convergence_established).toBe(false);
  });

  it("rejects unsafe filenames, entity declarations, invalid XML and unsupported UPF physics", async () => {
    const file = pseudo("Mg", 10), text = new TextDecoder().decode(file.bytes);
    for (const name of ["../Mg.UPF", "Mg'.UPF", "Mg UPF", "Mg.UPF\n&system", "Mg.UPF.exe"]) await expect(inspectQeUpf({ ...file, name })).rejects.toThrow(/filename/);
    for (const bad of ["<!DOCTYPE UPF>" + text, "<!ENTITY x 'y'>" + text, "<UPF>", text.replace("2.0.1", "1.0"), text.replace("SLA  PW   PBX  PBC", "LDA"), text.replace('has_so="false"', 'has_so="true"'), text.replace('relativistic="scalar"', 'relativistic="full"'), text.replace('pseudo_type="PAW"', 'pseudo_type="Coulomb"')]) {
      await expect(inspectQeUpf({ ...file, bytes: new TextEncoder().encode(bad) })).rejects.toThrow();
    }
    await expect(inspectQeUpf({ ...file, bytes: new Uint8Array(UPF_BYTE_LIMIT + 1) })).rejects.toThrow(/8 MiB/);
    const metadata = await inspectQeUpf(file); expect(metadata.element).toBe("Mg"); expect(metadata.header_cutoffs_ry).toEqual({ wavefunction: 60, charge_density: 480 });
  });

  it("freezes settings, source geometry and original file bytes before asynchronous verification", async () => {
    const source = await batch(), candidate = co(source), config = settings(), inputFiles = files();
    let release: () => void = () => {};
    const digest = vi.fn().mockImplementationOnce(async (algorithm, bytes) => { await new Promise<void>(resolve => { release = resolve; }); return webcrypto.subtle.digest(algorithm, bytes); }).mockImplementation((algorithm, bytes) => webcrypto.subtle.digest(algorithm, bytes));
    vi.stubGlobal("crypto", { subtle: { digest } });
    const pending = prepareQeInput(source, candidate.id, config, inputFiles);
    config.ecutwfc = 999; inputFiles[0].bytes.fill(0); source.candidates[0].atoms[0].element = "H";
    release(); const result = await pending;
    expect(result.manifest.settings.ecutwfc).toBe(60);
    expect(result.manifest.pseudopotentials.find(item => item.element === "Mg")!.sha256).toBe(sha(files()[0].bytes));
    expect(result.manifest.candidate.atoms.some(atom => atom.element === "H")).toBe(false);
  });
});

describe("Quantum ESPRESSO preparation UI", () => {
  const fileObjects = () => files().map(file => { const result = new File([file.bytes], file.name); Object.defineProperty(result, "arrayBuffer", { value: async () => new Uint8Array(file.bytes).buffer }); return result; });
  function fill() {
    for (const [label, value] of [["Wavefunction cutoff (Ry)", "60"], ["Charge-density cutoff (Ry)", "480"], ["Al atomic mass (u)", "26.9815"], ["B atomic mass (u)", "10.81"], ["C atomic mass (u)", "12.011"], ["Mg atomic mass (u)", "24.305"]]) fireEvent.change(screen.getByLabelText(label), { target: { value } });
    for (const axis of ["a", "b", "c"]) fireEvent.change(screen.getByLabelText(`K-point mesh ${axis}`), { target: { value: "2" } });
  }
  it("reads local bytes, prepares downloads, and removes stale exports on edits or a different candidate", async () => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    const source = await batch(), candidate = co(source);
    const view = render(<DiscoveryQeInput key={candidate.id} batch={source} candidateId={candidate.id} />);
    fireEvent.click(screen.getByText("Prepare Quantum ESPRESSO input")); fill();
    fireEvent.change(screen.getByLabelText("UPF files"), { target: { files: fileObjects() } });
    await screen.findByText((_, element) => element?.tagName === "P" && element.textContent === "Mg: Mg.fixture.UPF");
    fireEvent.click(screen.getByRole("button", { name: "Prepare QE inputs" }));
    await screen.findByRole("heading", { name: "Inputs prepared" });
    const blobs: Blob[] = []; vi.stubGlobal("URL", { createObjectURL: vi.fn((blob: Blob) => { blobs.push(blob); return "blob:qe"; }), revokeObjectURL: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    fireEvent.click(screen.getByRole("button", { name: "Download QE manifest" })); expect(blobs).toHaveLength(1);
    fireEvent.change(screen.getByLabelText("Cell charge (electrons removed)"), { target: { value: "1" } });
    expect(screen.queryByRole("button", { name: "Download QE manifest" })).not.toBeInTheDocument();
    const other = source.candidates.find(item => item.id !== candidate.id)!;
    view.rerender(<DiscoveryQeInput key={other.id} batch={source} candidateId={other.id} />);
    expect(screen.getByLabelText("Wavefunction cutoff (Ry)")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Prepare QE inputs", hidden: true })).toBeDisabled();
    expect(screen.queryByLabelText("C atomic mass (u)")).not.toBeInTheDocument();
    expect(view.container.textContent).not.toMatch(/[\u4e00-\u9fff]/); expect(fetch).not.toHaveBeenCalled();
  });

  it("discards a delayed local file selection after the settings change", async () => {
    const source = await batch(), candidate = co(source); let release: (bytes: ArrayBuffer) => void = () => {};
    const file = new File([files()[0].bytes], "Mg.fixture.UPF"); Object.defineProperty(file, "arrayBuffer", { value: () => new Promise<ArrayBuffer>(resolve => { release = resolve; }) });
    render(<DiscoveryQeInput batch={source} candidateId={candidate.id} />); fireEvent.click(screen.getByText("Prepare Quantum ESPRESSO input"));
    fireEvent.change(screen.getByLabelText("UPF files"), { target: { files: [file] } });
    expect(screen.getByRole("status")).toHaveTextContent("Reading local");
    fireEvent.change(screen.getByLabelText("Cell charge (electrons removed)"), { target: { value: "1" } });
    await act(async () => { release(new Uint8Array(files()[0].bytes).buffer); });
    expect(screen.getByRole("button", { name: "Prepare QE inputs" })).toBeDisabled();
    expect(screen.queryByText("Mg: Mg.fixture.UPF", { exact: false })).not.toBeInTheDocument();
  });
});
