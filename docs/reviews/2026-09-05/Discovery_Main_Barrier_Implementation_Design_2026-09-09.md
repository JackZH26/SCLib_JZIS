# Next increment: explicitly declared main barriers in Discovery

Status: proposed local implementation handoff, **not implemented or scientifically
approved**. Follows batch 51. Tracking: [DR04 #77](https://github.com/JackZH26/SCLib_JZIS/issues/77).

## Evidence for the remaining gap

The issue's compact-view acceptance includes a main barrier. The current
`ScientificDiscoveryMatrix` instead shows “Main barrier not separately declared”,
correctly following `docs/DISCOVERY_SCIENTIFIC_PROJECTIONS.md`: existing frozen
constraint/reason lists do not identify a primary physical barrier.

The v1 selection and payload are closed contracts. The native package guard in
`api/models/discovery_projection_v1.py` accepts only payload version
`discovery-scientific-projection/1.0.0`. Adding a UI-only property, silently
changing old selection bytes, or loosening only a frontend allowlist is not a
valid implementation.

## Smallest useful scientific contract

Introduce explicitly dispatched selection/payload v2, preserving v1 reads,
historical bytes and write behavior. For each selected material representative,
require one explicit `main_barrier` choice:

- `status: not_declared`: an intentional curator choice, not a fabricated value.
- `status: declared`: a bounded statement, rationale and exact typed basis
  references, all confined to this representative's selected state/action and
  nullable structure context.

The implementation design must close the exact object fields and length/count
bounds before writing the migration. Basis references may refer only to actual
retained matching cell/result/evidence references or exact assessment reason /
execution-constraint codes. There must be no arbitrary URL/path/source fetch,
unregistered evidence, another material/state/action, or invented hash. A
reason code's presence establishes a recorded policy basis, not physical proof.

Use the label **“Curator-declared main barrier”**. This is a reviewed research
interpretation, not proof of the primary causal obstacle to superconductivity.
An evidence gap is not negative evidence; an execution/resource constraint is
not a measured material property. Unknown/not-computed/inapplicable quantities
must never be converted to a zero or anti-superconducting contribution.

## Versioned end-to-end work

1. Define exact v1/v2 dispatch in the scientific projection/selection compilers
   and matching closed frontend parsers. Do not add the new field to v1.
2. Add an incremental native migration with explicit compatible payload-version
   guards. Do not edit the meaning of an already applied migration or broaden
   the trigger to accept arbitrary future versions. Check schema admission,
   historical package/replay/restore and runtime compatibility paths.
3. Extend curator preparation/UI with no default declaration. Changing selected
   assessment/structure clears the statement, references, preview and rehearsal.
   Do not choose the lowest dimension, first reason or highest-score action.
4. Bind the declaration into selection/payload hashes and the full current
   reconstruction. Any change produces a new package requiring new independent
   review/disclosure/publication; old approval pins cannot be reused.
5. Show declaration, rationale and exact basis in private inspection/review and
   the compact public row/details. v1 remains honestly “not separately declared”.
   Do not change frozen RPS values, weights, field registry or comparison scope.

Reuse the existing three-account and source-currentness guards. Main-barrier
review must not create a new scientific-acceptance boolean, a material-wide
approval flag, or training-label authority. Source holds still deny positive
publication while history/protective rejection/withdrawal remain available.

## Required verification

- Existing v1 raw byte/hash fixtures and historical recovery remain unchanged.
- v2 closed documents reject missing/extra fields, unsupported versions,
  cross-context/stale/unretained basis references and excess payloads.
- Changing score order, adding alternatives or missing dimensions cannot select
  or alter a barrier. Explicit nondeclaration works without invented evidence.
- A declaration edit invalidates old preview/package/review/publication pins.
- Guarded disposable SQL-to-HTTP covers register, independent review, publish,
  public reconstruction and later source hold, plus protective operations.
- Frontend tests cover explicit choice, full basis/rationale display, no default
  scientific conclusions, session clearing, deadlines and original-key recovery.

No real dataset write, provider access, physical calculation, scientific/rights
approval or production deployment is part of this local implementation slice.
The real reviewed pilot remains a distinct DR04 acceptance gate; empirical
priority calibration belongs to AL01, not to this descriptive field.
