# Proposed next increment: mandatory typed identity and leakage audit

Date: 2026-09-09. Issue: [ML06 / #70](https://github.com/JackZH26/SCLib_JZIS/issues/70).
Status: implementation handoff, **not implemented or scientifically approved**.
Preceding checkpoint: [complete captured label-currentness](Priority_Forty_First_Batch_Implementation_2026-09-09.md).

Historical status above describes this proposal at handoff. The subsequent
implementation contract is [ML identity audits](../../ML_IDENTITY_AUDITS.md);
consult the [forty-second implementation report](Priority_Forty_Second_Batch_Implementation_2026-09-09.md)
for tested scope and delivery status. This
proposal is not a live API specification or scientific approval.

## Concrete gap

The existing v4 compiler constructs complete frozen leakage groups before
label exclusions and rebuilds its cohorts and train-only preprocessing.
`_groups` returns a typed `(kind, id) -> component_sha256` inventory. However,
the exported bundle retains opaque component IDs and a literal empty
`component_crossings` list, rather than a complete typed membership/count audit.
The current view reports include row/group/family balance and missingness;
these do not establish the Work/state/trajectory identity accounting requested
by ML06's final acceptance criterion. This is not a reproduced split leak.

## Minimal architecture

Use a new mandatory audited wrapper, not edits to frozen v4 sources and not a
copy of the entire builder. Proposed files:

- `api/services/ml_identity_audit.py`: bounded deterministic pure audit.
- `api/services/ml_audited_dataset.py`: unchanged v4 build plus mandatory audit.
- A separate offline CLI with stable five-input reads and no-overwrite output.

Proposed envelope:

```text
version: ml-identity-audited-dataset/1.0.0
base_dataset: complete unchanged v4 bundle
base_dataset_sha256
identity_audit
identity_audit_sha256
audit_policy_version
audit_implementation_sha256
gate
authority: all false
```

Keep the original v4 task, input pins, compiler source pins, statistical rows,
partitions and fitted parameters unchanged inside the base. The new outer
protocol names the additional mandatory audit and pins its implementation.
Only a passing base gate **and** passing audit gate may write the new technical
package. An optional inspection sidecar cannot replace this mandatory gate.
Verification rebuilds both the base and audit from independently pinned inputs;
a freshly recomputed outer hash alone cannot legitimize modified assignments.

No public endpoint, database migration, authentication/rights assertion,
training run or publication capability is needed for this increment.

## Exact units and limits of interpretation

| Unit | Existing exact basis | Must not infer |
| --- | --- | --- |
| Work, Paper, revision, capture, occurrence | Frozen foreign keys and verified 0052/0064 bindings | Separate papers/occurrences are independent experiments |
| State and Sample | Exact state/sample IDs and composite material references | Equal conditions or sample-label strings prove specimen identity |
| Material series | Explicit `parent_material_id` subgraph | Stored `parent_series_group` strings are reviewed grouping evidence |
| Trajectory | `sample_trajectory` links with retained review bytes and exact endpoint hashes | Every unlinked sample is a known independent trajectory |
| Structure ancestry | Explicit `parent_structure_id` | Same formula proves the same structure |
| Near-duplicate cluster | Exactly bound `structure_near_duplicate` declarations | Different coordinate bytes prove structures are not near duplicates |
| Run and coordinate bytes | Actual declared run/manifest identities and verified coordinate hashes | A captured declaration authenticates execution of a calculation |

Namespace keys such as `material_ancestor`/`material` and
`structure_ancestor`/`structure` must not double-count one underlying row.
Report trajectory/series/near-duplicate connected components with explicit
edges separately from identities with no such declared relationship. Do not
name the latter "independent trajectories" or "independent series".

Unreviewed Paper/Work mappings may conservatively connect leakage components;
that does not make them verified aliases for positive evidence counting.
No title, citation-string, DOI-similarity or sample-name heuristic is added.
There is no general independently verified replication/batch registry in the
current contract. Keep `independent_support_count=null` and relationship
completeness explicitly limited to the captured declarations.

## Audit content

1. Sorted typed member inventory for every full frozen component, including
   excluded candidates, unselected features and noncandidate bridging nodes.
2. Every root example's exact claim, component, candidate status, admitted B
   partition and B/P/S/PS membership. All excluded examples remain inspectable.
3. Controlled join witnesses: relationship rule, typed endpoints and the frozen
   row/declaration artifact hash supporting that existing grouping rule.
4. Per-cohort/per-partition rows, components, typed identity counts and missing
   direct-identity counts, with denominators retained.

Separate **direct selected-label identities** from **all identities associated
with their full leakage components**. The latter include excluded bridges and
unused sources; they are not counts of selected supporting evidence. Neither
count establishes independent scientific replication.

Reconstruct the existing grouping rules faithfully; current label observation,
review actors or audit-only references must not introduce new scientific edges.
The audit must check complete reconstructed component hashes against the
unchanged builder output rather than assigning new groups opportunistically.

## Computed checks and no-go behavior

- Recompute sorted membership hashes and match every exact component ID.
- Accumulate actual B partitions for each identity and component. More than
  one partition is a crossing and fails the audit; do not emit a constant list.
- Verify every controlled join's endpoints belong to the same component.
- Require P/S/PS to be subsets of B; one example keeps its component/partition
  across all relevant cohorts and views.
- Check all same-cohort comparison views have identical members/assignments.
- For family holdout, use the complete component family set, including excluded
  nodes. Mixed/unknown-family components remain excluded and unassigned; assigning
  one fails the audit. Overall dataset no-go still follows the unchanged v4
  cohort/view gates, not the mere presence of an excluded component.
- Apply chemical-system separation only when the declared task requests that
  split mode; do not impose extrapolation rules on interpolation tasks.

Malformed identities, unknown references, duplicate members, missing frozen
rows, incorrect hashes or exhausted resource budgets reject a complete success
report. Do not truncate a graph and label it complete. Set explicit node,
relationship, membership-reference and serialized-byte budgets before
implementation, consistent with existing bounded context reconstruction. Bounds
are engineering constraints, not dataset capacity or runtime guarantees.

## Grounded verification plan

Reuse actual frozen SQL/canonical fixtures and distinguish pure adversarial
audit tests from end-to-end native capture/compilation evidence:

1. Two Paper versions, one Work, several revisions/occurrences and repeated
   citations: exact source counts, one Work identity, no invented replication.
2. One Sample with multiple States remains joined. Equal sample-label strings
   on otherwise distinct IDs do not fabricate a specimen alias.
3. Existing trajectory/structure declarations retain exact endpoint hashes,
   review bytes and deduplicated memberships; a wrong endpoint pin fails.
4. V4's excluded bridge remains in the reported complete component. A component
   with conflicting family destinations remains excluded/unassigned even if the
   bridge itself is excluded; assigning it fails the audit, not automatically
   every otherwise valid surviving cohort.
5. Actual Tc-derived feature ancestry remains excluded from feature views while
   required result/run/structure nodes remain in the leakage graph.
6. Repinned changes to members, counts, splits, cohort/view membership or audit
   results fail complete recomputation; direct crossing canaries establish that
   the audit really computes the claimed invariant.
7. An actual offline CLI builds/verifies a valid synthetic audited package;
   audit no-go writes no output, old v4 replay remains byte-identical and no
   database/provider/network connection is possible during offline replay.

Useful existing modules: `test_ml_task_dataset_sql.py`,
`test_ml_dataset_adversarial.py`, `test_ml_physical_feature_sql.py`, and
`test_ml_dataset_v4.py`. Run database tests only through the guarded disposable
runner. No real curation, source rights, training or deployment is authorized
by this design or its synthetic acceptance tests.
