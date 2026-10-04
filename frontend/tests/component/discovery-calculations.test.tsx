import { File as NodeFile } from "node:buffer";
import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { calculationByteSha, calculationRecovery, knownCalculationCapabilities, knownCalculationContext, knownCalculationPage, knownCalculationPreview, knownCalculationReading, knownCalculationReceipt, knownCalculationRecovery, knownCalculationRequest, prepareCalculationUpload, type CalculationFile, type CalculationReceipt } from "@/lib/discovery-calculations";
import { knownDesignCapabilities, knownDesignDetail } from "@/lib/discovery-designs";
import wire from "../fixtures/discovery-calculations-native.synthetic.json";
import { expressionCanonical, expressionSha } from "@/lib/source-expressions";

beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => vi.unstubAllGlobals());
const clone = <T,>(value: T): T => structuredClone(value);
const access = () => knownDesignCapabilities(wire.design_capabilities, wire.capabilities.actor_user_id)!;
const cap = () => knownCalculationCapabilities(wire.capabilities, access())!;
const ref = () => calculationRecovery(wire.commit as CalculationReceipt, wire.capabilities.actor_user_id);

it("replays actual owned SQL/HTTP preview, durable return, history, original decimal tokens and withdrawn scope", async () => {
  expect(wire.synthetic_actors_and_upf_headers).toBe(true); expect(wire.no_authenticated_execution).toBe(true);
  expect(access()).not.toBeNull(); expect(cap()).not.toBeNull();
  const parent = await knownDesignDetail(wire.parent, access(), wire.parent.design_id);
  expect(parent).not.toBeNull(); expect(await knownCalculationContext(wire.context, parent!.entries[0])).toEqual(wire.context);
  expect(knownCalculationRequest(wire.upload.request)).toBe(true); expect(knownCalculationRecovery(ref())).toBe(true);
  const preview = await knownCalculationPreview(wire.preview, cap(), ref());
  expect(preview?.reportText).toBe(wire.preview.report_canonical_json);
  expect(preview?.report?.observations.total_energy?.raw).toBe("-3.119334546679567E+001");
  for (const mode of ["commit", "outcome"] as const) expect((await knownCalculationReceipt(wire[mode], cap(), ref(), mode))?.receipt).toEqual(wire[mode]);
  const page = await knownCalculationPage(wire.page, cap(), wire.parent.design_id, 0);
  expect(page?.total).toBe(1); const item = page!.entries[0];
  expect((await knownCalculationReading(wire.detail, cap(), item))?.reportText).toBe(wire.detail.report_canonical_json);
  expect((await knownCalculationReading(wire.held_detail, cap(), item))?.report).toBeNull();
  expect((await knownCalculationReading(wire.held_detail, cap(), item))?.eligibility.eligible).toBe(false);
  for (let i = 0; i < wire.upload.files_base64.length; i++) expect(await calculationByteSha(Buffer.from(wire.upload.files_base64[i], "base64"))).toBe(wire.upload.request.files[i].sha256);
});

it("rejects cross-owner receipts, changed operation pins, authority inflation and changed raw native quantities", async () => {
  for (const change of [
    (v: any) => { v.scientific_acceptance = true; },
    (v: any) => { v.report.observations.total_energy.value = 300; },
    (v: any) => { v.report.observations.total_energy.unit = "K"; },
    (v: any) => { v.report_canonical_json += " "; },
    (v: any) => { v.report = null; },
    (v: any) => { v.design.next_action_sha256 = "a".repeat(64); },
    (v: any) => { v.request_canonical_json = v.request_canonical_json.replace('"findings":', '"findings":"duplicate","findings":'); },
    (v: any) => { v.report.execution_authenticated = true; },
  ]) { const bad = clone(wire.preview); change(bad); expect(await knownCalculationPreview(bad, cap(), ref())).toBeNull(); }
  expect(await knownCalculationPreview(wire.preview, { ...cap(), actor_user_id: "00000000-0000-0000-0000-000000000001" }, ref())).toBeNull();
  expect(await knownCalculationReceipt(wire.commit, cap(), { ...ref(), receiptId: "00000000-0000-0000-0000-000000000001" }, "commit")).toBeNull();
  expect(await knownCalculationPreview(wire.preview, { ...cap(), session_version: cap().session_version + 1 }, ref())).toBeNull();
  expect(knownCalculationCapabilities({ ...wire.capabilities, max_files: 12 }, access())).toBeNull();
});

it("does not expose report values for held scope or combine a detail with another history receipt", async () => {
  const item = (await knownCalculationPage(wire.page, cap(), wire.parent.design_id, 0))!.entries[0];
  expect(await knownCalculationReading({ ...wire.held_detail, report: wire.detail.report, report_canonical_json: wire.detail.report_canonical_json }, cap(), item)).toBeNull();
  const other = clone(item); other.receipt.report_sha256 = "b".repeat(64);
  expect(await knownCalculationReading(wire.detail, cap(), other)).toBeNull();
  expect(await knownCalculationPage({ ...wire.page, entries: [...wire.page.entries, ...wire.page.entries], total: 2 }, cap(), wire.parent.design_id, 0)).toBeNull();
});

it("hashes and encodes exact selected original bytes after validating the whole inventory", async () => {
  const { files, ...request } = wire.upload.request;
  const sources = files.map((f, i) => ({ role: f.role as CalculationFile["role"], file: new NodeFile([Buffer.from(wire.upload.files_base64[i], "base64")], f.name) as unknown as File })).reverse();
  const upload = await prepareCalculationUpload(request as Parameters<typeof prepareCalculationUpload>[0], sources);
  expect(upload).toEqual(wire.upload); expect(knownCalculationRequest(upload.request)).toBe(true);
  const read = vi.fn();
  await expect(prepareCalculationUpload(request as Parameters<typeof prepareCalculationUpload>[0], [{ role: "input", file: { name: "run.in", size: 1048577, arrayBuffer: read } as unknown as File }])).rejects.toThrow("Choose one");
  expect(read).not.toHaveBeenCalled();
  for (const change of [
    (r: any) => { r.files.reverse(); },
    (r: any) => { r.files[0].name = "../run.in"; },
    (r: any) => { r.unknowns = ["same", "same"]; },
    (r: any) => { r.decision = ""; },
    (r: any) => { r.files[0].size_bytes = 0; },
    (r: any) => { r.association = "verified"; },
  ]) { const bad = clone(wire.upload.request); change(bad); expect(knownCalculationRequest(bad)).toBe(false); }
});

it("rejects a fully re-signed receipt with internally inconsistent actor or file metadata", async () => {
  const bad = clone(wire.commit), payload = JSON.parse(bad.receipt_canonical_json);
  payload.actor_grant_id = "00000000-0000-0000-0000-000000000001";
  bad.receipt_canonical_json = expressionCanonical(payload); bad.receipt_sha256 = await expressionSha(bad.receipt_canonical_json);
  expect(await knownCalculationReceipt(bad, cap(), { actorId: cap().actor_user_id, requestKey: bad.request_key, requestSha: bad.request_sha256, design: bad.design }, "history")).toBeNull();
});
