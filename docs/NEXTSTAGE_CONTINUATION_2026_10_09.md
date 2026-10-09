# Next-stage continuation: 9 October 2026

This checkpoint continues the task handoff without replacing earlier receipts.
It records completed engineering and acquisition work; scientific decisions,
permissions and execution gates remain separate.

The later [source and compute preparation record](NEXTSTAGE_SOURCE_AND_COMPUTE_PREPARATION_2026_10_09.md)
adds the complete first-sixteen access denominator, source-navigation questions,
pending-review ZIP v6 and an organic-superconductor archive candidate. It also
records a fresh parse of four retained compute XML outputs and a finite
mesh-budget proposal. Its proposal is not execution approval.

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

Deployment `37910749759` subsequently completed successfully. A fresh capture
from 09:52:15 to 09:53:28 UTC (17:52–17:53 Singapore time) passed every public
acceptance check at `7efe186`, including all 206 static files and sixteen recovery
windows. API/footer/software/dataset fences agreed. The new
[receipt](data/nextstage-20261009/public-after-7efe186-v1.json) preserves individual
requests, expected 422 refusals and one-sample profile denominators. Health was
HTTP 200. `/sclib` returned 308 to the canonical root. The legacy ASRP root
returned 410, as required by the existing [retirement contract](operations/SITE_INTEGRATION.md);
it is not restored. This accepts that observed SCLib release, not the still
unpublished #166 diagnostics or a formal performance target.

The retained [release replay](data/nextstage-20261009/release-after-7efe186-v1.json)
independently verified all three component SHA files and immutable image digests
at the same `7efe186` revision. API and ingestion release inventories matched
their retained test inventories using the repository comparator; every inventory
hash matched its report. This is locked Python package-version parity on
Linux/amd64, with no additional OS/ABI or scientific execution claim.

At 10:20 UTC, #166's complete [Linux Test](https://github.com/JackZH26/SCLib_JZIS/actions/runs/37903095507)
finished successfully. Independent replay of all eight JUnit reports verified
8,500 passed, 9 skipped, zero failures/errors, 8,509 cases and 268 modules.
The [v3 identity receipt](data/nextstage-20261009/pr166-linux-validation-v3.json)
distinguishes PR head `1b54e0e` from CI's synthetic merge checkout `844e0e5`.
GitHub commit objects show that both, and the final merge `4c56af1`, share the
identical tracked tree `9558861ce0ad8428376bb3fa9b8d314a15b4b38b`.
The executed API/scripts source inventory stayed clean and unchanged. The
overall worktree was dirty; the plan does not enumerate unrelated dirty paths.
The retained v3 corrects v2's overly specific attribution of that flag to
untracked execution artifacts. The ordinary regression took 7,625.136
seconds. Its independent capacity check completed in the successful API job
and remains outside the ordinary-regression denominator.

After checking the original head, every actual Test/Security/offline result,
mergeability and review state, #166 was normally merged at 10:21:49 UTC
(18:21 Singapore time), with commit
`4c56af1693510d148a1642bc035910b064141819`. Its main release/deployment remains
pending; the accepted public release is still the observed `7efe186` above.
#167's API CI also completed successfully by the subsequent refresh. Keep the
optimization pending until #166's actual publication and natural instrumented
scan establish the baseline. The local 73-test compatibility rehearsal does
not replace that production observation. The documentation follow-up #168
is now based on main and remains a draft while this release sequence proceeds.

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

[Acquisition queue v3](data/nextstage-20261009/material-source-acquisition-queue-v3.json)
preserves the historical 200-row order and the 16/184 inspection boundary while
updating custody for five selected-pointer source candidates. The new
[acquisition receipt](data/nextstage-20261009/material-source-acquisition-v1.json)
pins their PDF bytes and all extracted pages, plus one cited original-experiment
candidate. Acquisition and title-page checks do not complete a pilot inspection.

