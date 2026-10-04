import { createHash, webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DiscoveryQeResult } from "@/components/DiscoveryQeResult";
import { generateCombinedCandidates } from "@/lib/discovery-combined-candidates";
import { prepareQeInput, type PreparedQe, type QeFile } from "@/lib/discovery-qe-input";
import { inspectQeResult, readQeNativeOutput, QE_RESULT_LIMITS, type QeResultFiles } from "@/lib/discovery-qe-result";

const fixture = (name: string, extension: string) => readFileSync(resolve("tests/fixtures/qe-output", `${name}.${extension}`), "utf8");
const file = (name: string, source: string): QeFile => ({ name, bytes: new TextEncoder().encode(source) });
const decode = (file: QeFile) => new TextDecoder().decode(file.bytes);
const sha = (source: string | Uint8Array) => createHash("sha256").update(source).digest("hex");
const original = (name = "scf") => ({ manifest: JSON.parse(fixture(name, "json")) }) as PreparedQe;
const xml = fixture("scf", "xml"), stdout = fixture("scf", "out");
beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

// Synthetic header-only UPFs exercise reproducible file matching, not a solver.
// The captured SCF geometry and native readings stay unchanged; only the regenerated prefix changes.
async function localFiles(): Promise<QeResultFiles> {
  const old = original().manifest;
  const pseudos = old.pseudopotentials.map(item => file(item.filename, `<UPF version="2.0.1"><PP_HEADER element="${item.element}" functional="PBE" relativistic="scalar" has_so="false" is_coulomb="false" pseudo_type="PAW" z_valence="${item.valence_electrons}"/></UPF>`));
  const batch = await generateCombinedCandidates(old.construction_request);
  const prepared = await prepareQeInput(batch, old.candidate.id, old.settings, pseudos);
  const prefix = (id: string) => `sclib_${id.split(":")[1].slice(0, 16)}`;
  return { manifest: file(prepared.filename, prepared.json), input: file(prepared.manifest.files.execution.filename, prepared.executionInput),
    xml: file("data-file-schema.xml", xml.replaceAll(prefix(old.id), prefix(prepared.manifest.id))), stdout: file("pw.out", stdout), pseudos };
}

