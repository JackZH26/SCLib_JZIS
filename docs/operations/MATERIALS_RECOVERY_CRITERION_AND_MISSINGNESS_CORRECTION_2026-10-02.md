# Materials criterion handoff and missingness correction

An independent read-only audit of the final R7 source found three concrete
accuracy problems in the recovery handoff and evidence wording. This correction
does not import scientific records or change catalogue selections.

## Tc definitions survive the review handoff

`pending_tc_records` supplied `tc_criterion`, while the existing typed mapper
reads `tc_definition`, `tc_type`, or `criterion`. The 39-candidate primary seed
produces nine pending Tc handoffs. The source-bound 21.5 K zero-resistance and
23 K onset handoffs therefore mapped to typed `unknown`, despite preserving
their definitions in the raw record.

The additive handoff now supplies `tc_definition` as well as the original
`tc_criterion`. The mapper retains those two known definitions; the other seven
remain unknown. Pressure, origin, evidence provenance, review requirements and
pending disposition retain their existing semantics. The source candidates,
candidate IDs and all five packaged resources remain unchanged.

Adding a raw handoff key legitimately changes the proposed raw-record hash and
typed claim UUID of all nine offline handoffs. The two known definitions also
change their semantic fingerprints. These are proposed handoff identities, not
existing production rows or new independent experiments. Replaying historical
handoffs must not be described as inserting nine new experiments.

The source candidate's complete criterion remains available for review. A
figure-scoped 90% resistivity definition must not be translated to generic onset
or copied to every result from its paper.

## Missing extraction is not a reviewed-paper absence

The recovery status `not_extracted` now displays **Not extracted**. Its reasons
can include an unimplemented parser, unavailable capture, or a source statement
whose subject still needs review. **Source text not checked** was too specific
for this shared status. Bounded checked-chunk searches and unavailable sources
keep their separate statuses.

Absent source locator, method or state in a retained evidence record now
displays **Not supplied in this record**. It does not claim that the
paper omitted those fields. A supplied `Unknown`, an actual method, and actual
same-record conditions continue to render as supplied.

## Validation and release boundary

Regression checks exercise the real handoff and typed mapper, retain unknown
definitions, and distinguish recovery reasons and absent metadata from supplied
values. Updated source requires fresh genuine native protocol captures and
exact-head CI. R7 archives, source receipts and secret triage remain immutable
historical checkpoints. Signed release, deployment and public acceptance still
need to verify the final merged source.

This correction grants no source rights, human review, scientific acceptance,
ML-training admission, canonical promotion or database mutation.