| Material candidate | Retained historical-pointer source | PDF pages |
|---|---|---:|
| MoSr2Eu1.5Ce0.5Cu2O10-δ | [cond-mat/0304552v1](https://arxiv.org/abs/cond-mat/0304552v1) | 8 |
| R8Ni7Oy | [2603.22662v1](https://arxiv.org/abs/2603.22662v1) | 43 |
| La0.4Sm0.6O0.5F0.5BiS2 | [1507.03172v1](https://arxiv.org/abs/1507.03172v1) | 6 |
| BaPb0.72Bi0.28O3 | [1706.06999v2](https://arxiv.org/abs/1706.06999v2) | 19 |
| Bi2TeI | [2209.02688v1](https://arxiv.org/abs/2209.02688v1) | 9 |

R8Ni7Oy needs source-role review: the inherited paper's Table I compiles
literature values, with nickelate references 29–31. Reference 31 identifies
[2602.19093v1](https://arxiv.org/abs/2602.19093v1), now retained privately as an
18-page candidate. The inherited record already declares origin/source role
Unknown/unknown. Locator hashes preserve this navigation question without
promoting that classification or binding the candidate. Reviewers must resolve
generic R versus specific Nd composition, sample/state and transition criterion;
similar values alone cannot establish the association. The current v2 version
of the BaPbBiO3 preprint likewise remains unbound to an unspecified legacy
publication revision. No canonical records were changed.

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

A later [gap acquisition v3](data/nextstage-20261009/retrieval-gap-acquisition-v3.json)
preserves v2 and adds the privately retained one-page publisher retraction notice
for Lu-H-N, with PDF/page hashes and literal notice-to-original DOI checks.
The original article page shows access options and the full article is still
missing, so the Lu-H-N source pair remains incomplete. The Hg cuprate publisher
page likewise requires access. Organic DOI resolution returned HTTP 403; that
response alone does not establish the refusal's cause. Failures and incomplete
source pairs remain in the acquisition denominator. No full text is redistributed.

The privately delivered pending-review ZIP v4 preserves all v3 files and adds
five-row independent material A/B/resolver blanks and the source-custody
metadata. The seventy-two-question blanks and earlier sixteen-material blanks
remain intact. Its [receipt](data/nextstage-20261009/pending-review-materials-v4-receipt.json)
pins the 27-file archive. No original PDFs, extracted passages, filled decisions,
reviewer identities or approved labels are included. Authorized reviewers still
need lawful access to the exact originals and the existing admission workflow.

## Validation of this checkpoint

The existing public-acceptance and Materials-profile offline suites passed all
23 tests. The coordinator's own JUnit reader independently reconstructed each
batch's module membership and counts for both the native `1b54e0e` result and
the completed main `7efe186` Docker result. All 200 historical material response
byte/size pins matched; material IDs were unique and the inspected/uninspected
partition was 16/184. The combined draft IDs were unique, language totals were
46/26, and every draft remained unassigned and unscored. Public JSON was checked
for machine-local paths; raw files and extracted text remain private.

A [local integration rehearsal](data/nextstage-20261009/material-integration-rehearsal-v1.json)
merged the original #166/#167 heads without conflict at
`8a91067f254ee9c2f1cfaafb36d5011023aa74bb`. Four focused API modules passed
**73 tests, zero skips/failures/errors** using newly owned native PostgreSQL/Redis.
The original source inputs stayed clean and unchanged, service cleanup completed,
and API/ingestion property-evidence bytes matched. This exercises request timing,
Tc selection, lifecycle memo and formula lookup together. It is a local code
compatibility result; Linux/full regression, actual publication and production
performance acceptance retain their separate gates.

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


## Later source preparation and completed local integration

The [source and compute follow-up](NEXTSTAGE_SOURCE_AND_COMPUTE_PREPARATION_2026_10_09.md)
now indexes eight retained material candidates with thirty review questions and
thirty page/span locators. Eight remaining publisher PDF requests all returned
401; exact-DOI repository-index observations supplied no full-text address.
Those failures stay in the denominator. Four of the six retrieval-gap cases now
have privately retained full-text candidates, including the HAL version-one
archive of the original organic-superconductor report. The Lu-H-N original and
notice pair remains incomplete. Additional source questions are navigation aids;
the seventy-two retrieval drafts and 16/184 complete-inspection partition remain
unchanged, with no approved rights, gold, reviewer identities or scientific data.

[Review ZIP v6](data/nextstage-20261009/pending-review-materials-v6-receipt.json)
contains 44 metadata/template files and preserves every byte of all 34 v5 members.
The original archives and three independent eight-row blanks remain intact.
A [compute replay](data/nextstage-20261009/compute-readiness-v3.json) freshly parses
four retained raw XML exports through the pinned existing reader. All four new
canonical JSON outputs match the prior readings byte for byte. No solver, node
connection, new worker or additional budget reservation was used.

The [completed integration result](data/nextstage-20261009/material-integration-validation-v1.json)
replaces only the earlier focused rehearsal's full-regression pending scope:
**8,543 passed, 9 skipped, zero failures/errors, 8,552 cases and 269 modules**, eight independently replayed JUnit
batches at local revision `8a91067f254ee9c2f1cfaafb36d5011023aa74bb`, lasting
3,614.272 seconds. All assigned modules reported cases,
all runners exited zero, owned-service cleanup completed, and HEAD plus the
941-file API/scripts inventory stayed clean and unchanged. Capacity is separate.
Skipped cases remain explicitly listed in the receipt.

At 12:01 UTC, #167's observed head became
`8dd638051f04bf31ab125fe150d47196b25b032b`, parented on main `4c56af1`.
Its [GitHub commit tree](data/nextstage-20261009/pr167-integration-tree-identity-v1.json)
matches the tested local integration tree exactly. The execution record retains
its actual local revision; the observed PR's Linux CI was still running and
remains a separate gate. Publication, naturally captured request timing and
production performance acceptance are not supplied by this local result.

The main `4c56af1` [Test run](https://github.com/JackZH26/SCLib_JZIS/actions/runs/37917133614)
subsequently completed successfully at 12:01 UTC. Its new
[Linux receipt](data/nextstage-20261009/main-4c56af1-linux-validation-v1.json)
independently replays all eight batches: 8,500 passed, nine skipped, zero
failures/errors, 8,509 cases and 268 modules. The 940 enumerated API/scripts
inputs stayed clean and unchanged; the whole-worktree dirty flag remains true
and unspecified other dirty paths are not inferred. The
[release replay](data/nextstage-20261009/release-after-4c56af1-v1.json) binds three
component image digests and three successful package-inventory comparisons to
this exact Test run and original artifact IDs. Release run `37927409318` succeeded
at 12:05 UTC. Deployment `37927770900` was in progress, and the 12:10 public
version observation still returned `7efe186`. New-version deployment and public
acceptance therefore remain pending in this checkpoint.


## Completed 4c56af1 publication and diagnostic scans

Deployment `37927770900` completed successfully at 12:34 UTC. The
[deployment receipt](data/nextstage-20261009/deployment-after-4c56af1-v1.json)
binds the completed job log to Release `37927409318` and observed public version
`4c56af1`, dataset `v2026.09.03`, API `1`. First, the
[strict profile](data/nextstage-20261009/material-profile-4c56af1-v1.json) captured
25 successful fixed-query gzip requests with valid timing headers: one natural
scan and four page hits for each of five queries. The subsequent
[complete public capture](data/nextstage-20261009/public-after-4c56af1-v1.json)
passed all twenty checks, all 206 static byte pins and all sixteen recovery
windows across 253 retained requests. Software/footer/dataset and before/after
version fences agreed. Earlier pending observations above remain historical.

The [diagnostic baseline](data/nextstage-20261009/material-performance-baseline-4c56af1-v1.json)
records a 22.998-second default client scan and 22.582-second server total, with
10.293 seconds in selection and 10.783 in scope. The existing Tc-selection
experiment addresses an observed major cost; scope includes SQL and needs its
own diagnosis. The fifteen-second first-request goal is not demonstrated.
One scan per query is neither statistical p95 nor production before/after
performance acceptance; page-hit latencies are kept separate.

The [v2 request plan](data/nextstage-20261009/material-performance-observation-plan-v2.json)
makes complete-acceptance accounting explicit. Actual Materials calls were
25 profile list GETs, 24 acceptance list GETs and sixteen enrichment GETs,
65 total against a maximum 90 per code arm. No second capture was necessary.
Source review, rights, gold, training, node handoff and the new finite budget
still require their real authorization and admission.
