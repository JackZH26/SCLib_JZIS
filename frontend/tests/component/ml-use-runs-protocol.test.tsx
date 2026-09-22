import { webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as runs from "@/lib/ml-use-runs";
import { canonical, changed, digest, http, inputFor, recoveryFor, sealRecord, sha, wire } from "../helpers/ml-run-wire";

const owner = runs.parseRunAccess(http.requester_access, "plan"), reviewer = runs.parseRunAccess(http.approver_access, "decision");
const foreign = "00000000-0000-4000-8000-999999999999", otherHash = "f".repeat(64);
const plan = JSON.parse(http.plan_committed).result.plan as runs.RunPlan;
beforeEach(() => { vi.stubGlobal("crypto", webcrypto); });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); });

describe("native run protocol — original SQL/HTTP bytes", () => {
  it("pins all 612 source inputs including evidence intake, historical bytes, and 28 original response strings", () => {
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-use-runs-native.delivery20260922r4.wire.json")))).toBe("d28714ce64f4de4bf59583fd6e75a074b6dec2b1f891b6083ad309ed7812b3e6");
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-use-runs-native.batch75.wire.json")))).toBe("139a5042e0aa1e6b71301159c03047a6dcda6d0ccc92e600f93b83b16fffa6c5");
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-use-runs-native.batch72.wire.json")))).toBe("4be1870e4e072254f65c1f304351b25bf164c4a6d3f9f3b9661fb9ab2972b221");
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-use-runs-native.batch73.wire.json")))).toBe("f0aff113f905cf23b81a2b42b436352391f0e71e7d3b449aec9e053f6e287f4f");
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-use-runs-native.batch74.wire.json")))).toBe("6baf207b484913ebd34c0adef9ed3bf1ee6a2051f642d0cb0a384f36817f2280");
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-use-runs-native.batch71.wire.json")))).toBe("d8759f5e1c15e484d53826c2df9baa8a33231d73e880ebe65443b7b3cc0f4be5");
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-use-runs-native.batch70.wire.json")))).toBe("ff58865a322a1e9a536298cb595177413673860452fe0cd23f6ce0c28cec61d9");
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-use-runs-native.batch69.wire.json")))).toBe("4d12cc266b5420f7630613501dcee172ba222c01f3ec22d858dd5a5de43b8923");
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-use-runs-native.batch68.wire.json")))).toBe("a25dfbf0052951446d9874c853c4d7dcf7dd090090219ff757a953f788a7d75b");
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-use-runs-native.batch67-final.wire.json")))).toBe("7f936957dfd468cb7d23ad93c04d759c798b89b6bb27218856107489327c478b");
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-use-runs-native.batch67.wire.json")))).toBe("c8cc16d02e1117ab6fb6c106fc2181b4b8f1009d9ff0a5b06a42e4adfc3e0b00");
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-use-runs-native.batch66.wire.json")))).toBe("b14098dab7f75674848656ced055b9ebbbaa214544ff2235776ec10fbc549d48");
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-use-runs-native.batch65.wire.json")))).toBe("66ae36119f0023616a3de987bc287fecf6e10058dbad53920e0f50b62d130002");
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-use-runs-native.wire.json")))).toBe("1cabdf1fc608c169a82b3b9942a6e672595c860a00b264b339f54e867dd9419f");
    expect(http.fixture_notice).toBe("Actual guarded native SQL and HTTP; synthetic identities and explicit intake compiler double; no real approval or execution.");
    expect(http.capture_test_path).toBe("api/tests/test_ml_use_runs_wire.py");
    expect(http.source_pins).toHaveLength(612); expect(new Set(http.source_pins.map(p => p.path)).size).toBe(612);
    expect(http.source_pins.some(p => p.path === "api/services/ml_pilot_review_admission.py")).toBe(true);
    expect(http.source_pins.some(p => p.path === "scripts/probe_ml_pilot_review_install.py")).toBe(true);
    expect(http.source_pins.some(p => p.path === "api/tests/test_ml_pilot_participant_wire.py")).toBe(true);
    expect(http.source_pins.some(p => p.path === "api/services/ml08_pilot.schema.json")).toBe(true);
    expect(http.source_pins.some(p => p.path === "scripts/migration_pilot_registration.py")).toBe(true);
    expect(http.source_pins.some(p => p.path === "scripts/probe_ml_pilot_registration_install.py")).toBe(true);
    expect(http.source_pins.some(p => p.path === "api/tests/test_ml_pilot_registration_reliability.py")).toBe(true);
    for (const pin of http.source_pins) {
      expect(pin.path).toMatch(/^(?:(api|scripts)\/[A-Za-z0-9_./-]+\.py|api\/services\/[A-Za-z0-9_-]+\.schema\.json)$/); expect(pin.path.split("/")).not.toContain("..");
      expect(sha(readFileSync(resolve(process.cwd(), "..", pin.path))), pin.path).toBe(pin.sha256);
    }
    expect(Object.values(http).filter(v => typeof v === "string" && v.startsWith("{"))).toHaveLength(28);
  });
  it("verifies original native evidence bytes, purge/no-op and missing-evidence inspection/readiness", async () => {
    const document = await runs.parseRunEvidence(http.evidence_read, http.evidence_query);
    expect(document.text).toBe(http.approve_input.evidence_text);
    expect(document.decision).toEqual(JSON.parse(http.approve_committed).result.decision);
    expect(runs.parseRunEvidencePurge(http.evidence_purge, http.evidence_query).replayed).toBe(false);
    expect(runs.parseRunEvidencePurge(http.evidence_purge_replay, http.evidence_query).replayed).toBe(true);
    const observed = await runs.parseRunInspection(http.evidence_missing_inspection, reviewer, http.plan_query);
    expect(observed.recorded_approval_status).toBe("evidence_unavailable"); expect(observed.head).toEqual(document.decision);
    const readiness = await runs.parseRunReadiness(http.readiness_evidence_missing, owner, http.plan_query, plan);
    expect(readiness.conditional_run_approval_current).toBe(false); expect(readiness.blockers).toContain("exact_plan_approval_evidence_unavailable");
  });
  it("verifies both admissions, original context, all plans/decisions/outcomes, inspections and readiness", async () => {
    expect(owner.actor_user_id).not.toBe(reviewer.actor_user_id);
    const context = await runs.parseRunContext(http.context, owner, http.submission_query);
    expect(context.runtime_json).toContain("1e-12"); expect(sha(context.runtime_json)).toBe(context.runtime_sha256);
    expect(JSON.parse(context.runtime_json).observed.numerical_policy.pivot_relative_tolerance).toBe(1e-12);
    for (const name of ["plan", "approve", "revoke", "deny"] as const) {
      const preview = await runs.parseRunResult(wire(name + "_preview"), recoveryFor(name), false, inputFor(name) as runs.RunInput);
      const saved = await runs.parseRunResult(wire(name + "_committed"), recoveryFor(name), true, inputFor(name) as runs.RunInput);
      const recovered = await runs.parseRunResult(wire(name + "_outcome"), recoveryFor(name), true);
      expect(preview.record).toBeNull(); expect(saved.record).toEqual(recovered.record); expect(recovered.replayed).toBe(true);
      const inspection = await runs.parseRunInspection(wire(name === "plan" ? "unreviewed" : name + "_inspection"), reviewer, http.plan_query);
      expect(name === "plan" ? inspection.plan : inspection.head).toEqual(saved.record);
      const readiness = await runs.parseRunReadiness(wire(name === "plan" ? "readiness_unreviewed" : "readiness_" + name), owner, http.plan_query, plan);
      expect(readiness.conditional_run_approval_current).toBe(name === "approve");
      expect(readiness.blockers).toContain("guarded_execution_consumer_unavailable");
      expect(readiness.source_coverage.source_permission_granted).toBe(false);
    }
  });
  it.each(["plan", "decision"] as const)("refuses unknown fields, roles and positive authority at %s admission", kind => {
    const raw = kind === "plan" ? http.requester_access : http.approver_access;
    for (const name of ["extra", "actor_user_id", "curator_grant_id", kind === "plan" ? "requester_grant_id" : "approver_grant_id", "version",
      "scientific_acceptance", "public_release", "ml_training_approved", "reviewer_authority_authenticated", "source_permission_granted",
      "run_authorization_granted", "data_access_granted", "conditional_run_approval_current", "execution_environment_attested", "budget_reserved",
      "scientific_pilot_accepted", "execution_consumer_available", "training_execution"]) {
      expect(() => runs.parseRunAccess(changed(raw, v => { v[name] = true; }), kind), name).toThrow();
    }
    expect(() => runs.parseRunAccess(raw, kind === "plan" ? "decision" : "plan")).toThrow();
  });
  it.each(["identity", "role", "curator", "submission", "inventory", "prepared", "budget", "scope", "profile", "expiry", "authority", "extra", "host_hash", "host_raw", "host_shape", "host_policy", "module"])("rejects mutated context: %s", async kind => {
    const raw = changed(http.context, v => {
      if (kind === "identity") v.actor_user_id = foreign;
      if (kind === "role") v.requester_grant_id = foreign;
      if (kind === "curator") v.curator_grant_id = foreign;
      if (kind === "submission") v.submission_sha256 = otherHash;
      if (kind === "inventory") v.inventory_sha256 = otherHash;
      if (kind === "prepared") v.prepared_sha256 = "bad";
      if (kind === "budget") v.budget_limits.cpu_seconds_max++;
      if (kind === "scope") v.budget_scope = "reserved";
      if (kind === "profile") v.runner_profile = "gpu";
      if (kind === "expiry") v.input_access_expires_at = "invalid";
      if (kind === "authority") v.run_authorization_granted = true;
      if (kind === "extra") v.source_text = "PRIVATE_CANARY";
      if (kind === "host_hash") v.runtime_sha256 = otherHash;
      if (kind === "host_raw") v.runtime_json += " ";
      if (["host_shape", "host_policy", "module"].includes(kind)) {
        const name = kind === "module" ? "implementation" : "runtime", doc = JSON.parse(v[name + "_json"]);
        if (kind === "host_shape") doc.observed.secret = "PRIVATE_CANARY";
        if (kind === "host_policy") doc.observed.numerical_policy.pivot_relative_tolerance = 1e-3;
        if (kind === "module") doc.selected_modules["../../source"] = otherHash;
        v[name + "_json"] = JSON.stringify(doc); v[name + "_sha256"] = sha(v[name + "_json"]);
      }
    });
    await expect(runs.parseRunContext(raw, owner, http.submission_query)).rejects.toThrow();
  });
  it.each(["duplicate", "float_alias", "exponent", "unsafe", "trailing", "bom", "whitespace"])("rejects noncanonical top-level wire: %s", async kind => {
    const raw = kind === "duplicate" ? http.context.replace('{', '{"version":"extra",')
      : kind === "float_alias" ? http.context.replace('"cpu_seconds_max":1800', '"cpu_seconds_max":1800.0')
        : kind === "exponent" ? http.context.replace('"cpu_seconds_max":1800', '"cpu_seconds_max":18e2')
          : kind === "unsafe" ? http.context.replace('"cpu_seconds_max":1800', '"cpu_seconds_max":9007199254740993')
            : kind === "trailing" ? http.context + "{}" : kind === "bom" ? "\uFEFF" + http.context : " " + http.context;
    expect(raw).not.toBe(http.context); await expect(runs.parseRunContext(raw, owner, http.submission_query)).rejects.toThrow();
  });
  it.each(["outer_commit", "inner_commit", "dry_run", "intent_hash", "record_hash", "intent", "unknown", "authority", "expired_null"])("rejects hostile committed receipt: %s", async kind => {
    const raw = changed(http.approve_committed, v => {
      if (kind === "outer_commit") v.committed = false;
      if (kind === "inner_commit") v.result.committed = true;
      if (kind === "dry_run") v.result.dry_run = true;
      if (kind === "intent_hash") v.result.intent_sha256 = otherHash;
      if (kind === "record_hash") v.result.decision.record_sha256 = otherHash;
      if (kind === "intent") v.result.intent.request_key += "foreign";
      if (kind === "unknown") v.result.raw_source = "PRIVATE_CANARY";
      if (kind === "authority") v.result.ml_training_approved = true;
      if (kind === "expired_null") { v.result.decision.expires_epoch = null; sealRecord(v.result.decision); }
    });
    await expect(runs.parseRunResult(raw, recoveryFor("approve"), true)).rejects.toThrow();
  });
  it("binds receipts to original account, kind, key, digest and exact input, even on replay", async () => {
    const ref = recoveryFor("plan");
    for (const change of [{ actorId: foreign }, { kind: "decision" as const }, { requestKey: "other" }, { intentSha256: otherHash }])
      await expect(runs.parseRunResult(http.plan_outcome, { ...ref, ...change }, true)).rejects.toThrow();
    await expect(runs.parseRunResult(http.plan_outcome, ref, true, { ...http.plan_input, memory_mib: http.plan_input.memory_mib + 128 })).rejects.toThrow();
  });
  it.each(["self", "ref", "parent", "head_status", "plan_hash", "expiry", "grant", "unknown"])("refuses inconsistent independent inspection: %s", async kind => {
    const raw = changed(http.approve_inspection, v => {
      if (kind === "self") v.actor_user_id = plan.actor_user_id;
      if (kind === "parent") { v.head.plan_sha256 = otherHash; sealRecord(v.head); }
      if (kind === "head_status") v.recorded_approval_status = "unreviewed";
      if (kind === "plan_hash") v.plan.memory_mib += 128;
      if (kind === "expiry") v.input_access_expires_at = "invalid";
      if (kind === "grant") v.approver_grant_id = foreign;
      if (kind === "unknown") v.plan.source_text = "PRIVATE_CANARY";
    });
    await expect(runs.parseRunInspection(raw, kind === "self" ? { ...reviewer, actor_user_id: plan.actor_user_id } : reviewer,
      kind === "ref" ? { ...http.plan_query, plan_sha256: otherHash } : http.plan_query)).rejects.toThrow();
  });
  it.each(["ready", "authority", "blockers", "status", "approval_flag", "approval_time", "counts", "complete", "validity", "combined", "blocked_count", "blocked_order", "blocked_status", "blocked_extra", "coverage_unknown", "epoch", "parent", "fingerprint", "self"])("refuses misleading readiness: %s", async kind => {
    const raw = changed(http.readiness_approve, v => {
      const c = v.source_coverage;
      if (kind === "ready") v.ready_for_execution = true;
      if (kind === "authority") v.run_authorization_granted = true;
      if (kind === "blockers") v.blockers.pop();
      if (kind === "status") v.approval_status = "unreviewed";
      if (kind === "approval_flag") v.conditional_run_approval_current = false;
      if (kind === "approval_time") v.observed_epoch = String(v.approval.expires_epoch);
      if (kind === "counts") c.status_counts.unreviewed++;
      if (kind === "complete") c.recorded_permissions_complete = true;
      if (kind === "validity") c.current_source_validity_passed = "yes";
      if (kind === "combined") { c.source_permission_granted = true; v.source_permission_granted = true; }
      if (kind === "blocked_count") c.first_blocked_resources.pop();
      if (kind === "blocked_order") c.first_blocked_resources.reverse();
      if (kind === "blocked_status") c.first_blocked_resources[0].status = "allow_recorded";
      if (kind === "blocked_extra") c.first_blocked_resources[0].source_text = "PRIVATE_CANARY";
      if (kind === "coverage_unknown") c.extra = true;
      if (kind === "epoch") c.observed_epoch = String(Number(v.observed_epoch) + 100);
      if (kind === "parent") c.submission_sha256 = otherHash;
      if (kind === "fingerprint") v.fingerprints_match.runtime = false;
      if (kind === "self") {
        v.approval.actor_user_id = owner.actor_user_id;
        const i = JSON.parse(http.approve_preview).result.intent; i.actor_user_id = owner.actor_user_id;
        v.approval.intent_sha256 = digest(i); sealRecord(v.approval);
      }
    });
    await expect(runs.parseRunReadiness(raw, owner, http.plan_query, plan)).rejects.toThrow();
  });
  it("can report full recorded rights with a source hold without granting combined permission", async () => {
    const raw = changed(http.readiness_unreviewed, v => {
      const c = v.source_coverage; c.status_counts = Object.fromEntries(runs.COVERAGE_STATUSES.map(s => [s, s === "allow_recorded" ? c.resource_count : 0]));
      c.recorded_permissions_complete = true; c.current_source_validity_passed = false; c.first_blocked_resources = [];
    });
    const r = await runs.parseRunReadiness(raw, owner, http.plan_query, plan);
    expect(r.source_coverage.recorded_permissions_complete).toBe(true); expect(r.source_coverage.source_permission_granted).toBe(false);
  });
  it("validates explicit budgets without coercion and preserves the approved intent", () => {
    expect(runs.validRunBudget({ cpu_seconds: 1, wall_seconds: 1800, memory_mib: 4096 })).toBe(true);
    for (const change of [{ cpu_seconds: 0 }, { wall_seconds: 0 }, { wall_seconds: 1801 }, { memory_mib: 127 }, { memory_mib: 4097 }, { cpu_seconds: 1.1 }, { memory_mib: "512" }])
      expect(runs.validRunBudget({ cpu_seconds: 1, wall_seconds: 1, memory_mib: 128, ...change } as runs.RunBudget)).toBe(false);
    expect(digest(runs.runIntent("plan", http.plan_input, owner.actor_user_id))).toBe(recoveryFor("plan").intentSha256);
    expect(canonical(JSON.parse(http.plan_preview))).toBe(http.plan_preview);
  });
  it("rejects calendar-normalized timestamps instead of displaying an impossible date", async () => {
    const raw = changed(http.context, v => { v.input_access_expires_at = "2026-02-30T00:00:00+00:00"; });
    await expect(runs.parseRunContext(raw, owner, http.submission_query)).rejects.toThrow();
  });
  it("rejects a displayed blocked-status subtotal larger than the full-inventory subtotal", async () => {
    const raw = changed(http.readiness_unreviewed, v => {
      v.source_coverage.status_counts.unreviewed = 1;
      v.source_coverage.status_counts.denied = v.source_coverage.resource_count - 1;
    });
    await expect(runs.parseRunReadiness(raw, owner, http.plan_query)).rejects.toThrow();
  });
  it("rejects a future approval mislabeled expired even when all outward flags and blockers agree", async () => {
    const raw = changed(http.readiness_approve, v => {
      v.approval_status = "expired"; v.conditional_run_approval_current = false; v.blockers.push("exact_plan_approval_expired");
    });
    await expect(runs.parseRunReadiness(raw, owner, http.plan_query)).rejects.toThrow();
  });
  it.each(["self_predecessor", "beyond_retention", "before_creation"])("rejects a hash-consistent but impossible decision: %s", async name => {
    const raw = changed(http.approve_inspection, v => {
      if (name === "self_predecessor") { v.head.supersedes_id = v.head.id; v.head.supersedes_sha256 = otherHash; }
      if (name === "beyond_retention") v.head.expires_epoch = Math.ceil(Date.parse(v.input_access_expires_at) / 1000) + 1;
      if (name === "before_creation") v.head.expires_epoch = Math.floor(Date.parse(v.head.created_at) / 1000);
      const input = Object.fromEntries(Object.keys(http.approve_input).map(k => [k, v.head[k]]));
      v.head.intent_sha256 = digest(runs.runIntent("decision", input as runs.RunDecisionInput, v.head.actor_user_id)); sealRecord(v.head);
    });
    await expect(runs.parseRunInspection(raw, reviewer, http.plan_query)).rejects.toThrow();
  });
  it("rejects a snapshot that predates the decision it claims to observe", async () => {
    const raw = changed(http.readiness_approve, v => {
      v.observed_epoch = String(Math.floor(Date.parse(v.approval.created_at) / 1000) - 1);
      v.source_coverage.observed_epoch = v.observed_epoch;
    });
    await expect(runs.parseRunReadiness(raw, owner, http.plan_query)).rejects.toThrow();
  });
  it.each(["expired", "approver_unavailable", "fingerprint_changed", "source_gate_satisfied"])("accepts a consistent %s snapshot without execution authority", async kind => {
    const raw = changed(http.readiness_approve, v => {
      if (kind === "expired") { v.observed_epoch = String(v.approval.expires_epoch); v.approval_status = "expired"; v.conditional_run_approval_current = false; v.blockers.push("exact_plan_approval_expired"); }
      if (kind === "approver_unavailable") { v.approval_status = "approver_unavailable"; v.conditional_run_approval_current = false; v.blockers.push("exact_plan_approval_approver_unavailable"); }
      if (kind === "fingerprint_changed") { v.fingerprints_match.runtime = false; v.blockers.push("runtime_fingerprint_changed"); }
      if (kind === "source_gate_satisfied") {
        const c = v.source_coverage; c.status_counts.unreviewed = 0; c.status_counts.allow_recorded = c.resource_count;
        c.recorded_permissions_complete = true; c.current_source_validity_passed = true; c.source_permission_granted = true;
        c.first_blocked_resources = []; v.source_permission_granted = true; v.blockers = v.blockers.filter((b: string) => b !== "current_source_permissions_or_validity_incomplete");
      }
    });
    const r = await runs.parseRunReadiness(raw, owner, http.plan_query);
    expect(r.blockers).toContain("guarded_execution_consumer_unavailable"); expect(r.blockers).toContain("independent_scientific_pilot_not_attested");
  });
});
