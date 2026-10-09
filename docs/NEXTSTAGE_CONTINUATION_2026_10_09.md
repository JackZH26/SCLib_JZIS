# Next-stage continuation: 9 October 2026

This checkpoint continues the task handoff without replacing earlier receipts.
It records completed engineering and acquisition work; scientific decisions,
permissions and execution gates remain separate.

## Completed local API regression

[Validation v2](data/nextstage-20261009/material-timing-validation-v2.json)
updates the earlier v1 `full_local_api=pending` observation. The original v1
record is preserved. An independent read of all eight retained JUnit reports
matches the completed coordinator result: **8,500 passed, 9 skipped, zero
failures/errors, 8,509 cases and 268 modules** at
`1b54e0e41530e154bce19b32f1bfaffb9c875263`. Every runner exit is zero and every
assigned module has reported cases. The original result, plan and batch byte
hashes are retained in the new receipt.

This was the owned native PostgreSQL/Redis regression, lasting 3,706.606 seconds.
The independently invoked capacity suite is not added to its denominator.
The skips remain skips. The result establishes neither exact-head Linux image
parity, production performance nor scientific acceptance.

## Release state at the first continuation refresh

The read-only refresh at 09:31 UTC (17:31 Singapore time) observed:

- Main remained `7efe1866d610ad227fef9be9f59000173c09d248`.
- Main Test [37897281585](https://github.com/JackZH26/SCLib_JZIS/actions/runs/37897281585)
  and Release images [37910387089](https://github.com/JackZH26/SCLib_JZIS/actions/runs/37910387089)
  completed successfully. The retained Docker API result for that main revision
  reports 8,492 passed, 9 skipped, zero failures/errors and 267 modules.
- Deployment [37910749759](https://github.com/JackZH26/SCLib_JZIS/actions/runs/37910749759)
  was in progress. Public `/version` still returned `67b790e`, dataset
  `v2026.09.03`, API `1`; deployment progress is not public acceptance.
- PRs #165, #166 and #167 retained their handoff heads. Their API jobs were
  still running; the other listed checks had completed. No review decision was
  recorded. Main had no enforced branch checks or rulesets, which does not
  waive the project's complete Test/Security/release requirements.
- Daily arXiv ingest remained `disabled_manually`.

PR #165 is an ancestor of #166. Normal merge commits preserve that relationship.
At 09:40 UTC (17:40 Singapore time), #165's complete Test and all listed checks
had succeeded. It was merged with merge commit
`f219a8e8afb92c4142bc2cc0646ad7872ace7a30`, with its head guarded at
`75adfa23079e40721c060c00ada8d1b8707e6c45`. The refreshed local main-to-#166
diff contains twelve remaining files; #166's original head was preserved.
With #165 merged, review #166's remaining diff. PR #167 is a separate Tc
selection optimization and overlaps the Materials route; retain request timing,
atomic scientific selection, source/revision fences and cancellation cleanup
when integrating it. Publication still needs actual release/deployment receipts
and a consistent public version fence, followed by a naturally observed
instrumented scan. No production cache clearing or cache-busting is needed.

## Material acquisition queue

[The 200-row queue](data/nextstage-20261009/material-source-acquisition-queue-v2.json)
now explicitly distinguishes the sixteen inspected original-source pilots from
the **184 rows without this task's original-source inspection**. Each row keeps
its material ID, formula, inherited order, historical source/Result pointers,
public response hash and remaining acquisition/review gates.

The underlying availability receipt was captured on 8 October at public release
`bcf2d85` between matching version fences. All 200 retained response bytes were
checked against that receipt before assembling the queue. This checkpoint makes
no new requests to those 200 endpoints and does not upgrade the historical
availability observation into a current scientific judgment. Catalogue family
tags remain declared metadata, with no scientific family adjudication.

The next proposed acquisition batch contains the first sixteen uninspected IDs
in the inherited order. This is a work-order proposal, not a new scientific
ranking or permission to change canonical facts. For each row, first acquire
the precise original source/version, then retain page/span support and resolve
sample/state/criterion before submitting an independent review. All two-reviewer,
resolver, intended-use and scientific decisions remain unassigned.

## Retrieval coverage and new retained originals

[The combined coverage inventory](data/nextstage-20261009/retrieval-acquisition-coverage-v2.json)
retains **72 question drafts, 46 English and 26 Chinese**. It contains 26
provisional connected components based only on identical normalized declared
source pointers. Translations and questions on the same paper stay together;
the nine shared Materials Cloud benchmarks form one component. These are not
26 verified independent experiments: Work/root, original experiment,
sample/state, citation and temporal links still require a full audit.

Original task tags remain intact. Ambiguous comparison/clarification and
comparison/mechanism tags are not silently reassigned to the proposed protocol
quotas. Every primary protocol task remains pending adjudication. The suggested
120-question target and 80/40 language balance remain an unapproved collection
plan; arithmetic gaps cannot be filled with paraphrases and called completion.
All splits are unassigned; no draft receives unseen-test eligibility, gold,
human scores or provider-run credit.

[Gap acquisition v2](data/nextstage-20261009/retrieval-gap-acquisition-v2.json)
adds private custody and page-text hashes for three fixed-version originals:

| Draft case | Retained original | Pages | Remaining gates |
|---|---|---:|---|
| Pr nickelate film | [arXiv:2006.13369v1](https://arxiv.org/abs/2006.13369v1) | 19 | Sample/criterion, complete corpus/Result binding, rights and independent review |
| CeCoIn5 / cited CeIn3 | [arXiv:cond-mat/0103168v1](https://arxiv.org/abs/cond-mat/0103168v1) | 16 | Direct/cited-root separation, complete corpus/Result binding, rights and independent review |
| LaAlO3/SrTiO3 interface | [arXiv:0807.0585v1](https://arxiv.org/abs/0807.0585v1) | 11 | Device/gate/sample association, complete corpus/Result binding, rights and independent review |

Current and fixed abstract metadata declare the expected related DOI in each
case. PDF bytes and all extracted page-text hashes are retained privately;
AI title-page visual checks establish navigation/identity observations only.
Extraction does not prove that all scientific associations were reviewed.
The metadata shows nonexclusive arXiv distribution for the nickelate and
interface preprints and the older assumed-1991-2003 licence for CeCoIn5. These
observed URIs are not task-specific retrieval, evaluation, redistribution or
training approval. Public files contain no PDFs, extracted passages or images.

Hg cuprate, organic and Lu-H-N article/notice full-text acquisition remains
unresolved in this checkpoint. The original twelve-question addendum and v2
review ZIP are preserved; this increment introduces neither new scientific
labels nor production source-lifecycle changes.

## Validation of this checkpoint

The existing public-acceptance and Materials-profile offline suites passed all
23 tests. The coordinator's own JUnit reader independently reconstructed each
batch's module membership and counts for both the native `1b54e0e` result and
the completed main `7efe186` Docker result. All 200 historical material response
byte/size pins matched; material IDs were unique and the inspected/uninspected
partition was 16/184. The combined draft IDs were unique, language totals were
46/26, and every draft remained unassigned and unscored. Public JSON was checked
for machine-local paths; raw files and extracted text remain private.

## Execution boundaries and next dependencies

Continue source acquisition and metadata/locator preparation while reviewers
remain unappointed. Canonical facts, gold judgments and training eligibility
require the actual authorized review/admission workflow. Local blank templates
and self-declared identities do not establish approval.

The native-compute chain #155 → #156 → #160 → #161 → #162 → #163 → #164 remains
separate. Existing retained budget is 6,780/7,200 core-seconds, leaving 420;
2 ranks × 600 seconds needs a 1,200-core-second reservation. New science jobs
therefore require a new explicit finite protocol/budget, authenticated resources,
runtime custody and exclusive worker handoff. No extra worker, soak acceptance,
SCF/DFPT/Tc campaign or model training was started for these acquisition files.
