# Private ML08 canary construction and replay

Protocol: `ml08-canary/1.1.0`. This implements the artifact step after the
[ML08 review/accounting protocol](pilot/ML08_Pilot_Protocol.md), not approval of
that proposed protocol or evidence that real human reviews have occurred.

The earlier validator checks the declared canary reference/hash in a conclusion
but deliberately does not open it. `scripts/ml_pilot_canary.py` closes that
artifact gap: construct a private canary from the frozen selection and complete
review ledger, then rebuild it independently and bind the final conclusion to
its exact bytes. No source permission, scientific acceptance, human identity,
reviewer independence or model execution is authenticated by this command.

Version 1.1.0 uses the API-packaged `services.ml_pilot_accounting` kernel and
`services.ml_pilot_documents` byte parser. Its source inventory also pins those
two modules and the installed `ml08_pilot.schema.json` resource. The selection,
review and conclusion input schemas remain 1.0.0; their scientific accounting
rules are unchanged. JSONL is delimited by physical LF bytes, preserving literal
U+2028/U+2029 inside quoted source text. Input JSON now receives the shared
8 MiB / 400,000-node / depth-64 boundary, including the cumulative review log.

Old canaries and HTML reports remain immutable historical artifacts. Replay
them with their originally pinned implementation; current-code replay deliberately
rejects a changed code inventory. A new 1.1.0 canary needs fresh construction,
independently retained pins and a conclusion bound to its new bytes. Do not edit
an old artifact's version or reseal its outer hash to make it appear current.
The [installed ML08 intake contract](ML_PILOT_DOCUMENT_INTAKE.md) describes the
packaging boundary and the separate, still-unimplemented authentication gates.

## Inputs and independent anchors

Use the locked API Python environment and matching repository revision. All
supplied paths must be absolute, non-traversing physical paths without symlink
ancestors; on macOS use `/private/tmp`, not `/tmp`. Real private material belongs
in approved storage, not this repository.

| Input | Required binding | Meaning |
| --- | --- | --- |
| Selection JSON | Exact file SHA-256 **and** original logical `selection_sha256` | Predeclared cohort, strata and pseudonymous roster; no replacement of inaccessible events |
| Review JSONL | Exact file SHA-256 **and** canonical ordered `review_log_sha256` | All revisions, including superseded primary/secondary/arbitration rows |
| Approved protocol document | File hash matching selection's `protocol_sha256` | Document bytes, not authenticated approval |
| Evidence directory | Exact required `<context_sha256>.bin` leaves | Explicit operator-supplied bytes; no references are followed |
| Conclusion JSON, verify only | File hash, original selection/log pins and canary hash | Complete documentary proposal, not an authenticated signature |
| Canary JSON, verify only | Independently retained file hash | Must equal a fresh complete reconstruction |

Raw and logical hashes are different. Selection's logical hash excludes its own
hash field; the review-log hash covers a canonical ordered JSON array, not JSONL
bytes. Whitespace can preserve logical content while changing raw file pins.
No hash is automatically rewritten. Obtain anchors from the independently
retained approved record, not the same freely editable working files.

## Closed evidence directory

Across every review revision, context is required when its source record has a
nonempty context reference, hash and `access_status=permitted`. This is a
**recorded assertion**, not a current permission check. The operator must
separately hold authority to access the supplied files. Pending/rejected and
superseded reviews are included; they are not dropped to improve completeness.

Provide exactly one regular single-link `<sha256>.bin` file per required hash
in a dedicated directory, with no other files or subdirectories. Equal hashes
deduplicate byte checks, not scientific support. Context references may be reused
across revisions with different hashes; both original revisions/hashes survive.
Missing/restricted/not-accessible context stays explicit in the ledger and is
not opened. It cannot qualify as accepted data through invented evidence.

The command follows no source URL/path, performs no archive extraction, executes
no source file and makes no network/database request. Binary evidence is hashed,
not interpreted or embedded in the canary. Neither a matching hash nor a supplied
file proves that an assertion is supported by it or that its licence is valid.

## Build before preparing the conclusion

All original 60 candidates must have primary outcomes and complete required
comparisons/disagreement dispositions. Unresolved arbitration with pending or
rejected results is retained. An entirely inaccessible cohort can still yield
an honest `stop` conclusion; no accuracy threshold or positive result is needed.