describe("Native PWSCF 7.5 output readings", () => {
  it("reads the actual bounded SCF fixture in Hartree, preserving force units and source atoms", () => {
    const result = readQeNativeOutput(original(), "execution", xml, stdout);
    expect(result.status).toBe("scf_reported_converged");
    expect(result.convergence.scf_steps).toBe(11);
    expect(result.observations.total_energy).toMatchObject({ value: -31.19334546679567, unit: "Hartree/cell", raw: "-3.119334546679567E+001" });
    expect(result.observations.total_energy!.value * 2).toBeCloseTo(-62.38669093, 8);
    expect(result.observations.valence_electrons!.value).toBe(9);
    expect(result.observations.fermi_energy!.value).toBeCloseTo(0.3275509208161235, 14);
    expect(result.observations.forces!.maximum_atom_norm).toBeCloseTo(Math.hypot(9.372140477715273e-7, 6.290655941780258e-6), 15);
    expect(result.observations.stress!.values).toHaveLength(9);
    expect(result.observations.final_atoms!.map(atom => atom.source_atom_id)).toEqual(original().manifest.candidate.atoms.map(atom => atom.id));
    expect(result.scientific_scope).toMatchObject({ tc_calculated: false, stable_host_validated: false, scientific_acceptance: false, ml_training_approved: false, database_write: false });
    expect(result.consistency).toMatchObject({ execution_authenticated: false, pseudopotential_execution_bytes_attested: false, stdout_energy_checked: true });
  });

  it.each(["initialization", "relax-initialization"])("does not turn the actual %s XML exit 255 into physical observations", name => {
    const result = readQeNativeOutput(original(name), "initialization", fixture(name, "xml"), fixture(name, "out"));
    expect(result.status).toBe("initialization_only");
    expect(result.engine.reported_exit_status).toBe(255);
    expect(result.convergence).toMatchObject({ scf_steps: 0, electronic_reported: false, scf_error_hartree: null });
    expect(Object.values(result.observations).every(value => value === null)).toBe(true);
  });

  it("reads native fixed-cell optimization status without claiming that zero steps moved the atoms", () => {
    const result = readQeNativeOutput(original("relax"), "execution", fixture("relax", "xml"), fixture("relax", "out"));
    expect(result.status).toBe("relaxation_reported_converged");
    expect(result.convergence).toMatchObject({ ionic_reported: true, ionic_steps: 0, electronic_reported: true });
    expect(() => readQeNativeOutput(original("relax"), "execution", fixture("relax", "xml"), fixture("relax", "out").replace('0 bfgs steps', '1 bfgs steps'))).toThrow(/optimization step counts/);
  });

  it("rejects an initialization log from a different atom and electron inventory", () => {
    expect(() => readQeNativeOutput(original("initialization"), "initialization", fixture("initialization", "xml"), fixture("relax-initialization", "out"))).toThrow(/Stdout atom count/);
  });

  it.each([
    ["wrong units", (s: string) => s.replace('Units="Hartree atomic units"', 'Units="Rydberg atomic units"')],
    ["unsupported creator", (s: string) => s.replace('VERSION="7.5"', 'VERSION="7.4"')],
    ["unsupported schema", (s: string) => s.replace('VERSION="25.05.21"', 'VERSION="24.01.01"')],
    ["DTD", (s: string) => '<!DOCTYPE espresso [<!ENTITY value "1">]>' + s],
    ["truncated XML", (s: string) => s.slice(0, -20)],
    ["duplicate energy", (s: string) => s.replace('</total_energy>', '<etot>1</etot></total_energy>')],
    ["wrong k mesh", (s: string) => s.replace('nk1="4"', 'nk1="6"')],
    ["wrong charge", (s: string) => s.replace('<tot_charge>0.000000000000000E+000', '<tot_charge>1.000000000000000E+000')],
    ["changed pseudopotential", (s: string) => s.replace('Al.pbe-n-kjpaw_psl.1.0.0.UPF', 'another.UPF')],
    ["changed position", (s: string) => s.replace('-2.970598445306019E-004', '-2.970598445306019E-001')],
    ["changed lattice", (s: string) => s.replace('<a1>5.941196890612692E+000', '<a1>6.941196890612692E+000')],
    ["tiny threshold mismatch", (s: string) => s.replace('<conv_thr>5.000000000000000E-009', '<conv_thr>5.010000000000000E-009')],
    ["inconsistent convergence error", (s: string) => s.replace('<scf_error>4.977058790058067E-009', '<scf_error>4.977058790058067E-003')],
    ["zero converged iterations", (s: string) => s.replace('<n_scf_steps>11', '<n_scf_steps>0')],
    ["extra DFT corrections", (s: string) => s.replace('</dft>', '<dftU/></dft>')],
    ["changed output spin", (s: string) => s.replace('<magnetization>\n      <lsda>false', '<magnetization>\n      <lsda>true')],
    ["invalid tensor dimensions", (s: string) => s.replace(/<stress rank="2" dims="[^"]+"/, '<stress rank="2" dims="1 9"')],
    ["non-finite energy", (s: string) => s.replace('-3.119334546679567E+001', 'NaN')],
  ])("rejects %s", (_, edit) => expect(() => readQeNativeOutput(original(), "execution", edit(xml), stdout)).toThrow());

  it.each([
    ["missing terminator", stdout.replace("JOB DONE.", "")],
    ["concatenated runs", stdout + stdout],
    ["fatal engine error", stdout + "\nError in routine test"],
    ["wrong energy", stdout.replace("-62.38669093", "-61.38669093")],
    ["wrong iterations", stdout.replace(/convergence has been achieved in\s+11/, "convergence has been achieved in 12")],
  ])("rejects stdout %s", (_, log) => expect(() => readQeNativeOutput(original(), "execution", xml, log)).toThrow());

  it("retains provisional status for nonconvergence or an incomplete native exit", () => {
    const nonconverged = xml.replace('<convergence_achieved>true', '<convergence_achieved>false');
    expect(readQeNativeOutput(original(), "execution", nonconverged, stdout).status).toBe("scf_not_converged");
    expect(readQeNativeOutput(original(), "execution", xml.replace('<exit_status>0', '<exit_status>3'), stdout).status).toBe("incomplete");
    expect(() => readQeNativeOutput(original(), "initialization", xml, stdout)).toThrow();
  });
});

describe("Original files and deterministic output record", () => {
  it("reconstructs the candidate and checks the manifest, exact input and full UPF bytes before reading", async () => {
    const files = await localFiles(), result = await inspectQeResult(files);
    expect(result.report.status).toBe("scf_reported_converged");
    expect(result.report.files.find(item => item.role === "input")!.sha256).toBe(sha(files.input.bytes));
    expect(result.sha256).toBe(sha(result.json));
    expect(await inspectQeResult(files)).toEqual(result);
    expect(result.report.candidate_id).toBe(original().manifest.candidate.id);
    expect(result.report.source_reference).toEqual(original().manifest.source_reference);
  });

  it.each(["manifest", "input", "pseudo"])("rejects edited %s bytes instead of silently relinking", async role => {
    const files = await localFiles();
    const changed = role === "pseudo" ? files.pseudos[0] : files[role as "manifest" | "input"];
    changed.bytes = new TextEncoder().encode(decode(changed) + " ");
    await expect(inspectQeResult(files)).rejects.toThrow(/manifest or UPF|differs from both/);
  });

  it("rejects over-limit files before decoding, and missing UPFs", async () => {
    const files = await localFiles();
    await expect(inspectQeResult({ ...files, xml: { name: "large.xml", bytes: new Uint8Array(QE_RESULT_LIMITS.xml + 1) } })).rejects.toThrow(/size limit/);
    await expect(inspectQeResult({ ...files, pseudos: [] })).rejects.toThrow(/original 1 to 8/);
    await expect(inspectQeResult({ ...files, manifest: file("invalid.json", "{}") })).rejects.toThrow(/original SCLib/);
  });

  it("copies all file bytes before asynchronous work", async () => {
    const files = await localFiles(); let release: () => void = () => {};
    const digest = vi.fn().mockImplementationOnce(async (algorithm, bytes) => { await new Promise<void>(resolve => { release = resolve; }); return webcrypto.subtle.digest(algorithm, bytes); }).mockImplementation((algorithm, bytes) => webcrypto.subtle.digest(algorithm, bytes));
    vi.stubGlobal("crypto", { subtle: { digest } });
    const pending = inspectQeResult(files);
    files.xml.bytes.fill(0); files.input.bytes.fill(0); files.pseudos[0].bytes.fill(0);
    release(); expect((await pending).report.status).toBe("scf_reported_converged");
  });
});

const fileObject = (file: QeFile) => {
  const result = new File([file.bytes], file.name);
  Object.defineProperty(result, "arrayBuffer", { value: async () => new Uint8Array(file.bytes).buffer });
  return result;
};
const upload = (files: QeResultFiles) => {
  for (const [role, label] of [["manifest", "Preparation manifest"], ["input", "Executed input"], ["xml", "QE XML output"], ["stdout", "QE stdout log"]] as const) {
    fireEvent.change(screen.getByLabelText(label), { target: { files: [fileObject(files[role])] } });
  }
  fireEvent.change(screen.getByLabelText("Original UPF files"), { target: { files: files.pseudos.map(fileObject) } });
};

describe("Local calculation reading UI", () => {
  it("reads, exports and clears stale results without any network request", async () => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    const view = render(<DiscoveryQeResult />);
    expect(screen.getByRole("button", { name: "Read QE output" })).toBeDisabled();
    upload(await localFiles()); fireEvent.click(screen.getByRole("button", { name: "Read QE output" }));
    await screen.findByRole("heading", { name: "QE reports electronic convergence" });
    expect(screen.getByText("9 per cell")).toBeInTheDocument();
    expect(screen.getByText("Prepare a follow-up calculation")).toBeInTheDocument();
    const blobs: Blob[] = []; vi.stubGlobal("URL", { createObjectURL: vi.fn((blob: Blob) => { blobs.push(blob); return "blob:output"; }), revokeObjectURL: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    fireEvent.click(screen.getByRole("button", { name: "Download reading" }));
    fireEvent.click(screen.getByRole("button", { name: "Download checksum" }));
    expect(blobs).toHaveLength(2);
    fireEvent.change(screen.getByLabelText("QE XML output"), { target: { files: [] } });
    expect(screen.queryByRole("button", { name: "Download reading" })).not.toBeInTheDocument();
    expect(screen.queryByText("Prepare a follow-up calculation")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear files" }));
    expect(screen.getByRole("button", { name: "Read QE output" })).toBeDisabled();
    expect(fetch).not.toHaveBeenCalled(); expect(view.container.textContent).not.toMatch(/[\u4e00-\u9fff]/);
  });

  it("does not restore a delayed reading after the selected files change", async () => {
    render(<DiscoveryQeResult />); const files = await localFiles(); upload(files);
    let release: (value: ArrayBuffer) => void = () => {};
    const delayed = new File([files.xml.bytes], files.xml.name);
    Object.defineProperty(delayed, "arrayBuffer", { value: () => new Promise<ArrayBuffer>(resolve => { release = resolve; }) });
    fireEvent.change(screen.getByLabelText("QE XML output"), { target: { files: [delayed] } });
    fireEvent.click(screen.getByRole("button", { name: "Read QE output" }));
    expect(screen.getByRole("status")).toHaveTextContent("Reconstructing");
    fireEvent.click(screen.getByRole("button", { name: "Clear files" }));
    await act(async () => { release(new Uint8Array(files.xml.bytes).buffer); });
    expect(screen.queryByRole("heading", { name: "QE reports electronic convergence" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Read QE output" })).toBeDisabled();
  });
});
