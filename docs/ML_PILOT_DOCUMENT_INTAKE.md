# Installed private ML08 document intake

`ml08-document-intake/1.0.0` makes the existing scientific accounting kernel
available from the installed API package. It is a byte-level service, not an
HTTP upload endpoint, database registration, human-review signature or approval.
It creates no database rows, contacts no service and executes no ML training.

## One scientific kernel

`api/services/ml_pilot_accounting.py` owns `ml08-accounting/1.0.0` and loads
`ml08_pilot.schema.json` beside the installed module. The public
`docs/pilot/ML08_Pilot.schema.json` remains an exact mirror, checked in tests.
`scripts/validate_pilot_review.py` remains the compatible repository CLI; it
delegates rather than implementing a second scientific validator.

The original 60-candidate denominator, failures, unresolved reviews, independent
comparison declarations, per-field decisions and `go`/`narrow`/`stop` accounting
are preserved. A reported negative observation is not converted to Tc = 0.
Self-declared humans, source access and protocol approval are still declarations.

## Byte-level caller contract

Import `inspect_documents` from `services.ml_pilot_documents`. Supply keyword
arguments `selection_raw`, `reviews_raw`, `protocol_raw` and optional
`conclusion_raw`, each as exact bytes. Every supplied document requires its
matching `<name>_file_sha256`; `selection_sha256` and `review_log_sha256` are
separate, mandatory logical anchors. Conclusion bytes and their file pin must
be present or absent together. The declared protocol hash must match the
actual protocol bytes. Protocol text is opaque: it is hashed, never executed.

Each document is bounded to 8 MiB before parsing. JSON/JSONL also receives a
400,000-node and depth-64 preparse guard; the complete review log is bounded
before any record allocation and is limited to 2,000 revisions. Duplicate keys,
nonfinite values, invalid UTF-8, unsupported Unicode and non-object JSONL rows
fail closed. LF/CRLF delimit physical records; quoted U+2028/U+2029 remain text.
Only the review log may be empty. These are transport limits, not sample-size
or scientific quality thresholds. No over-limit input is silently truncated.

The result contains private accounting diagnostics, exact input pins and
explicitly false authority flags. `registration_recorded`, `context_bytes_checked`
and `canary_replay_verified` are false; `training_execution` is `disabled`.
`ready_for_final_human_signoff` refers to documentary completeness only, not an
authenticated signoff or scientific acceptance. Failures use static error codes,
without echoing private bytes, paths or input values. No source reference is opened.

## Installation proof

The API CI workflow builds the actual wheel, creates a separate standard-library
venv and installs only that wheel with `--no-index --no-deps`. It then runs
`scripts/probe_ml_pilot_install.py` with that environment's `python -I`.

The probe refuses repository module fallback, ORM/application imports, sockets
and subprocesses. Both modules and their schema must resolve inside the new
environment. Its 60 explicitly synthetic, unreviewed candidates test installation
and false-authority behavior only. Output is a text-free receipt containing
source/schema hashes and scope flags. It does not attest the full API runtime,
Docker image, Linux CI execution, real human work or scientific feasibility.

## Remaining admission work

Before this service can support authenticated scientific pilot acceptance:

1. The [registration service](ML_PILOT_REGISTRATION.md) now binds immutable
   selection/protocol hashes to authenticated accounts and server-recorded
   chronology. A supplied timestamp or hash alone cannot prove registration
   or establish independent human identity.
2. Retain and bind all review revisions, actual evidence/canary bytes and current
   source-access checks. Do not treat self-consistent uploads as permission.
   The [read-only review preflight](ML_PILOT_REVIEW_PREFLIGHT.md) now checks all
   uploaded revisions against that registration and recorded participation
   intervals; it does not retain source bytes or verify the declared canary.
3. Record independent, authenticated signoffs against exact reviewed bytes and
   the complete failure denominator. Keep `go`/`narrow`/`stop` within the reviewed
   feasibility scope; 60 cases do not by themselves establish model sufficiency.
4. Keep run budget, current rights, runtime isolation and execution admission as
   separate gates. This service never clears the existing ML09 run blockers.

Private real pilot documents belong in approved storage, not repository fixtures.
See the [pilot protocol](pilot/ML08_Pilot_Protocol.md),
[canary replay](ML_PILOT_CANARY.md) and [run governance](ML_USE_RUNS.md).
