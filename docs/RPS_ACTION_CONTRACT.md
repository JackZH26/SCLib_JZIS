# RPS action contract — DR01

Status: local implementation; no scientific action templates, review approvals or
production releases are created by this change. All test fixtures are synthetic.
Do not copy fixture approvals into a real release.

## Scope and numerical policy

RPS ranks **material + defined state + next action** within a frozen campaign and
budget. It is policy-defined research priority, not superconductivity probability,
calibrated utility, universal material quality, or an instruction to execute.

The numerical RPS-v1.2 policy is unchanged:

- Six physical dimensions retain their weights even when support is unknown.
  Effective weights = 50% common + 50% campaign-pinned profile mixture.
- `P = sum(effective_weight × physical_lower_bound)`; unknown contributes lower
  bound 0, upper bound 100 and is not experimental negative evidence.
- `G = 100 × D.lower × T.lower`.
- `B` uses the worst required-resource **upper-cost / campaign-budget** ratio:
  ratios ≤0.1, ≤0.25, ≤0.5, ≤1 map to 1, 0.75, 0.5, 0.25 respectively.
- `A = 50 × (B + R.lower)`; raw = `1000 + 45P + 27G + 18A`.
- Display uses nearest 50, half-up. The unchanged golden case is P=60, G=A=75,
  raw 7075, display 7100. Baseline 5500 plus physical, gain, execution and
  rounding contributions reconstructs the display exactly.

Eligibility is now an explicit, stricter contract. `POLICY_VERSION` remains
`RPS-v1.2` because its numerical formula has not changed; `POLICY_HASH` changes
and includes `action_contract_version = rps-action-contract/1` and the eligibility
rule identifier. Consumers must pin/check the hash, not only the display version.
This is an intentional fail-closed compatibility break.

## Required records

`Assessment.action_requirements` carries the complete execution declaration:

| Field | Contract |
| --- | --- |
| `schema_version` | `rps-action-contract/1` |
| `template_ref` | ID and SHA-256 of the immutable `action_template` artifact |
| `template_review` | ID and SHA-256 of its separate completeness-review artifact |
| `template` | Inline typed template; must equal the referenced artifact content |
| `prerequisites` | Exactly one declaration for every template rule |
| `dependencies` | Typed, evidence-linked availability declarations; no duplicates, unresolved or orphan IDs |
| `resources` | Exactly one applicability declaration for each of the five categories |

A template (`rps-action-template/1`) defines version, title, scope, action kind,
explicit prerequisite rules, prerequisite-completeness rationale and all five
resource rules. Action kinds are verification, calculation, conversion and
measurement. Each prerequisite specifies a dependency kind, whether it is
critical, and whether a justified not-applicable declaration is permitted.
Dependency kinds include structure, sample, equipment, software, data, external
and other. A complete template may have no prerequisites only with an explicit
completeness rationale and an actual completeness review; the software cannot
establish whether such a template is scientifically adequate.

Prerequisite status is satisfied, pending, blocked, unknown or not_applicable.
Satisfied declarations require evidence and at least one matching-kind linked
dependency; every linked dependency must be available. Available dependencies
also require evidence. Not-applicable prerequisites need evidence and rationale
and must be permitted by their template. `blocked` means confirmed unavailable or
unsatisfiable for this action under the current fixed campaign; it needs rationale
and traceable evidence. `pending` means resolution is outstanding, and `unknown`
means availability is not established; these require rationale but may honestly
have no evidence yet. A blocked dependency cannot masquerade as a satisfied
prerequisite. External equipment/sample access
is represented here even when it is not a priced resource category.

Dependencies are availability attestations, **not** executable jobs, dependency
DAGs, reservations, live inventory checks or guarantees of access. Evidence must
identify the relevant structure/sample/equipment version and availability basis.
The curator must check that evidence applies to this material, state and action,
including expiry or changed access. A later status/input revision requires a new
assessment/release; the original release remains a historical snapshot.

## Complete resources and eligibility

The fixed cost vocabulary is cpu_core_hours, gpu_hours, memory_gib, storage_gib
and human_hours. Their interpretations must be consistent within the campaign:
CPU core-hours and GPU-hours are consumption; memory is peak GiB, storage is
additional/reserved GiB over a stated horizon, human-hours are effort. GPU type,
hardware/software assumptions and horizon belong in the cost basis/evidence.
The scorer does not silently convert architectures, currency or units.

Template resource rules are required, optional or not_applicable. An assessment
declares required, unknown or not_applicable, with rationale and evidence for
known applicability. A template-required category cannot be declared not
applicable. An optional category must be resolved explicitly for that action;
not applicable is allowed only with the reviewed rationale/evidence. A genuinely
changed scope needs a new template version and review, not an omitted resource.

`costs` must exactly match declared required resources. Each required cost has
finite nonnegative bounds, upper ≥ lower when known, a basis and evidence.
Unknown upper bounds stay null, never zero. All five applicability declarations
are displayed, including unpriced/not-applicable categories, so omitted human
effort or memory cannot disappear from view. A template must identify at least
one costed required category; pending applicability may temporarily have no
cost rows without being treated as a free action.

Ranking gates:

- Critical prerequisite blocked, or a blocked dependency required by a critical
  prerequisite → ineligible, no score. This applies to structures, samples,
  equipment and external access as well as other dependency kinds. A parent
  prerequisite labelled pending/unknown cannot hide a confirmed blocked input.
- Critical prerequisite pending or unknown, without a confirmed required block
  → pending, no score. Noncritical dependencies and genuinely not-applicable
  prerequisites (per the reviewed template and evidence) are not hard gates.
