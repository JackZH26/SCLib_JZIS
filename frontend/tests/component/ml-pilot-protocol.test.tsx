import { webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as pilot from "@/lib/ml-pilot-participation";
import { canonical, changed, digest, http, inputFor, recoveryFor, sealRecord, sha, wire } from "../helpers/ml-pilot-wire";

const actor = pilot.parsePilotAccess(http.access), owner = pilot.parsePilotAccess(http.owner_access);
const foreign = "00000000-0000-4000-8000-999999999999", otherHash = "f".repeat(64);
beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
describe("original native pilot participation protocol", () => {
  it("pins the capture, original replies and each current source without resealing old evidence", () => {
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-pilot-participant-native.delivery20260924r2.wire.json")))).toBe("4154b1331a61a7bec97c96f6dbd2ee2149eb71d5075da45fd9f9c459f3c65722");
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-pilot-participant-native.delivery20260924r1.wire.json")))).toBe("a64d2d71bd58bd658558d94160d8dbbe7b813d00b5490dc0f3dee9605f73081e");
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-pilot-participant-native.delivery20260923r4.wire.json")))).toBe("38729ff17b1fed4bf8604aab5d67e835d8ee388dbaabcc882ce7a21bac3e66d9");
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-pilot-participant-native.delivery20260922r10.wire.json")))).toBe("f6cec3fedec5c95256662d75abc60d60a5c3665a74342f78337fa8ca57e11fa5");
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-pilot-participant-native.delivery20260922r9.wire.json")))).toBe("fee017b8b60e62031cded06453c5faf0539ba77643d696a3924840ee23e33b6b");
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-pilot-participant-native.batch72.wire.json")))).toBe("51b334293c2e024d7b08648fdeaf0d4a53d0a1595444cd9f6af42239a9e41fb3");
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-pilot-participant-native.batch73.wire.json")))).toBe("e246bca6fc8654c852885137e96980706ae84b46ffc19eb4020e84d9dc8b12dd");
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-pilot-participant-native.batch74.wire.json")))).toBe("f9b85c230f5571eef3e798e547f6639fcb19ead3ddb87d7a8ced1f3f537ff10d");
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-pilot-participant-native.batch71.wire.json")))).toBe("5529a271abb2f0aee7990514cbe20bb8cd31fcd4bf017c06fa3f81415a17b593");
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-pilot-participant-native.batch70.wire.json")))).toBe("9ebb1a84f28cf713030b8a72fc5749b8a7d036237e8a01dd49216630635994ef");
    expect(http.capture_test_path).toBe("api/tests/test_ml_pilot_participant_wire.py");
    expect(http.fixture_notice).toBe("Actual owned SQL, authenticated HTTP and installed upload worker; synthetic accounts and declared events only, no real scientific approval or source permission.");
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-pilot-participant-native.batch75.wire.json")))).toBe("ce0cbb73250fc614964f5f028e20479903eb9f33a7dd1ffd1680ea43c409178a");
    expect(http.source_pins).toHaveLength(617);
    expect(new Set(http.source_pins.map(p => p.path)).size).toBe(http.source_pins.length);
    for (const p of http.source_pins) {
      expect(p.path).toMatch(/^(api|scripts)\/[A-Za-z0-9_./-]+\.(py|schema\.json)$/); expect(p.path.split("/")).not.toContain("..");
      expect(sha(readFileSync(resolve(process.cwd(), "..", p.path))), p.path).toBe(p.sha256);
    }
    expect(Object.values(http).filter(v => typeof v === "string" && v.startsWith("{"))).toHaveLength(21);
  });
  it("verifies all actual inspections including owner projection, grant revocation and historic acceptance", async () => {
    for (const name of ["initial", "pending", "decline_inspection", "accept_inspection", "revoked_inspection", "withdraw_inspection"]) {
      const page = await pilot.parsePilotInspection(wire(name), actor, http.query);
      expect(page.owner).toBe(false); expect(page.participants).toHaveLength(1);
      expect(page.ready_for_prospective_review).toBe(name === "accept_inspection");
    }
    for (const name of ["owner_initial", "owner_ready"]) {
      const page = await pilot.parsePilotInspection(wire(name), owner, http.query);
      expect(page.owner).toBe(true); expect(page.participants).toHaveLength(3); expect(page.ready_for_prospective_review).toBe(name === "owner_ready");
    }
    expect(pilot.parsePilotAccess(http.revoked_access)).toEqual(actor);
    const recovered = await pilot.parsePilotResult(http.accept_historical, recoveryFor("accept"), true);
    expect(recovered.replayed).toBe(true); expect(recovered.decision).toEqual(JSON.parse(http.accept_committed).result.decision);
  });
  it.each(["accept", "decline", "withdraw"] as const)("verifies original %s preview/commit/recovery and exact canonical intent", async name => {
    const ref = recoveryFor(name), input = inputFor(name);
    expect(digest(pilot.pilotIntent(input, actor.actor_user_id))).toBe(ref.intentSha256);
    expect((await pilot.parsePilotResult(wire(name + "_preview"), ref, false, input)).decision).toBeNull();
    const committed = await pilot.parsePilotResult(wire(name + "_committed"), ref, true, input);
    expect((await pilot.parsePilotResult(wire(name + "_outcome"), ref, true)).decision).toEqual(committed.decision);
  });
  it.each(["scientific_acceptance", "scientific_pilot_accepted", "human_identity_verified", "scientific_reviewer_independence_verified", "source_permissions_verified",
    "actual_event_existence_verified", "external_review_chronology_verified", "public_release", "ml_training_approved", "run_authorization_granted", "source_document_bytes_retained", "training_execution", "scope", "version", "actor_user_id", "extra"])("refuses altered admission %s", field => {
    expect(() => pilot.parsePilotAccess(changed(http.access, v => { v[field] = true; }))).toThrow();
  });
  it.each(["extra", "authority", "foreign", "registration", "binding", "roles", "role_order", "count", "accepted", "ready", "policy", "timestamp", "head_early", "self_predecessor", "head_actor", "intent", "record", "microsecond"])("rejects invalid inspection %s", async kind => {
    const raw = changed(http.accept_inspection, v => {
      const row = v.participants[0];
      if (kind === "extra") v.source_text = "PRIVATE_CANARY";
      if (kind === "authority") v.scientific_acceptance = true;
      if (kind === "foreign") row.binding.user_id = foreign;
      if (kind === "registration") v.registration.record_sha256 = otherHash;
      if (kind === "binding") row.binding.record_sha256 = otherHash;
      if (kind === "roles") row.binding.roles = ["administrator"];
      if (kind === "role_order") { row.binding.roles = ["secondary", "primary"]; row.binding.roles_sha256 = digest(row.binding.roles); sealRecord(row.binding, ["roles"]); }
      if (kind === "count") v.participant_count = 31;
      if (kind === "accepted") v.accepted_account_count = 0;
      if (kind === "ready") v.ready_for_prospective_review = false;
      if (kind === "policy") v.current_registration_document_policy = false;
      if (kind === "timestamp") v.registration.created_at = "2026-02-30T00:00:00Z";
      if (kind === "head_early") row.head.created_at = "2020-01-01T00:00:00Z";
      if (kind === "microsecond") { v.registration.created_at = "2026-01-01T00:00:00.000002Z"; row.binding.created_at = "2026-01-01T00:00:00.000001Z"; }
      if (kind === "self_predecessor") row.head.supersedes_id = row.head.id;
      if (kind === "head_actor") row.head.actor_user_id = foreign;
      if (kind === "intent") row.head.intent_sha256 = otherHash;
      if (kind === "record") row.head.reason_code = "tampered";
    });
    await expect(pilot.parsePilotInspection(raw, actor, http.query)).rejects.toThrow();
  });
  it("does not confuse owner records with self-only projection or grant legacy policy readiness", async () => {
    await expect(pilot.parsePilotInspection(http.owner_initial, actor, http.query)).rejects.toThrow();
    await expect(pilot.parsePilotInspection(http.initial, owner, http.query)).rejects.toThrow();
    const raw = changed(http.accept_inspection, v => { v.registration_document_check_version = "ml08-registration-documents/1.0.0"; v.current_registration_document_policy = false; v.ready_for_prospective_review = false; });
    expect((await pilot.parsePilotInspection(raw, actor, http.query)).ready_for_prospective_review).toBe(false);
  });
  it.each(["extra", "count", "order", "duplicate", "roster", "implementation", "intent", "record"])("rejects altered full owner roster %s", async name => {
    const raw = changed(http.owner_initial, v => {
      if (name === "extra") v.registration.licence = "approved";
      if (name === "count") v.participant_count++;
      if (name === "order") v.participants.reverse();
      if (name === "duplicate") v.participants[1] = v.participants[0];
      if (name === "roster") v.registration.roster[0].user_id = foreign;
      if (name === "implementation") v.registration.implementation.files["../../canary"] = otherHash;
      if (name === "intent") v.registration.intent_sha256 = otherHash;
      if (name === "record") v.registration.request_key = "changed";
    });
    await expect(pilot.parsePilotInspection(raw, owner, http.query)).rejects.toThrow();
  });
  it.each(["committed", "dry_run", "authority", "key", "actor", "intent", "decision", "extra"])("refuses altered result %s", async name => {
    const raw = changed(http.accept_committed, v => {
      if (name === "committed") v.committed = false;
      if (name === "dry_run") v.result.dry_run = true;
      if (name === "authority") v.result.scientific_pilot_accepted = true;
      if (name === "key") v.result.intent.request_key = "replacement";
      if (name === "actor") v.result.intent.actor_user_id = foreign;
      if (name === "intent") v.result.intent_sha256 = otherHash;
      if (name === "decision") v.result.decision = null;
      if (name === "extra") v.result.secret = "PRIVATE_CANARY";
    });
    await expect(pilot.parsePilotResult(raw, recoveryFor("accept"), true)).rejects.toThrow();
  });
  it("rejects duplicate keys, noncanonical bytes, control aliases, invalid reasons and invented withdrawal roots", async () => {
    for (const raw of [http.access + " ", "\ufeff" + http.access, http.access.replace('{', '{"version":"duplicate",'), canonical({ ...JSON.parse(http.access), actor_user_id: "../bad" })]) {
      expect(() => pilot.parsePilotAccess(raw)).toThrow();
    }
    for (const reason of ["", " upper", "1reason", "UPPER", "source text", "a".repeat(161)]) expect(pilot.pilotReason(reason)).toBe(false);
    expect(() => pilot.pilotIntent({ ...inputFor("decline"), decision: "withdraw" }, actor.actor_user_id)).toThrow();
    await expect(pilot.parsePilotResult(http.accept_committed, { ...recoveryFor("accept"), actorId: foreign }, true)).rejects.toThrow();
  });
});
