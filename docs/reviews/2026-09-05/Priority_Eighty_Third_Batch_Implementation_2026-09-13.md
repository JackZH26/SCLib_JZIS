# Batch83 — exact scan exceptions and value-free safety diagnostics

Base HEAD: `02949468802db042e56645e2932b08863a174074`, branch
`codex/sclib-research-v2`. Earlier uncommitted work is preserved. No commit,
push, PR, issue closure, deployment, production migration or feature activation.

## New terminal regression evidence

The batch82 full-run handle **3224 is terminal**, exit 1. Its first four
complete JUnit files independently verify **3,919 passes and 3 skips over
112 modules**, including **969 passes in 972.07 s** for batch 4. There are
zero failures/errors in those complete files, but that is **not full success**.
Batch 5's owned runner exited 4 while importing the pre-client safety guard:

```text
Unsafe test environment [sentinel-identity-or-lifetime-invalid]
```

It emitted no JUnit and did not reach business tests. Batches 6–8 did not start.
The coordinator correctly reports `incomplete`, `full_module_coverage=false`,
counted batches 1–4 and unreported batches 5–8. Its measured duration is
**2,795.314 s**. Owned-service cleanup was reported for the completed lifetimes
and the refused fifth lifetime. All 734 original input pins and HEAD matched
at final inspection. No observation timeout was treated as termination.

The unchanged [original plan](measurements/api-regression-batch82-2026-09-13/plan.json),
[original incomplete result](measurements/api-regression-batch82-2026-09-13/result.json)
and all four XML files are retained together. Result SHA-256:
`39e390d1b431d4b696474493bf7273692431ac5473fd6ec29ca8d71f4139558f`.
No synthetic fifth XML or passing full-run receipt was created.

## Startup diagnosis: not yet a root-cause claim

Inspection confirms that the parent runner validated the new environment before
starting pytest; the child then refused the grouped identity/lifetime condition
before application/client imports. The grouped error does not identify which
predicate failed. The cleaned capability cannot be reused or reconstructed as
though it were the original. No clock adjustment, stale service attachment or
expiry extension is justified by this evidence.

Before changing code, three separately created native startup probes each
passed the actual two PostgreSQL/Redis safety tests, in **1.46 s, 1.35 s and
1.50 s**, with owned cleanup after each. Their original XML files are retained
under [the follow-up measurements](measurements/security-policy-batch83-2026-09-13/startup-1.xml).
This did not reproduce the refusal and does not establish its cause or prove
the remaining ordinary API modules pass.

`scripts/test_safety.py` now distinguishes identity mismatch, not-yet-valid
capability, expired capability, invalid lifetime and excessive lifetime using
static reason codes only. It retains the same inclusive wall-clock interval,
the existing maximum accepted lifetime and all DSN/process/container guards.
The runner's one-hour capability and SQL expiry are unchanged. There is no
clock-skew grace, retry loop, identity bypass or credential-bearing diagnostic.
The change improves future diagnosis; it is **not claimed to fix the unexplained
batch5 refusal**.

New offline checks prove all seven invalid examples refuse before runtime
inspection with exact value-free messages, and that both original inclusive
interval boundaries remain accepted. Existing pre-client import/socket guards
remain part of verification.

## Exact historical secret-scan policy implemented

The [batch82 triage and actual temporary controls](Secret_Scan_Triage_Batch82_2026-09-13.md)
identified 63 historical false-positive findings with 36 unique immutable
commit/path/rule/line fingerprints. Only those 36 entries were added to the
existing five exceptions. The security test checks the complete exact set and
rejects duplicate entries. There is no path-wide, rule-wide or UUID-prefix ignore.

Using the actual updated repository policy, Gitleaks 8.30.1 rescanned the exact
61-commit range and returned **exit 0, zero findings**. Its
[unchanged native report](measurements/security-policy-batch83-2026-09-13/history.redacted.json)
is retained separately from the original nonzero report. This covers that
historical range only. The eight uncommitted native fixtures still have no
commit fingerprints; they must be scanned after separately authorized commit
creation, not pre-ignored using mutable file paths or a guessed future SHA.

## Verification and live work

- Targeted safety, security workflow, batch coordinator and runtime inventory:
  **71 tests and 39 subtests passed, 1.05 s**, after the final source edit.
- Ruff and `git diff --check` passed. The first lint attempt identified 41
  implicit string concatenations, including the original five entries; explicit
  parentheses corrected the format without changing any fingerprint value.
- Full offline scripts completed **2,290 tests and 91 subtests in 99.08 s**,
  exit 0. Handle **64422 is terminal**. The sanitized environment used the
  previously verified tokenizer cache; no new dependency download was needed.
- The **same 28 whole modules** originally assigned to batch5 completed under
  handle **12253**, exit 0: **1,032 passed, no failures/errors/skips, 498.64 s**,
  one existing warning and owned cleanup. No filter or module omission was used.
  The [actual plan, result and XML](measurements/api-batch5-replay-batch83-2026-09-14/result.json)
  were retained unchanged and independently checked against all 28 modules.
  Artifacts: `/private/tmp/sclib-batch83-batch5-replay-hzdu1m6y`.
  Its fresh 734-input inventory SHA-256 is
  `07598257259e531a123fc1a5a0f195312f5ac56a169cc868fbad92f6e6f48cb2`.
  The wrapper compared source/HEAD again after completion and retained actual
  JUnit counts without converting this replay into a complete regression.

On **2026-09-14 UTC**, a new independent **eight-batch / 223-module** regression
started under handle **29317**, using coordinator 1.1.0 and the current sources.
Its output root is `/private/tmp/sclib-batch83-full-api-6uHRlJ/run`.
It starts from batch1; no original or replay counts are substituted into it.
Keep API/script inputs and HEAD unchanged while this full regression is live.
The earlier fifth-batch startup refusal was not reproduced, and its external
root cause remains unestablished; finer diagnostics are not a claim of a cure.
The
batch82 734-input migration receipt and native captures remain unchanged
historical evidence after the safety-script edit; they are not relabeled as
current-source captures. Current-source evidence refresh and a complete ordinary
API regression remain required. Real source rights, the independent 60-event
pilot, scientific/ML evaluation and authorized remote delivery remain separate
unfinished requirements.
