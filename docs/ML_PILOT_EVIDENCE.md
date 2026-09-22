# Private ML08 canary and context byte verification

This is a **read-only, default-off integrity check**, not scientific acceptance.
It combines actual original/context bytes with a fresh authenticated account
declaration snapshot. It stores no source document, context, declaration or
inspection record. No extraction, embedding, model fitting, source download,
archive extraction or scientific approval is performed.

## What it checks

`POST /v1/ml/pilots/review-attestations/evidence` requires all four switches:

- `ML_PILOT_REGISTRATION_ENABLED`
- `ML_PILOT_REVIEW_INTAKE_ENABLED`
- `ML_PILOT_ATTESTATIONS_ENABLED`
- `ML_PILOT_EVIDENCE_INTAKE_ENABLED`

They remain false by default. The authenticated session and exact own
`X-SCLib-Participant-Id` / `X-SCLib-Participant-Sha256` headers are admitted before
the body is read. The original participant/registrar grants must be active.
The route shares the existing two-operation private-route capacity limit within
each API process. This is not a cross-replica cluster quota; deployment capacity
and upstream rate limits require their own operational configuration.

The owned isolated child checks, in order:

1. The closed frame, bounds, independent raw/logical pins and four original
   selection/protocol/reviews/conclusion documents. It uses the same documentary
   kernel as preflight, including all selected events and review revisions.
2. The conclusion's canary hash against the actual supplied canary file. Version
   `ml08-canary/1.2.0` and current selected package-source inventory are required.
3. The exact distinct context hashes required across **all** review revisions,
   including superseded, pending and rejected results with a permitted-context
   assertion. Each supplied context is hashed incrementally; missing, unrelated,
   repeated, oversized, empty or altered files are rejected.
4. Full canary reconstruction from originals and observed context inventory,
   byte-for-byte equality with the uploaded canary, unchanged selected source
   inventory, and no trailing body bytes. Supplied summaries/proofs are never
   used instead of this reconstruction.

After the worker ends, the parent rechecks its bounded output, frame hash and
selected implementation. A **new repeatable-read, read-only SQL transaction**
rechecks the live session, registrar and all reviewer grants, registered roles,
participation histories/acceptance and declared chronology. It computes the
[joint declaration snapshot](ML_PILOT_ATTESTATIONS.md) in that same transaction.
A withdrawal or grant change during byte processing can therefore reject the
response. Valid byte replay does not override missing/stale/withdrawn declarations.

## Bounded binary wire contract

Content type is exactly `application/vnd.sclib.ml08-evidence-v1`. Content encoding
must be absent or `identity`. Multipart, compressed content and JSON envelopes
are not accepted. The browser constructs a Blob from original File objects; it
does not base64-encode context or concatenate the complete body in JavaScript.

The frame is UTF-8/ASCII magic `SCLIB-ML08-EVIDENCE-1` followed by LF, exactly
eight lowercase hexadecimal digits giving metadata byte length, LF, canonical
UTF-8 metadata JSON, then contiguous raw file bytes in metadata order. EOF is
required after the final file. Metadata has exactly:

```text
version: "ml08-evidence-upload/1.0.0"
parameters: { participant_id, participant_sha256, registration_sha256 }
selection_sha256: original logical selection hash
review_log_sha256: original canonical ordered complete-log hash
files: [{ key, sha256, size_bytes }, ...]
```

The first five keys are `selection`, `protocol`, `reviews`, `conclusion`, `canary`.
All remaining keys are `<sha256>.bin`, strictly sorted by their distinct lowercase
hashes. Filenames are transport keys, never filesystem destinations or source
URLs. Source references inside documents are never followed.

Limits: metadata 1 MiB; the four originals 8 MiB each; canary 32 MiB; contexts
8 MiB each, 64 MiB combined and at most 6,000 distinct hashes. The exact total
envelope bound is `len(MAGIC) + 9 + 129 * 1024 * 1024` bytes. The parent caps
stream chunks at 65,536, sends at most 64 KiB per write with backpressure and
never accumulates the complete body. The child retains bounded original
documents/canary for reconstruction, but only a running hash for context bytes.
It has 45 s wall time, 30 s CPU, disabled core/file writes, and a 512 MiB address
space limit on Linux. The route has a 60 s deadline; browser requests have 65 s.
Cancellation, timeout, rejected framing and output overflow reap the owned child.

The response contains only opaque hashes, counts, boundaries and the nested
account snapshot. It is `private, no-store`, at most 128 KiB, with no context,
review prose, other participant identifiers or scientific values. Invalid input
is 400; stale binding/state 409; active access failure 401/403; disabled feature
404; transport limits 413; unsupported content 415; capacity/timeout 503. There
is no commit attempt and no unknown-commit recovery state for this read-only route.

## English workbench

After **Check original review documents**, supply **Exact canary bundle** and
**Exact context files**, then choose **Verify canary and context bytes**.
The canary must already match the conclusion. The browser does not rewrite or
reseal any document. Its context filename/count/size checks are preliminary;
the server checks every actual byte and required ledger reference independently.

