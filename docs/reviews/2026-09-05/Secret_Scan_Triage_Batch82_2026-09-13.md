# Batch82 delivery secret-scan triage — 2026-09-13

Status at initial triage: **findings triaged; scanner still nonzero; exception implementation pending**.
The subsequent [batch83 implementation](Priority_Eighty_Third_Batch_Implementation_2026-09-13.md)
added the 36 reviewed historical fingerprints and matching security tests, then
passed the actual historical-range scan. The original reports and temporary
controls below remain unchanged. Uncommitted fixture fingerprints and remote
Security execution remain pending; the initial source freeze ended only after
the API run was authoritatively terminal.
No credentials were uploaded, no ignore policy changed and no source or history
was rewritten. The live full API run retains its unchanged API/script inputs
and HEAD `02949468802db042e56645e2932b08863a174074`.

## Actual local scan

The installed **Gitleaks 8.30.1** ran locally with default rules, a minimal
environment, full output redaction, inline allow comments disabled and the
existing five exact historical fingerprints. No remote scanner was invoked.

| Scope | Observed result |
| --- | --- |
| Every modified or untracked, non-ignored file from `git ls-files -m -o --exclude-standard -z` | 128 regular files scanned individually; 38 findings in 8 files; zero scanner execution errors |
| All 61 commits in `d26fc098565492b78b416fb30b6b1ec7087b24c7..02949468802db042e56645e2932b08863a174074` | Exit 1, 63 findings, 36 distinct commit/path/rule/line fingerprints |

All findings use `generic-api-key`. A per-file finding exit was counted as a
finding, not a successful clean scan. The 128-file inventory predates this
triage document and the copied reports. It is not a scan of ignored local
configuration, every file on disk, upstream history before the stated base,
Linux images or production. Scanner silence is not proof of absence of secrets.

Original private reports remain in
`/private/tmp/sclib-batch82-secret-scan-8Ef1Sk`. The actual redacted finding
reports were copied unchanged to
[the evidence directory](measurements/secret-scan-batch82-2026-09-13/branch-commits.redacted.json).
The original clean per-file reports remain in that private directory; they
were not replaced with fabricated positive or negative results.

## Evidence-based classification

| Category | Historical findings | Working-file findings | Check performed |
| --- | ---: | ---: | --- |
| Synthetic `request_key` values | 58 | 38 | Read the captured JSON, including nested HTTP JSON strings; every request key in the affected files has the synthetic-prefix/UUID shape. For all 25 affected historical file/revision groups, read the generating test at the same commit and confirmed the synthetic UUID construction. Current capture generators were also inspected. |
| `api/services/research_access.py` provenance hashes | 4 | 0 | Each stored hash exactly equals SHA-256 of the source blob from that finding's same commit, rather than an access credential. |
| Ordinary issue acceptance prose | 1 | 0 | Read the exact historical JSON line describing duplicate JSON keys and empty/duplicate candidate IDs. The matcher spans ordinary wording, not a token. |

The reviewed findings are false positives for credential detection. This
classification is tied to these actual immutable history entries and captured
test files; it is not permission to ignore future `request_key` values, all
UUID-shaped strings, source manifests or the fixtures directory.

The relevant generators are `test_discovery_main_barrier.py`,
`test_ml_pilot_attestations.py`, `test_ml_pilot_participant_wire.py` with
`test_ml_pilot_registration.py`, and `test_source_task_operations_http.py`
with `test_source_tasks.py`. They generate synthetic request identifiers
separately from authentication. The recovery services still require the
authenticated actor and matching request binding. **Real** recovery identifiers
may remain private even though these disposable synthetic examples are not
credentials; do not generalize this triage to production data.

## Retained working-file finding reports

The original numeric report filenames are kept. The `File` property inside each
report identifies its scanned file. Every `Secret` is `REDACTED`.