- Resource applicability unknown or required cost upper bound unknown → pending.
- `R.lower = 0.25` retains its rubric meaning of unresolved critical uncertainty
  → pending, even if a declaration otherwise appears ready. `R.lower = 0` is
  ineligible. Raising R cannot override an unresolved critical prerequisite.
- Missing/zero budget for a required resource or any upper cost over budget →
  ineligible. Unknown applicability is not resource availability.
- D.lower=0 or T.lower=0, resolved problem, target mismatch, or an unregistered
  template → ineligible. Unresolved target fit → pending.
- Reference, benchmark-control and negative-control roles remain unranked.
  Negative-control **role** never creates an experimental negative **outcome**.
- A low/zero physical-support dimension alone is not an execution veto. Such an
  action may still be informative; a missing required structure is a different,
  operational constraint and cannot be offset by high P or G.

For example, DFPT needs the appropriate coordinate structure, method inputs and
compute access; a measurement needs an identified sample, suitable apparatus and
access. Neither can rank as executable while a critical prerequisite is unknown.
A separately scoped structure-verification or sample-preparation action may rank
only after its own inputs, outcomes, costs and template have been reviewed. Merely
renaming DFPT as verification does not meet that scientific review requirement.
Unresolved purchases or equipment access remain pending; confirmed unavailable
required access is ineligible in this campaign, even if P/G/R are high. Neither
status asserts permanent physical impossibility: a changed campaign or a
separately reviewed preparation action can be assessed anew. The five-category
budget is not a currency/procurement model or a feasible multi-action portfolio.

## Review and integrity boundary

The campaign pins each allowed template artifact ID and full artifact digest.
A separate `template_review` must record approved decision, nonblank reviewer ID,
scope `prerequisite_and_resource_completeness`, rationale, evidence references,
and the exact template ID/version/hash. The template must exist no later than
its review, and template approval must exist no later than the action artifact
or assessment review. Templates and template reviews are within the evidence
cutoff. An assessment review may follow the cutoff, but not publication.
These times describe actual recorded availability, not backdated approvals.

The action artifact binds `action_requirements_hash` and
`assessment_action_hash`. The latter covers summary, outcomes, costs and the
**entire** action requirements, including prerequisite/dependency statuses,
resource applicability, rationales, evidence and template/review references.
The existing assessment review additionally binds the entire assessment, fixed
campaign and policy hash. Changing any bound field requires new hashes and a
new actual review, then a new immutable release approved through the existing
administrator-pinned manifest allowlist. Changing a manifest hash alone does
not refresh an action or assessment review.

The release validator resolves every template, template-review and execution
evidence reference. Retracted evidence cannot support a published assessment.
The detail API includes execution and template-review evidence metadata with
source version and locator; it never returns source full text. The frontend
checks release identity, template metadata, contract version, hash consistency
and complete resource categories before showing verified detail.

Hashes prove content integrity, **not reviewer identity or scientific truth**.
Reviewer IDs are recorded attestations, not cryptographic signatures. Approval
authority remains the trusted curator/administrator release workflow; this change
adds no public write/approval path. Independent public whole-bundle download and
recomputation, catalog failure isolation and richer authorization are DR02, not
claimed as completed here.

## Honest contribution explanations

`Dimension.evidence_polarity` is supporting, opposing, mixed, neutral or unknown.
It is an evidence judgment with rationale/locators, not inferred from the sign of
the field, score or lower bound. Unknown support cannot carry a contrary polarity.
Assessed but unclassified evidence is explicitly labelled unclassified; it is
never silently called adverse. Mechanism-dependent/nonmonotonic effects must be
judged in the fixed rubric and state, not assigned universal positive signs.

For effective dimension weight w:

- Assessed anchor contribution: `45w(anchor − 50)`.
- Conservative uncertainty discount: `45w(lower − anchor)`.
- Unknown support: missing-support contribution `−2250w`, with null anchor and
  null uncertainty components, **not** opposing evidence.

These components sum to the existing lower-bound dimension contribution.
An anchor 75 with [25,100] and supporting evidence reports supporting evidence
plus an uncertainty discount, not adverse evidence. Explicit opposing evidence
is labelled adverse only because of its declared polarity, not a low score.
Execution constraint codes are separate from physical explanations. Bounds are
assessment bounds, not confidence intervals; empirical calibration is pending.

## Migration and remaining human work

There is no auto-upgrade or legacy-score fallback. Old bundles lacking the new
required fields or carrying the old policy hash fail validation; the UI hides
old-contract scores. Do not overwrite an old pinned release or synthesize review
approvals merely to restore serving. Preserve prior files as historical records.

For each future real release:

1. Define scoped scientific action templates and complete resource/prerequisite
   rules; have a qualified reviewer actually assess completeness.
2. Record actual versioned template artifacts, actual review metadata and
   traceable evidence. Create a new fixed campaign revision pinning those hashes.
3. Reassess action states, dependencies and costs at the declared cutoff; retain
   pending/unknown status where availability evidence is absent and record
   blocked only for evidence-backed unavailability.
4. Produce new action and assessment hashes and actual assessment approvals.
   Validate with `scripts/validate_priority_release.py` locally. Test fixtures
   cannot establish that the human scientific-review step is complete.
5. Review the full release, then separately authorize/pin its new manifest through
   the existing publication process. This implementation does not publish it.

Local regression coverage includes numeric goldens, fixed denominators, gating,
complete resources, missing structures/samples, separately scoped verification,
template/review timing and tamper binding, honest polarity explanations, and UI
fail-closed behavior. Use the disposable runner in `docs/TESTING_SAFELY.md`; do
not invoke API pytest directly against any reusable database.
