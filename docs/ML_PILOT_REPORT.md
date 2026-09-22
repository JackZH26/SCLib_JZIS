# Private ML08 human-review report

Protocol: `ml08-private-review-report/1.0.0`.

`scripts/ml_pilot_report.py` rebuilds and verifies a complete
[private canary](ML_PILOT_CANARY.md), including the independently pinned
conclusion, before producing one self-contained English HTML report. This is
an executable presentation of the recorded pilot, not another approval policy,
an authenticated signature, a reviewed dataset or a model-training credential.

The website's [verified field summary](ML_PILOT_QUALITY_REPORT.md) is a separate,
limited view of the same canary/conclusion after authenticated byte replay. It
does not replace this complete offline report, its typed results, full review
history, group-by-field timing or independent HTML verification.

## What the reviewer receives

- Every original selected candidate, in selection order, including inaccessible,
  irrecoverable and unresolved events. There is no ranking, substitution or
  automatic exclusion of failures.
- Separate event, atomic-result, association and reported work/sample/state/
  structure counts. Independent-work/replication counts remain unknown. Shared
  result IDs do not become extra atomic results; secondary reviews do not become
  additional material observations.
- All eleven priority fields and all seven availability statuses, with distinct
  atomic-result and candidate-event denominators. Candidate recovery means any
  reported result, including pending/rejected results, not extraction accuracy,
  complete recovery or independently adjudicated correctness.
- Recorded total/field effort and timing coverage across **all revisions**.
  Missing time displays as not recorded, not zero minutes. A partial recorded
  total is not an estimate of total human effort. Zero is displayed only when
  timing was actually recorded as zero.
- Frozen family, source-class and stratum groups. Each group's field recovery
  uses its own selected-event denominator; field timing includes all its review
  revisions. No formula-based reassignment, quota or comparative accuracy is
  inferred from these descriptive groups.
- Effective typed Tc/pressure values, criterion, observation, method and state
  interpretation. Inequalities, intervals, approximation and uncertainty survive;
  not-detected observations retain their tested temperature window, not Tc = 0.
  Unknown pressure does not become ambient. Observed/Computed/Inferred are
  displayed as recorded, never silently combined into a model target.
- Every primary, secondary and arbitration revision, with original reasons,
  missingness, source locators, identity references and error details. Superseded
  values remain review history, not the current result or additional support.
- The original human-declared go/narrow/stop and per-field keep/narrow/defer
  proposal, rationale and limitations. The program neither chooses nor approves
  that recommendation. Unresolved arbitration or an entirely failed cohort can
  remain in a valid documentary package.

Counts and current/effective review rules reuse the existing ML08 validator.
The additional group-by-field timing presentation comes from the same complete
ledger and frozen selection. No new scientific pass threshold is introduced.

## Build and verify

Use the locked API environment, exact canary implementation/Python revision and
independently retained input pins. Follow the canary guide's source-permission,
physical-path and closed-evidence-directory rules. On macOS, use physical paths
such as `/private/tmp`, not a symlink such as `/tmp`.

Start with the **same complete arguments as canary `verify`**, replacing the
script name and mode with `scripts/ml_pilot_report.py build`, and add a new HTML
destination. For clarity, the complete input contract is:

```bash
api/.venv/bin/python scripts/ml_pilot_report.py build \
  --selection /secure/pilot/selection.json \
  --selection-file-sha256 RETAINED_SELECTION_FILE_SHA256 \
  --selection-sha256 RETAINED_SELECTION_LOGICAL_SHA256 \
  --reviews /secure/pilot/reviews.jsonl \
  --reviews-file-sha256 RETAINED_JSONL_FILE_SHA256 \
  --review-log-sha256 RETAINED_ORDERED_LOG_SHA256 \
  --protocol /secure/pilot/approved-protocol.md \
  --protocol-sha256 RETAINED_PROTOCOL_FILE_SHA256 \
  --evidence-directory /secure/pilot/context-by-hash \
  --bundle /secure/pilot/outputs/canary.json \
  --bundle-sha256 RETAINED_CANARY_FILE_SHA256 \
  --conclusion /secure/pilot/conclusion.json \
  --conclusion-sha256 RETAINED_CONCLUSION_FILE_SHA256 \
  --output /secure/pilot/outputs/private-review.html
```

