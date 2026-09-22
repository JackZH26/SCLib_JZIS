# Explicit Discovery main barriers

Scope: DR04 [#77](https://github.com/JackZH26/SCLib_JZIS/issues/77). This is an
interpretation and disclosure contract, **not a new superconductivity label,
probability, empirical utility score, or scientific-acceptance decision**.

## Scientific meaning

The compact material row displays **Curator-declared main barrier** for the
explicitly chosen material/state/structure/action in a frozen campaign. A
curator can intentionally decline to declare a primary barrier. The system
never chooses the lowest-scoring dimension, first reason code, highest-scoring
alternative action, or a family stereotype on their behalf.

| Category | Permitted basis | What it does not establish |
| --- | --- | --- |
| `evidence_gap` | Selected scientific cells marked `unknown`, `not_computed`, or `conflicted` | Absence of superconductivity, a measured zero, or a physical disadvantage |
| `execution_constraint` | Exact codes in the selected assessment's `execution_constraint_reasons` | A measured material property or a mechanism-level obstacle |
| `scientific_hypothesis` | Selected `reported` or `conflicted` scientific cells with at least one quantified observation | A proven cause, a universal threshold, or correctness of an unreviewed result |
| `recorded_policy_reason` | Exact codes in the selected assessment's `reason_codes` | Independent physical evidence or a validated priority model |

Conflicting observations may justify either an evidence-gap declaration or a
scientific hypothesis, but only as the curator's explicit interpretation. A
reported value alone does not determine whether it is positive or negative for
superconductivity. Family, pressure, structure, calculation method and the
claimed mechanism still matter. The rationale must communicate those limits;
schema validation cannot judge whether a physical explanation is true.

## Closed, versioned documents

Existing `discovery-scientific-selection/1.0.0` and
`discovery-scientific-projection/1.0.0` documents remain v1 and do not acquire an
extra field. They continue to display “Main barrier not separately declared”.
New v2 documents pair `discovery-scientific-selection/2.0.0` with
`discovery-scientific-projection/2.0.0`; mixing versions is invalid. Each v2
representative and corresponding payload row contains exactly one of:

```json
{"status":"not_declared"}
```

```json
{
  "status": "declared",
  "category": "evidence_gap",
  "statement": "The selected context lacks a reported coherence observable.",
  "rationale": "This identifies missing evidence to investigate, not evidence against superconductivity.",
  "basis_refs": [
    {"kind":"scientific_cell","property_key":"superfluid_stiffness"}
  ]
}
```

This is a contract illustration, not a declaration for an actual material.
Statements contain 1–500 Unicode code points and rationales 1–2,000. They must
contain non-whitespace text. ASCII control characters other than TAB, LF and
CR, plus DEL, are rejected. There must be 1–8 unique basis references, sorted
by Unicode code-point order of `kind + ":" + code_or_property_key`. The only
reference shapes are:

- `{"kind":"assessment_reason","code":"<exact recorded code>"}`
- `{"kind":"execution_constraint","code":"<exact recorded code>"}`
- `{"kind":"scientific_cell","property_key":"<registered key>"}`

The code is bounded to 200 code points and matched exactly, including case and
any colon. It is not converted into a new distribution reason code. A cell key
addresses the unique cell **inside this selected representative**. Its complete
result/evidence references, native hashes, availability and reason are already
bound by the selection hash. It does not point to an arbitrary same-named
property from another material, state or structure. Result observations and
their current review pins are bound by the payload hash. No URL, local path,
unregistered property, free-standing citation or invented evidence hash is
accepted as a basis reference.

The eight scientific registry properties and registry capability version are
unchanged; v2 does not pretend the full frontend dictionary is populated.
Frozen RPS values, weights, comparison scope and calibration disclaimer remain
unchanged. Main barriers are excluded from scientific labels and do not grant
ML-use authorization.

## Operator and publication flow

The existing read-only selection context and transport receipt wrappers remain
version 1; their closed outer shapes do not change. `/selection/prepare` retains
v1 behavior. The explicit `/selection/prepare-v2` route requires a v2 barrier
choice for every material. New UI selections use that route, with no default
declaration, category or basis. Editing the assessment, structure or a scientific
cell clears the declaration. Editing any declaration invalidates its prepared
preview and registration rehearsal.

Preparation and registration reconstruct actual retained data. The declaration
is included in selection and payload hashes, so an edit needs a new package
and fresh independent selection/disclosure review. An old package's approval
cannot authorize a newly declared interpretation. The existing three-account
curator/reviewer/publisher boundary, current-source checks, exact rights targets
and scientific-cell publication requirements remain authoritative. Review of
the declaration concerns the representative selection and disclosure; it does
not add a new `scientific_acceptance` boolean.

Public compact rows show the category and statement. Expanded material details,
curator previews and governance inspection expose the rationale, exact basis
and selected context pins. A later source hold blocks positive use/publication;
bounded history, protective rejection and withdrawal remain available.

## Migration and recovery

`0070_discovery_main_barrier` adds native paired-version and declaration guards
over the existing immutable Discovery governance tables. The original0069
migration and guard definition remain unchanged. Fresh model-created test
databases install the same0070 guards after0069.

A downgrade to0069 is permitted when only v1 packages remain, restoring the
original insert function without rewriting retained v1 bytes. It refuses when
v2 packages exist; deleting reviewed history is not a rollback plan. Application
schema admission requires the exact configured head. Any deployment needs an
approved backup/migration/compatible-code rollout; this local implementation
does not migrate production or enable public approval maps.

## Acceptance still outside this implementation

Synthetic SQL/HTTP and frontend tests establish software invariants only. DR04
still needs a genuinely reviewed real-data pilot and remote delivery evidence.
This field does not satisfy the real pilot, source licenses, scientific
adjudication, real-model training, or the independent fixed-budget AL01
evaluation in [#78](https://github.com/JackZH26/SCLib_JZIS/issues/78).