| Report | Fixture basename | Findings |
| --- | --- | ---: |
| [file-55.json](measurements/secret-scan-batch82-2026-09-13/file-55.json) | `discovery-main-barrier-native.batch75.wire.json` | 1 |
| [file-56.json](measurements/secret-scan-batch82-2026-09-13/file-56.json) | `discovery-main-barrier-native.batch82.wire.json` | 1 |
| [file-57.json](measurements/secret-scan-batch82-2026-09-13/file-57.json) | `ml-pilot-attestations-native.batch74.wire.json` | 6 |
| [file-58.json](measurements/secret-scan-batch82-2026-09-13/file-58.json) | `ml-pilot-attestations-native.batch75.wire.json` | 6 |
| [file-59.json](measurements/secret-scan-batch82-2026-09-13/file-59.json) | `ml-pilot-attestations-native.batch82.wire.json` | 6 |
| [file-62.json](measurements/secret-scan-batch82-2026-09-13/file-62.json) | `ml-pilot-participant-native.batch74.wire.json` | 6 |
| [file-63.json](measurements/secret-scan-batch82-2026-09-13/file-63.json) | `ml-pilot-participant-native.batch75.wire.json` | 6 |
| [file-64.json](measurements/secret-scan-batch82-2026-09-13/file-64.json) | `ml-pilot-participant-native.batch82.wire.json` | 6 |

Historical report SHA-256:
`bfe56c59a396d107a2cfd27a23c8ca0f40dcc5cda82d8e77da697d0d2753ab56`.

## Next bounded implementation

### Actual temporary-policy probe completed during the source freeze

An external private directory,
`/private/tmp/sclib-batch82-exact-ignore-tF6FbY`, contains a proposed 41-entry
policy: the original five entries plus only the 36 reviewed historical
fingerprints. Gitleaks received it through explicit `--gitleaks-ignore-path`;
the repository's active `.gitleaksignore` and security tests remain untouched.

| Actual invocation | Exit | Independently inspected report |
| --- | ---: | --- |
| Same exact 61-commit range, proposed exact policy | 0 | [Zero findings](measurements/secret-scan-batch82-2026-09-13/exact-report.json) |
| Same range, only the prose exception's commit SHA replaced by an unrelated all-zero SHA | 1 | [Exactly the original prose fingerprint returned](measurements/secret-scan-batch82-2026-09-13/wrong-commit-report.json) |
| Same `discovery-main-barrier-native.batch72.wire.json` path scanned as a mutable file, proposed exact policy | 1 | [Its request-key finding remained detectable](measurements/secret-scan-batch82-2026-09-13/mutable-file-report.json) |

These actual negative controls establish that the proposed entries are not
path-wide exceptions and require their historical commit identity. They do not
prove detection of every possible future secret. In particular, this temporary
clean historical scan does **not** clear the unchanged repository policy, the
eight uncommitted fixture files, or remote CI.

The [temporary candidate](measurements/secret-scan-batch82-2026-09-13/temporary-exact.gitleaksignore)
and [wrong-commit control](measurements/secret-scan-batch82-2026-09-13/temporary-wrong-commit.gitleaksignore)
were copied unchanged beside their actual redacted reports. They are data for
review, not active policy. Candidate SHA-256:
`516b23515d87feba2a5d52b2dcc9156d6d6537d60d7a644263ff851df0492831`.
The source-pinned API run is still live; no commit or fixture rewrite was needed.

### Remaining repository implementation

1. Let the currently running source-pinned API regression terminate before
   editing the security contract tests. Do not stop or invalidate it for this
   independent finding.
2. Add only the 36 reviewed immutable historical fingerprints to the existing
   exact-fingerprint policy, with matching tests and rationale. Preserve the
   original five exceptions. No path-wide, rule-wide, prefix or entropy bypass.
3. Rerun the actual scanner against the same commit range and validate that
   the approved exact exceptions, not a disabled rule, account for the change.
   Keep this nonzero original report as evidence.
4. The eight uncommitted fixture files have no commit fingerprints yet. After
   separately authorized commit creation, rescan the actual resulting revision
   and review its exact fingerprints. Do not guess a future commit SHA, rewrite
   byte-pinned fixtures or use mutable path/line-only ignores to suppress them.
5. Recheck any source-pinned evidence affected by the security-test edit and
   report its real scope. Exact-revision remote Test/Security execution remains
   required after separately authorized publication.

The existing `test_gitleaks_exceptions_are_exact_fingerprints` asserts the exact
five-entry set, so editing only `.gitleaksignore` would knowingly break the
offline suite. Both the policy and its test require one coherent follow-up
after the API/script source freeze. No issue is closed by this triage.