```bash
api/.venv/bin/python scripts/ml_pilot_canary.py build \
  --selection /secure/pilot/selection.json \
  --selection-file-sha256 <retained-selection-file-hash> \
  --selection-sha256 <retained-selection-logical-hash> \
  --reviews /secure/pilot/reviews.jsonl \
  --reviews-file-sha256 <retained-jsonl-file-hash> \
  --review-log-sha256 <retained-canonical-ordered-log-hash> \
  --protocol /secure/pilot/approved-protocol.md \
  --protocol-sha256 <retained-protocol-file-hash> \
  --evidence-directory /secure/pilot/context-by-hash \
  --output /secure/pilot/outputs/canary.json
```

Paths and placeholders are illustrative. Create the approved output directory
beforehand. The tool creates a new owner-only `0600` file, never overwrites an
existing path and refuses output inside the evidence directory. Stdout contains
only a bounded receipt of opaque hashes/counts and non-authorizing flags, not
paths, reviewer names, event IDs, scientific values, review prose or raw context.

The canary preserves the complete selection, ordered review ledger, effective
per-candidate review/result associations, accounting, byte inventory and
raw/logical input pins. Superseded revisions retain their original values and
effort; duplicate result IDs do not become independent observations. Tc bounds,
uncertainty, unknown pressure and `not_detected` remain typed; a negative
observation never becomes Tc = 0. Context bytes themselves are not copied.

The nested accounting report is identified as the documentary validator's
output. Its warning about not opening evidence describes that component; the
enclosing canary's separate scope records that explicit local bytes are hashed.
Neither step proves content support, permissions or human scientific acceptance.

The canary excludes the conclusion to avoid circular hashes. A responsible
human can then prepare the conclusion against that canary hash, original
selection/log hashes, every field's keep/narrow/defer action and a reasoned
`go`, `narrow` or `stop`. Retain the conclusion's file hash independently.

## Verify the final documentary package

Use `verify` with the same selection/review/protocol/evidence arguments, omit
`--output`, and add:

```text
--bundle /secure/pilot/outputs/canary.json
--bundle-sha256 <independently-retained-canary-file-hash>
--conclusion /secure/pilot/conclusion.json
--conclusion-sha256 <independently-retained-conclusion-file-hash>
```

Verification writes nothing. It reconstructs the entire canary, reruns the
review/accounting invariants and binds the conclusion to the exact canary,
selection and log. Changing counts, dropping failures, forging code pins or
resealing only the outer hash cannot pass replay. Files, directory/leaf identities,
bytes, captured values and selected source files are rechecked before success.

Exit `0` means the offline operation completed, not that a pilot was accepted.
Exit `2` means invalid/incomplete input or an output condition needing attention.
Possibly completed filesystem publication reports `output_state_unknown` and
`output_written=null`, not rollback. Inspect the exact destination privately
before retrying; never automatically delete or replace an existing output.

## Bounds and remaining gates

Input selection/JSONL/protocol/conclusion files: 8 MiB each. Review revisions:
2,000. Evidence: 6,000 leaves, 8 MiB per leaf and 64 MiB combined. The reused
package codec/writer enforces 32 MiB / 400,000 nodes / depth 64. JSON has duplicate,
finite-number, Unicode and allocation checks. These are operational ceilings,
not scientific sampling criteria; excess input is refused, never truncated.

Empty input/evidence files, symlinks, hardlinks, FIFOs, directory leaves and
traversal are refused. An empty evidence directory is valid only when the
complete review ledger requires no context files, for example an all-failed
cohort. The
existing no-clobber writer preserves owned-inode cleanup and unknown-outcome
reporting. Code/Python observations pin selected sources, not loaded-code
identity, installed dependency parity or a complete execution-image attestation.

Actual selection/protocol approval, current source-access authority, real
independent human reviews, justified recommendations and authenticated final
acceptance remain separate. Private review prose and small-group accounting
may be sensitive: do not publicly redistribute the canary without review.
Never promote its hash to `scientific_pilot_accepted` merely because offline
replay passed. [Run-plan governance](ML_USE_RUNS.md), audited dataset lineage,
current rights, runtime admission and execution retain their own gates. Model
execution remains disabled.

The [private human-review report](ML_PILOT_REPORT.md) can now present this exact
canary and its conclusion as an inert, replayable English HTML document. It
retains all event failures and review revisions without embedding context files
or promoting documentary validity into scientific acceptance.
