# Verified private ML08 field report

This English website view helps reviewers decide which database fields are
worth retaining, narrowing or deferring after a pilot. It presents recorded
evidence and effort; it does not calculate scientific accuracy, rank material
families, recommend a schema change or authorize training.

## Entry and trust boundary

On `/dashboard/research/ml-pilot-reviews`, inspect your participant binding,
choose the review action and check the four original documents. Then explicitly
verify the exact canary and all required context bytes using the
[default-off byte intake](ML_PILOT_EVIDENCE.md). Only a successfully parsed,
account-bound byte-replay response reveals **Show verified field report**.

That button refreshes account access using the existing declaration-wording
GET, then rereads the same local canary and conclusion. Their actual raw SHA-256
values must match the existing review basis and byte proof. It sends no further
source upload, coverage request, declaration, export or database mutation. It
does not refresh the cohort-wide SQL snapshot: the displayed snapshot time
remains the original byte-replay check's time. This is historical evidence, not
a live rights or collective-signoff monitor.

The local view accepts canary `ml08-canary/1.2.0`, accounting/conclusion 1.0.0,
at most 32 MiB of canary and 8 MiB of conclusion. Reads are cancellable and have
a 30-second operation limit. Duplicate keys, malformed UTF-8, nonfinite numbers,
invalid displayed counts, vocabulary or denominators fail closed. Raw files are
hashed before parsing; JS reserialization is not used as proof of exact Python
floating-point/scientific values. Original source URLs are not followed.

The server's complete reconstruction remains the verifier. The frontend checks
only the shape and consistency of the displayed projection; it does not build
a second ledger calculator or replace the canary compiler. No API, migration,
scientific schema, compiler version or new feature flag is introduced.

## Scientific interpretation of the display

| Display | Counting unit and interpretation |
| --- | --- |
| Selected cohort and outcomes | All 60 preregistered events, including failures and unresolved events. No substitution of successful events. |
| Distinct effective atomic result IDs | De-duplicated effective result IDs, not independent works or replications. A shared result can serve more than one event. |
| Event–result associations | Links between events and their effective results; not extra atomic results. |
| Review records and effort | All primary, secondary and arbitration revisions, including superseded assessments and failures. Not the number of materials. |
| Candidate field recovery | Events containing any reported result for that field / 60 selected events. Pending/rejected results are included. Not accuracy or complete recovery. |
| Atomic field availability | Seven statuses for each field, summing to the distinct atomic-result denominator. No merging of `not_applicable` into missing data. |
| Frozen-group recovery | The same event recovery within each preregistered family, source class or stratum, using that group's selected-event denominator. Not an independent sample or family ranking. |
| Errors and comparisons | Separate typed error occurrences and latest comparison-record counts. Overlap is possible; no accuracy/error-rate denominator is invented. |

The eleven fields are `source_revision`, `source_locator`, `raw_context`,
`work_identity`, `sample_state`, `structure_identity`, `tc_value`, `tc_criterion`,
`pressure`, `origin`, and `method`. These are the priority pilot fields, **not**
the whole cross-family material schema. The seven availability states are
`reported`, `not_reported`, `not_accessible`, `not_extracted`, `ambiguous`,
`conflicted`, and `not_applicable`.

With zero atomic results, the view explicitly reports an empty denominator;
it does not show 100% missingness or turn failed events into negative examples.
Unknown pressure is not ambient pressure. A not-detected transition has a tested
temperature window, not a manufactured Tc = 0. Reported identity counts do not
establish independent evidence or available crystal coordinates.

Effort displays recorded minutes **and** timed-record coverage. No timed records
means “Not recorded”; an actual zero measurement means “0 recorded min”. A
partial sum is not total human effort. Superseded revisions still contribute.
Numbers use `en-US`; a display-rounding marker `≈` preserves the distinction
between formatted and exact recorded sums. Field time is not inferred from
populated cells. Group-by-field timing and unallocated effort details remain in
the complete offline report, not a second browser recomputation.

The eleven keep/narrow/defer actions, their reasons, overall go/narrow/stop,
rationale and limitations are copied from the exact supplied conclusion. They
are human-recorded proposals, never generated, endorsed or applied by this view.
A recorded “go” and complete account coverage do not prove scientific signoff.

## Interaction and privacy

- No consent checkbox is selected. Showing the report clears any old consent,
  confirmation, preview and receipt, while retaining the bound historical byte
  and account snapshots.
- Input, context, action, reason, participant or account changes invalidate the
  report. Original-file/coverage/byte rechecks clear it before sending requests;
  writes and failed checks clear it too. An obsolete asynchronous local read
  cannot restore content after an account change or unmount.
- Successful opening focuses the report heading below the sticky header.
  Tables have labelled keyboard-scrollable regions. Frozen group selectors
  reset to a valid group when the dimension changes. Mobile tables scroll within
  their own region without widening the document.
- File bytes, report and private references live in page memory only; no browser
  storage, telemetry payload or automatic download is added. Account refresh is
  still a network request, so this is not an offline-only workflow.
- Original context-file bytes are not displayed. **Conclusion prose and small
  group labels can themselves contain sensitive source-derived text.** They are
  rendered as escaped text, not HTML or clickable source links. A collapsed
  section is not redaction. Existing source-intake infrastructure requirements
  still apply; no whole-infrastructure no-retention guarantee is made.

For typed result values, every event, every review revision, original missingness
reasons, full error details and group-by-field timing, build and independently
verify the [complete private HTML report](ML_PILOT_REPORT.md). This summary does
not regenerate, export or replace that artifact.

## Evidence and remaining acceptance

The native zero-result fixture tests the existing authenticated wire/binding and
honest empty-state display. A separately labelled pure-kernel synthetic fixture
exercises 60 events, 66 log revisions, 9 distinct results/10 associations, seven
availability states, failed events, unresolved arbitration and partial timing.
Its presentation adapter is not authenticated HTTP or new scientific evidence.

Actual ML08 acceptance still needs permitted real sources, prospective selection,
independent qualified reviewers, complete failure/effort accounting and reasoned
field decisions. Source permission, scientific acceptance, dataset promotion,
public release, training and production deployment remain separate gates.
