# Next-stage execution record: 9 October 2026

This is the first execution checkpoint of the agreed four-week work plan.
It records deliverables and dependencies, not completion of all research gates.
The public application was checked at `67b790e`; review artifacts below have
their own pinned inputs and do not promote database records.

While preparing this checkpoint, main advanced to `7efe186` through the
Discovery readability PR #158. Its Security check passed and full Test was
still running when checked; the public API continued to report `67b790e`.
The new main commit is not substituted for the actually observed deployment.

| Workstream | Work completed in this checkpoint | Remaining acceptance |
|---|---|---|
| P0 deployment | Successful deployment verified; API and freshly fetched frontend footer agree | Recheck after each application deployment |
| P0 documentation | README updated for 103 hypotheses, 8 coordinate groups / 19 states, recovery and prepared batches; repeatable public acceptance tool added | Keep dated observations distinct from future main/deployed versions |
| P1 performance | Four request profiles, identity/gzip wire size, 20 measurements per profile, raw failures preserved | Controlled cache-miss capture and server-stage profiling; freeze SLOs before acceptance |
| P1 material review | 16 review rows with 55 source observations, 34 overlapping candidate references, exact Result/source/page/span pins and unresolved conditions | Two qualified independent reviews and resolver where needed; sample/state/criterion and source-rights decisions; append approved changes only afterward |
| P1 retrieval evaluation | 60 source-linked draft questions, 40 English / 20 Chinese, known retrospective cases marked, no split or gold labels invented | Expand coverage, adjudicate, acquire complete retained corpus/Work/root bindings, connected split/time audit, then captured baseline/new runs under RG04 |
| P1 compute transport | 22 isolated fault tests passed; existing HTTPS/mTLS staging evidence inspected | Actual node sleep/restart/cancellation/resource lifecycle and 24-hour observation |
| P2 native QE | Existing M4/PBE evidence and unmerged PR chain inspected; summary energy/error metrics independently recomputed | Integrate/review native contracts, verify installed runtime and exclusive handoff, fresh resources and new finite budget before denser-grid jobs |
| P2 ML | Scoped readiness audit covers the 16 recovery rows and 103 hypotheses; zero approved labels established | Task-specific science/rights/membership approval, whole-corpus leakage audit, real ML08 events and human reviews before training |

The owner confirmed on 9 October that no scientific-review roster has been
appointed and requested preparation of pending review materials. Reviewer,
resolver and scientific decision fields therefore remain unassigned. This does
not postpone the independent engineering and source-metadata work above.

## Review deliverables

- [Readable sixteen-material review queue and sixty questions](data/nextstage-20261009/review-queue-v1.md).
- [Machine-readable review/ML preparation package](data/nextstage-20261009/review-preparation-v1.json).
- [Current online coverage, integrity and latency](README_SNAPSHOT_2026_10_09.md).
- [Compute readiness and budget evidence](data/nextstage-20261009/compute-readiness-v1.json).

The review preparation inherits previously inspected public source metadata; this
checkpoint does not claim a new independent rereading of all original papers.
Original text is not embedded. Every observation retains source revision,
capture/content/span digests and page locators; unresolved associations remain
explicit. The remaining 184 entries of the earlier 200-material availability
queue have not acquired original-source review through this task.

The sixty questions are an **acquisition inventory**, not a validated RG04c
evaluation package or sixty independent experiments. Three questions on each
material share sources. Nine source-pair benchmarks share the Materials Cloud
source, and three experimental anchors need source/structure separation. The
known benchmark outcomes must not become unseen test credit. Cuprates,
nickelates, heavy fermions, organics, interfaces and withdrawn-source cases remain
coverage gaps. No retrieval/answer accuracy, citation support, provider cost or
live ANN replay is claimed. The [RG04 issue](https://github.com/JackZH26/SCLib_JZIS/issues/75)
and [120-question scientific protocol](SCIENTIFIC_EVALUATION_PROTOCOL.md) remain open.

Rebuild into new paths and compare exact bytes:

```bash
python3 scripts/build_nextstage_review_package.py --output /tmp/review-preparation-new.json --markdown-output /tmp/review-queue-new.md
cmp /tmp/review-preparation-new.json docs/data/nextstage-20261009/review-preparation-v1.json
cmp /tmp/review-queue-new.md docs/data/nextstage-20261009/review-queue-v1.md
```

Changed input identities, review authority or generator bytes require a new
review-preparation version. The generator cannot turn source licensing alone
into a task-approved training label or substitute its draft context for human
scientific-support judgments.

## Compute dependency update

Main's isolated coordinator remains dummy-only. Separately, the existing
[native M4 PR #155](https://github.com/JackZH26/SCLib_JZIS/pull/155) contains reported
actual QE 7.5 fixed-input Mg₄B₈ PBE/PAW SCF returns at 1, 2 and 4 MPI ranks.
Their respective wall times are 377.03, 199.67 and 246.00 seconds; this checkpoint
performed no new solver run or direct node probe. From the retained summary,
the energy window is `3.941143707682689e-12 Ha/atom` and maximum SCF error is
`7.957364286940383e-13 Ha/atom`, with one identical input-manifest identity.
This recomputation does not authenticate original output custody or establish
k-mesh convergence, physical stability, phonons, Tc or optimal parallelism.

The recorded campaign reserves **6,780 of 7,200 core-seconds**, leaving **420**.
A new 2-rank job reserving 600 seconds requires 1,200 core-seconds, so it does
not fit. Measured short wall times do not refund the conservative reservation.
The current next action is denser-grid initialization/resource inspection and
an explicitly versioned finite protocol/budget before admitting more SCF jobs.

Source-pinned PBEsol preparation/execution work forms the separate unmerged
chain #156 → #160 → #161 → #162 → #163 → #164, depending on #155. The
[initialization-worker PR #164](https://github.com/JackZH26/SCLib_JZIS/pull/164)
reports passing mocked/fixture transport tests; its own description establishes
no genuine PBEsol run or Mini installation. Those PRs are not represented as
deployed website capability. Installed release contents, a distinct node/runtime
grant, an exclusive worker handoff and actual resource admission remain gates.
No second worker, new scientific campaign or 24-hour acceptance was started
by this documentation/acceptance checkpoint.

## Validation and publication scope

The new offline contract suite passed **12 tests**; the isolated dummy transport
suite passed **22 tests**, for **34 passed**, with no skipped cases. Ruff and
dependency consistency checks passed. Tests cover changed deployment versions,
failed-request denominators, altered recovery values, exact byte/size pins,
bounded gzip decoding, rejected changed authority, shared-source question groups
and pending review decisions. They use owned temporary/synthetic stores and no
website API database. Real read-only acceptance checks are recorded separately.

The dedicated Public Acceptance Tools workflow repeats the twelve offline tests
and exact review-package rebuild on Python 3.11. It makes no live requests. The
existing full Test/Security/release process remains unchanged. Publication of
this checkpoint changes repository documentation and standalone tools, not
production schema, ingest scheduling, material facts, compute budgets or scores.

Next execution should resolve the scientific-review roster while acquiring
missing source/family cases, and profile a genuinely observed cache miss without
purging production caches. Native-compute progress follows its existing PR and
runtime custody chain; actual node soak, denser-grid calibration and ML training
must retain their own observed outcomes and unresolved gates.
