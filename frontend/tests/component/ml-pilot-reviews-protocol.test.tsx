import { webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as review from "@/lib/ml-pilot-reviews";
import { canonical, changed, controls, coverageReply, digest, documents, native, own, recoveryFor, reference, sha } from "../helpers/ml-review-wire";

beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
describe("native own-review declaration protocol", () => {
  it.each([0, 1, 2])("verifies participant %i original joint snapshots without implying scientific acceptance", index => {
    const p = native.participants[index], basis = review.parseReviewPreflight(p.preflight, p.actor_user_id, reference(p), documents(p));
    for (const phase of ["initial", "complete", "withdrawn"] as const) {
      const value = review.parseReviewCoverage(coverageReply(phase, p), p.actor_user_id, reference(p), basis);
      expect(value.account_declarations_complete).toBe(phase === "complete");
      expect(value.own_declaration_status).toBe(phase === "initial" ? "missing" : phase === "complete" ? "current" : "withdrawn");
    }
  });
  it.each(["scope", "version", "actor", "reference", "source", "implementation", "record_count", "sum", "negative", "fraction", "required", "complete", "author", "own", "not_required", "date", "scientific", "signoff", "write", "freshness", "extra"])("rejects misleading joint coverage: %s", name => {
    let raw = changed(coverageReply(), v => {
      if (name === "scope") v.scope = "approved";
      if (name === "version") v.version = "old";
      if (name === "actor") v.actor_user_id = native.participants.find(p => p.actor_user_id !== own.actor_user_id)!.actor_user_id;
      if (name === "reference") v.participant_sha256 = "f".repeat(64);
      if (name === "source") v.input_pins.reviews_file_sha256 = "f".repeat(64);
      if (name === "implementation") v.implementation_sha256 = "f".repeat(64);
      if (name === "record_count") v.review_record_count = 60;
      if (name === "sum") v.missing_declaration_count = 1;
      if (name === "negative") v.stale_declaration_count = -1;
      if (name === "required") v.required_declaration_count = 31;
      if (name === "complete") v.account_declarations_complete = false;
      if (name === "author") v.conclusion_author_declaration_current = false;
      if (name === "own") v.own_declaration_status = "missing";
      if (name === "not_required") v.own_declaration_status = "not_required";
      if (name === "date") v.snapshot_started_at = "2026-02-30T00:00:00Z";
      if (name === "scientific") v.scientific_pilot_accepted = true;
      if (name === "signoff") v.current_collective_signoff_verified = true;
      if (name === "write") v.attestation_recorded = true;
      if (name === "freshness") v.historical_snapshot_only = false;
      if (name === "extra") v.other_reviewer_ids = ["PRIVATE_CANARY"];
    });
    if (name === "fraction") raw = raw.replace('"matching_declaration_count":3', '"matching_declaration_count":2.5');
    const basis = review.parseReviewPreflight(own.preflight, own.actor_user_id, reference(), documents());
    expect(() => review.parseReviewCoverage(raw, own.actor_user_id, reference(), basis)).toThrow();
  });
  it("pins current original replies without resealing historical evidence", () => {
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-pilot-attestations-native.delivery20260921.wire.json")))).toBe("5b80af85e4aff943c87ac19f639743d232ab11086a12db3a4103a81579103761");
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-pilot-attestations-native.batch75.wire.json")))).toBe("4c55cf055b23be8554cf3eceb9edcda20bb4f3657b0d1c8eeacdc6f261d517b8");
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-pilot-attestations-native.batch73.wire.json")))).toBe("9efd63d963bd8a4c0a2ecb8c2294ea4cd615833a35a9f8d49acd49e560c90bb0");
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-pilot-attestations-native.batch74.wire.json")))).toBe("f5f3f68dbf52e65eaf713e243b2015420c544415c00e498fce7b6982eb135cb6");
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-pilot-attestations-native.batch72.wire.json")))).toBe("cd45d0b65b86fc9ea2d33e90ff3b150ebd4c392512e956e2810156cea1e30c3b");
    expect(native.capture_test_path).toBe("api/tests/test_ml_pilot_attestations.py"); expect(native.fixture_notice).toContain("synthetic, not a real independent review");
    expect(native.source_pins).toHaveLength(598);
    expect(new Set(native.source_pins.map(p => p.path)).size).toBe(598);
    expect(native.coverage).toHaveLength(9);
    for (const p of native.source_pins) { expect(p.path).toMatch(/^(api|scripts)\/[A-Za-z0-9_./-]+\.(py|schema\.json)$/); expect(p.path.split("/")).not.toContain("..");
      expect(sha(readFileSync(resolve(process.cwd(), "..", p.path))), p.path).toBe(p.sha256); }
    expect(native.participants).toHaveLength(3);
    expect(native.participants.flatMap(p => Object.values(p)).filter(v => typeof v === "string" && v.startsWith("{"))).toHaveLength(36);
  });
  it.each([0, 1, 2])("verifies participant %i wording, full scope, exact preview/commit and withdrawal history", async index => {
    const p = native.participants[index], ref = reference(p), actor = p.actor_user_id;
    const wording = await review.parseReviewWording(p.declaration_wording); expect(wording.actor_user_id).toBe(actor);
    const b = review.parseReviewPreflight(p.preflight, actor, ref, documents(p));
    expect([0, 1, 60]).toContain(b.own_review_record_count); expect(b.selected_candidates).toBe(60);
    expect(await review.parseReviewInspection(p.initial, actor, ref)).toBeNull();
    const head = await review.parseReviewInspection(p.attested_inspection, actor, ref);
    expect(head!.basis).toEqual(b);
    for (const action of ["attest", "withdraw"] as const) {
      const expected = { controls: controls(p, action), action, basis: b, predecessor: action === "attest" ? null : head };
      const prefix = action === "attest" ? "" : "withdrawal_";
      const r = recoveryFor(p, action);
      expect((await review.parseReviewResult(p[(prefix + "preview") as "preview"], r, false, expected)).declaration).toBeNull();
      const saved = await review.parseReviewResult(p[(prefix + "committed") as "committed"], r, true, expected);
      expect(saved.declaration!.basis).toEqual(b); expect(saved.declaration!.action).toBe(action);
      const old = await review.parseReviewResult(p[(prefix + "recovered") as "recovered"], r, true);
      expect(old.replayed).toBe(true); expect(old.declaration).toEqual(saved.declaration);
    }
    expect((await review.parseReviewInspection(p.withdrawal_inspection, actor, ref))!.action).toBe("withdraw");
    expect((await review.parseReviewResult(p.recovered, recoveryFor(p), true)).declaration!.action).toBe("attest");
  });
  it.each(["version", "actor_user_id", "scope", "declaration_version", "declaration_sha256", "declaration_text", "scientific_acceptance", "current_collective_signoff_verified",
    "external_digital_signature_verified", "source_permissions_verified", "canary_replay_verified", "context_bytes_checked", "run_authorization_granted", "training_execution", "extra"])("rejects changed wording contract %s", async name => {
    await expect(review.parseReviewWording(changed(own.declaration_wording, v => { v[name] = true; }))).rejects.toThrow();
  });
  it.each(["extra", "version", "actor", "ref", "flag", "scope", "file", "selection", "log", "candidates", "records", "own_count", "own_none", "conclusion", "recommendation", "canary", "implementation"])("refuses altered preflight %s", name => {
    const raw = changed(own.preflight, v => {
      if (name === "extra") v.private_source = "PRIVATE_CANARY";
      if (name === "version") v.version = review.REVIEW_VERSION;
      if (name === "actor") v.actor_user_id = "00000000-0000-4000-8000-999999999999";
      if (name === "ref") v.participant_sha256 = "f".repeat(64);
      if (name === "flag") v.documentary_binding_checked = false;
      if (name === "scope") v.scope = "approved";
      if (name === "file") v.input_pins.reviews_file_sha256 = "f".repeat(64);
      if (name === "selection") v.selection_sha256 = "f".repeat(64);
      if (name === "log") v.review_log_sha256 = "f".repeat(64);
      if (name === "candidates") v.selected_candidates = 59;
      if (name === "records") v.review_record_count = 2001;
      if (name === "own_count") v.own_review_record_count = 62;
      if (name === "own_none") { v.own_review_record_count = 0; v.conclusion_author_is_current_account = false; }
      if (name === "conclusion") v.conclusion_author_is_current_account = 1;
      if (name === "recommendation") v.recorded_recommendation = "approved";
      if (name === "canary") v.canary_replay_verified = true;
      if (name === "implementation") v.implementation_sha256 = "not-a-pin";
    });
    expect(() => review.parseReviewPreflight(raw, own.actor_user_id, reference(), documents())).toThrow();
  });
  it.each(["outer", "dry", "authority", "recorded", "key", "actor", "reason", "contract", "intent", "record", "basis", "date", "ref", "cycle", "extra"])("rejects altered committed result %s", name => {
    const raw = changed(own.committed, v => { const r = v.result;
      if (name === "outer") v.committed = false;
      if (name === "dry") r.dry_run = true;
      if (name === "authority") r.scientific_pilot_accepted = true;
      if (name === "recorded") r.declaration_recorded = false;
      if (name === "key") r.intent.request_key = "other";
      if (name === "actor") r.intent.actor_user_id = "00000000-0000-4000-8000-999999999999";
      if (name === "reason") r.intent.reason_code = "UPPER";
      if (name === "contract") r.intent.declaration_sha256 = "f".repeat(64);
      if (name === "intent") r.intent_sha256 = "f".repeat(64);
      if (name === "record") r.declaration.record_sha256 = "f".repeat(64);
      if (name === "basis") r.declaration.basis.own_review_record_count = 1;
      if (name === "date") r.declaration.created_at = "2026-02-30T00:00:00Z";
      if (name === "ref") r.declaration.participant_sha256 = "f".repeat(64);
      if (name === "cycle") r.declaration.supersedes_id = r.declaration.id;
      if (name === "extra") r.declaration.signature = "PRIVATE_CANARY";
    }); return expect(review.parseReviewResult(raw, recoveryFor(), true)).rejects.toThrow();
  });
  it("pins the displayed basis, action and predecessor to a preview rather than trusting only a valid hash", async () => {
    const b = review.parseReviewPreflight(own.preflight, own.actor_user_id, reference(), documents());
    const expected = { controls: controls(), action: "attest" as const, basis: b, predecessor: null };
    for (const altered of [{ ...expected, basis: { ...b, own_review_record_count: 1 } }, { ...expected, action: "withdraw" as const }, { ...expected, controls: { ...controls(), reason_code: "other" } }]) {
      await expect(review.parseReviewResult(own.preview, recoveryFor(), false, altered)).rejects.toThrow();
    }
    const head = await review.parseReviewInspection(own.attested_inspection, own.actor_user_id, reference());
    await expect(review.parseReviewResult(own.withdrawal_preview, recoveryFor(own, "withdraw"), false, { controls: controls(own, "withdraw"), action: "withdraw", basis: b, predecessor: { ...head!, participation_sha256: "f".repeat(64) } })).rejects.toThrow();
    expect(digest(b)).toBe(JSON.parse(own.preview).result.intent.basis_sha256);
  });
  it("rejects foreign inspection, extra metadata, noncanonical and duplicate-key responses", async () => {
    for (const raw of [own.declaration_wording + " ", "\ufeff" + own.declaration_wording, own.declaration_wording.replace("{", '{"version":"duplicate",')]) await expect(review.parseReviewWording(raw)).rejects.toThrow();
    await expect(review.parseReviewInspection(own.initial, native.participants.find(p => p.actor_user_id !== own.actor_user_id)!.actor_user_id, reference())).rejects.toThrow();
    await expect(review.parseReviewInspection(changed(own.initial, v => { v.historical_record_only = false; }), own.actor_user_id, reference())).rejects.toThrow();
    expect(() => review.parseReviewPreflight(canonical({ ...JSON.parse(own.preflight), signed: true }), own.actor_user_id, reference(), documents())).toThrow();
  });
});