The byte proof and joint account snapshot appear separately from declaration
consent. No checkbox is selected, no declaration is previewed/committed, and no
background request is sent. Input/auth changes, writes, or failed rechecks remove
old proofs and consent/previews. Files and proof live only in page memory, not
browser storage. Reloading requires explicit re-upload. A zero-context successful
replay says only that the ledger required no contexts, not that papers were read.

After successful replay, **Show verified field report** opens a
[hash-bound local summary](ML_PILOT_QUALITY_REPORT.md) of all eleven pilot fields,
seven availability states, recovery/effort and recorded human proposals. It
refreshes account access but sends no further source upload or declaration.
Conclusion prose and small-group labels may be private; they are escaped text,
not a redacted/public report. The full offline review report remains separate.

## Privacy and infrastructure precondition

The application does not persist uploaded bytes; this is **not** an unconditional
whole-infrastructure no-retention guarantee. Apply and independently validate
the matching Nginx server and [private-intake policy](PRIVATE_INGRESS.md) before
enabling intake: 130 MiB evidence-only request ceiling, request/response buffering
off, no proxy temp files, HTTP/1.1 upstream, deadlines and a dedicated rate limit.
The related two-/four-file JSON, ML reconstruction and scientific-import uploads
now have separately scoped exact limits. Other routes retain the 20 MiB ceiling.
These source changes and their disposable native rehearsal do not update an
existing production proxy or verify its additional ingress/retention layers.

Check any additional ingress/CDN/WAF/APM, tracing, body logging, crash reporting,
host swap/core-dump policies and operational retention rules. This source change
does not apply Nginx configuration or enable the feature. Never upload restricted
source bytes merely because a record says `access_status=permitted`; that field
is an assertion, not verified current access authority.

## Clean-wheel CI verification

The API CI job builds an actual wheel, installs it with `--no-index --no-deps`
into a new venv and now runs the evidence probe as well as the existing
accounting/registration/review probes. Its test-only driver uses the locked
repository test environment to construct synthetic inputs, then executes
`scripts/probe_ml_pilot_evidence_install.py` under the separate installed Python
with `-I -B`, a minimal environment and an owned empty working directory.
No real documents, `.env`, database, registration or remote source are used.

The driver requires that pip's installed `direct_url.json` identify the exact
wheel path and SHA-256, that the interpreter prefix match the specified venv,
and that only SCLib and the standard venv packaging tools be installed. It checks
the installed response against the repository kernel's actual replay, not just
a reported success bit. The installed probe independently rejects repository or
server imports, checks installed source/resource paths, blocks network access
and permits exactly one owned streaming child per successful case.

Three cases are required: zero context; both original and superseding contexts
across 63 review rows; and one full 8 MiB context transmitted in 997-byte pieces.
A fourth attempt changes an actual context byte without updating its hash and
must fail without a success JSON result. Input files are generated in memory;
the output contains observations, hashes and synthetic counts, not source prose.

After explicitly preparing an owned wheel and dependency-free venv, run from
the repository root:

```bash
api/.venv/bin/python -m scripts.tests.run_installed_evidence_probe \
  --python /absolute/owned-venv/bin/python \
  --wheel /absolute/owned-build/sclib_api-0.1.0-py3-none-any.whl \
  --output /absolute/private-output/new-installed-evidence.json
```

All paths must be absolute and the output must not already exist. The driver
installs nothing. It creates the report exclusively with mode 0600 after the
checks and temporary working-directory cleanup. CI retains it as
`installed-evidence-replay-attempt-N`; absent output fails artifact upload.
The report's wheel/probe/driver hashes and actual interpreter/distribution
identity describe that observation. Synthetic identifiers vary between runs;
this is not a frozen scientific input bundle or an authorization receipt.

Executing this on macOS proves native installed-package behavior only. The
independent [Linux test/final-image parity gates](RELEASE_RUNTIME_PARITY.md),
actual HTTP authentication tests and real independent scientific review remain
required. Merely adding the CI step does not prove it has run remotely.

## Scientific and compatibility boundaries

Only `context_bytes_checked` and `canary_replay_verified` become true at the
inspection's outer integrity scope. Inside the nested account-only snapshot,
those flags remain false because that component did not perform byte replay.
`source_permissions_verified`, `human_identity_verified`, reviewer independence,
event existence, external chronology, scientific acceptance, collective signoff,
public release, ML approval and run authorization remain false throughout.

Implementation hashes observe selected installed source bytes, not loaded-code
identity or runtime-image attestation. Old 1.1 canaries/reports/declarations remain
immutable; replay them using their pinned implementation. For 1.2, build a new
canary, independently retain its hash, prepare a new conclusion/report and obtain
fresh appropriate account declarations. Do not relabel or reseal old artifacts.
The schemas for selection, review and conclusion stay 1.0.0; database schema stays
0077. A genuine approved 60-event pilot, permitted sources, independent human
work, reasoned field actions and downstream scientific acceptance still remain.
