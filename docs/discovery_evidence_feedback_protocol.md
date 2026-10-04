# Discovery archival evidence returns

Discovery now has a private workflow for returning an existing source-record
reading to an exact saved research action. A researcher records what the source
review found, a `continue`, `stop` or `redirect` decision, its reason, and remaining
unknowns. The researcher can then save a linked initial design proposal and
explicitly associate that saved child with the evidence return.

This implements the archival source-review part of methodology D6. It does not
submit a calculation, run an experiment, certify a stable host, or establish that
the reference and proposed design describe the same physical sample or state.
Native scientific result returns and execution receipts remain separate work.

## Local validation scope

The current package has 62 feedback contract, service, HTTP, transport and direct
SQL cases plus 24 schema lifecycle cases passing against owned native services.
The 48 offline schema contract checks pass. The full frontend suite passes 46
source checks and 2,721 unit tests, and the normal production build succeeds.
An actual migrated 0089 database verifies empty downgrade/upgrade preservation
of earlier SQL rows, functions and triggers. Populated history refuses mutation
and downgrade. Consecutive migrations explicitly acknowledge session unlock
before returning; concurrent operations still fail immediately.

The browser acceptance uses ordinary login and real local SQL/API writes on an
owned disposable database. Public Pt-doped and CaFFe DTO values are reconstructed
locally; their production governance and full raw records are not copied. The
acceptance saves one archival return, a new initial child, then reloads that
existing child and explicitly saves its follow-up association. Desktop 1280px
and mobile 320px layouts have no document-level horizontal overflow. The private
acceptance-only page and API adapter are absent from shipped frontend sources.
CI, normal deployment and production scientific acceptance remain distinct gates.

## Scientific scope

The first version accepts current retained-result designs with a `source_review`
next action, and existing retained-result evidence. Cross-material comparisons
are allowed. Exact material IDs and original retained-record indices select the
reference; chemical resemblance alone does not establish a physical association.

The evidence reading preserves source-supplied Tc type, definition and criterion;
measurement and method tokens; pressure and pressure context; Hc2 values, units,
conditions and direction; unresolved scientific-value proposals; raw knowledge
origin and `evidence_type`. Absent origin is not replaced by an inferred observed
or computed label. A `0 K` Hc2 condition does not by itself establish an Hc2(0)
method, WHH extrapolation or measurement procedure. WHH is shown only where the
retained source explicitly supplies it.

Invalid, oversized or unsupported scalar readings are withheld, without clipping
the original record or converting its value. A malformed scientific-value proposal
does not silently fall back to an older scalar. Existing parser and source policy
may withhold the entire evidence projection. Such holds remain distinct from a
scientific rejection.

All receipts explicitly retain:

| Authority | Value |
|---|---|
| Scientific acceptance | false |
| Canonical promotions | 0 |
| ML training approval | false |
| Public release | false |
| Calculation executed | false |
| Experiment executed | false |
| Physical association established | false |

User-authored findings and decisions are private research notes, not generated
scientific conclusions. The expected outcomes in the proposal and the actual
researcher decision are displayed separately.

## Interaction

1. Inspect a saved research design, then refresh evidence access.
2. Load the exact evidence material and retained-record index. Follow its link to
   the anchored Materials record or source paper when needed.
3. Enter findings, the actual decision and reason, and remaining unknowns.
4. Preview the exact immutable operation; explicitly save the evidence return.
5. Load return history and choose **Start proposal from return**. This copies an
   ordinary linked draft, requiring a freshly loaded baseline and a new design
   preview/save.
6. After its initial revision is actually saved, preview and explicitly save the
   follow-up association. A draft or synthetic child identity cannot be linked.

An already saved initial child can also be reloaded by design ID. Its current
eligible initial revision and exact parent are verified before a fresh link
preview; returning to the workflow does not require a duplicate child proposal.

The link records a proposal relationship. Its evidence and original action do
not become inherited properties of the new physical design.

## HTTP and persistence

`DISCOVERY_FEEDBACK_ENABLED` defaults to `false` independently of the design and
condition-batch interfaces. Paths are under `/v1/research/discovery-feedback`:

| Request | Purpose |
|---|---|
| `GET /capabilities` | Current private access and bounded contract |
| `GET /context` | Exact saved design/action plus evidence selector |
| `POST /operations/preview` | Rehearse either closed operation without retaining a write |
| `POST /operations/commit` | Commit only the exact reviewed preview |
| `GET /operations/outcome` | Recover the original request outcome by key and digest |
| `GET /designs/{design_id}/returns` | Bounded owner history and saved-child associations |

Operation version is `discovery-feedback-operation/1.0.0`; response contract is
`discovery-feedback/1.0.0`. Requests are bounded to 32 KiB, history windows and
follow-ups to 8, and projected source readings to 16 KiB. The closed request
contains no quantity edit, same-sample assertion or execution flag.
Single receipt reads are bounded to 512 KiB and history responses to 4 MiB, with
256 KiB receipt-proof parsing. These finite transport budgets allow legal
32 KiB requests whose notes expand through nested JSON escaping.

Migration `0089_discovery_feedback` adds only `discovery_evidence_returns_v1` and
`discovery_feedback_follow_ups_v1`. Both have append-only update/delete/truncate
guards. An exclusive, empty-only downgrade refuses retained feedback history.
The original `0087` design and `0088` batch contracts remain frozen.

SQL independently verifies owner, live curator grant/session, current design
head, exact action digest, current captured source, source projection, hashes and
child-parent identity. The HTTP layer additionally enforces existing parser
policy; conservative SQL governance is not claimed as parser-policy parity.

Receipt proofs exclude full source context and projected scientific values. The
history reader rechecks captured digests and current eligibility. After a source
withdrawal, parent revision, grant/session change or other relevant drift,
machine-readable current source values are withheld. Immutable historical notes,
selectors and receipt digests remain private history.

## Uncertain saves

Once a commit is dispatched, a lost response does not prove rollback. The UI keeps
minimal original request/digest recovery pins in its parent workspace, blocks
other design and batch mutations, and checks the original outcome with GET.
It does not automatically retry the write. Account changes clear visible private
source data and invalidate stale async responses.

## Acceptance boundary

Backend contract, native PostgreSQL and authenticated HTTP coverage exercise
preview rollback, exact commit, original-outcome recovery, owner isolation,
revocation, source holds, malformed values, current action pins and actual saved
child associations. Owned local fixtures and public DTO reconstruction prove
interface behavior, not production raw-record identity, paper fidelity,
independent human adjudication, execution completion or ML readiness.

Local migration rehearsals must preserve earlier rows, functions and triggers
through actual `0089 → 0088 → head` and earlier-head cycles. Deployment additionally
requires exact-head CI, signed release and verification against the deployed
schema and frontend. A local pass is not deployment confirmation.