Replace illustrative paths/pins with authorized, independently retained values;
the tool does not create the parent directory or invent those pins. The HTML
includes the original raw/logical bindings and the renderer's source hash.
Its own file hash is returned on stdout (not embedded circularly in itself).

For exact replay, use the same inputs and `verify` instead of `build`, omit
`--output`, and add:

```text
--report /secure/pilot/outputs/private-review.html
--report-sha256 INDEPENDENTLY_RETAINED_HTML_FILE_SHA256
```

Verification writes nothing. It reconstructs the canary/conclusion, rerenders
the entire report and compares its exact bytes. Changing displayed counts or
deleting failures/history cannot be repaired by simply rehashing the HTML.
Changed renderer source also requires a new report. The source observation
is not a signed executable or complete loaded-runtime attestation.

The source package is replayed before and after rendering. Canary/conclusion
bytes and identities and the renderer source are rechecked. All original local
context leaves are still required; possession of the derived HTML alone cannot
recreate a source-verification claim. Ordinary users can read the HTML without
Python, but that reading is not independent byte replay or scientific approval.

## Privacy, inert content and filesystem behavior

The file has no JavaScript, remote fonts/assets, source hyperlinks, forms or
automatic fetching. All supplied strings are HTML-escaped. Only fixed internal
section anchors are clickable. A restrictive content-security policy and
no-referrer/no-index metadata supplement escaping; they are not a guarantee
against a compromised browser or unauthorized distribution.

**This is a private report, not a redacted/public report.** Original context file
bytes and protocol document bytes are not embedded, but supplied review prose,
pseudonyms, source/permission references and small-group counts are included.
Text pasted into a review field is still text in the report. Collapsed sections
are already in the HTML; collapsing is not redaction. Use only approved private
storage and viewers. Printing/sharing needs its own permission. Expand the
sections required for a printout; a printout alone is not a complete replayable
review ledger.

Output is bounded to 32 MiB; excess is rejected, never truncated. Existing
files/symlinks/FIFOs/directories are not overwritten. Output inside the closed
context directory is refused. A newly created file is owner-only `0600` and
its final bytes, inode, link count, mode and parent identity are checked.

Creation is **exclusive, not atomic publication**: another authorized process
could observe a partial file during writing. Consumers must wait for a successful
receipt and verify the independently retained full-file hash. Any error after
creation returns `output_state_unknown`, with `output_written=null`; a partial
file may remain for inspection. The command does not delete, overwrite or retry
that path. Inspect it privately before choosing a new destination.

Exit `0` means completed build/replay, not scientific approval. Exit `2` denotes
invalid/incomplete input or an uncertain output requiring attention. Stdout
contains only opaque hashes, byte counts and explicit non-authorizing flags;
private content and source paths are not printed in errors.

## Reproduction and remaining work

```bash
api/.venv/bin/ruff check scripts/ml_pilot_report.py scripts/tests/test_ml_pilot_report.py
api/.venv/bin/python -m pytest scripts/tests/test_ml_pilot_report.py \
  scripts/tests/test_ml_pilot_canary.py scripts/tests/test_pilot_review.py -q
```

The standalone browser harness is
`frontend/tests/e2e/ml-pilot-report.visual.cjs`. It requires the installed frontend
Playwright/Chromium dependencies, an owned **synthetic** hostile-text test report
and an existing owned screenshot directory. It tests desktop/mobile rendering,
all 60 event entries, field-table navigation, native disclosures, keyboard focus,
escaped markup, absence of external requests and absence of document overflow.
Use the `test_every_supplied_string_is_inert_text_not_markup_link_script_or_css`
fixture in an explicitly created temporary pytest directory, never real pilot
data, for this harness.

Actual protocol approval, 60 real preselected source events, human assessments,
current access permission and independently authenticated scientific review are
still required. No real records or human signatures were created for this
feature. The report is separate from website deployment, database migration,
source-rights decisions, execution admission and issue acceptance.
