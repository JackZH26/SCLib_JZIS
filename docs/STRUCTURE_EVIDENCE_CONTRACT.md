# Structure evidence contract — SC11

Version: `structure-evidence/1.0.0`.

The byte-identical implementations are
`ingestion/ingestion/structure_evidence.py` and
`api/services/structure_evidence.py`. They perform no database, model, network,
file, coordinate, or scientific-approval operation. The limited field set is
`structure_phase`, `crystal_structure`, and `space_group`.

This increment delivers **pending relation proposals**, not reviewed structure
records. Neither an exact quotation nor a source's active lifecycle status is
scientific acceptance. No CIF, coordinates, structure descriptors, or verified
experimental/computational structure match can be generated from these labels.

## Extraction and retained originals

```python
annotate_structure_records(
    records, body=assembled_text, paper_id=source_id,
    source_revision=None,
)
```

The function returns copies and does not modify input records. Original NER
output remains in `raw_extraction`. Existing raw structural labels are neither
deleted nor rewritten. The old whole-paper regex fallback no longer populates
each material's `structure_phase`.

NER may additionally emit `structure_claims`, a list of objects containing
`field`, `value`, `evidence_text`, and an explicitly source-reported locator.
These typed proposals remain separate from the main measurement quotation.
Conflicting typed and raw values are retained as separate alternatives.
Historical normalized-only labels, including old paper-wide fallback values,
remain explicitly unlinked proposals rather than disappearing from the audit.

Each record receives a `structure_evidence` extraction annotation with pending
proposals, unassigned document mentions, assessment completeness, version,
`coordinate_status=not_validated`, and `scientific_acceptance=false`.
Document mentions are not assigned to the record merely because the annotation
is carried with that record. Public projection deduplicates these mentions.

## Local text checks and their limits

An extraction proposal can have association `literal_local`, `unassigned`,
`ambiguous`, or `conflicted`. All retain `status=pending`.

`literal_local` means a bounded quotation occurs exactly once in the examined
input, and the record's literal formula and label co-occur there without a
recognized material/state conflict. Explicit sample/state identifiers must
occur locally. Supported simple pressure units are compared without silently
moving a result to another pressure; unresolved ranges, uncertainty, multiple
pressures and conflicting simple doping values remain unresolved. Recognized
negative, tentative, cited, or compound context prevents a literal-local label.

This is a transparent, conservative co-occurrence check, **not general relation
entailment, correct extraction, complete citation detection, or acceptance**.
Formula aliases, complex multilingual phrasing, tables requiring cross-row
context, unlisted materials, and interpretation-dependent relations still need
human adjudication. Unknown sample/state context is never filled by formula
equality. An explicit label is not evidence that a structure caused a Tc value.

Unassigned phase mentions retain a bounded surrounding sentence/context, its
character span, and a separate mention-token span. A family alias such as YBCO
is a mention candidate, not a coordinate structure or an inferred phase result.
Context clipping is explicit through `context_complete=false`.

## Source identity and coordinates

Extraction evidence locators use `kind=assembled_text_char_span`, with Python
Unicode character offsets `start` and `end`. They index the captured assembled
NER text; they are not PDF page, byte, or canonical full-publication coordinates.
Any supplied page/table locator remains separately source-reported and is not
authenticated by a string match.

`content_sha256` hashes the UTF-8 examined input, with
`content_identity_basis=assembled_ner_input_utf8`. The examined input is bounded
to 16,000 characters. A longer supplied input produces explicit incomplete
coverage and cannot generate literal-local associations. Its hash identifies
the examined prefix, not the complete publication. No current date, earliest
paper date, or hash is substituted for a publication revision.

`publication_revision` stays null unless explicitly supplied. Even then its
status is source-asserted, not independently verified. Source-version registries
and result availability remain ML01/ML03 work.

## Public projection

```python
build_structure_evidence(records, scope_id=material_id, source_statuses=None)
```

Output shape:

```text
version
scientific_acceptance: false
coordinate_status: not_validated
properties[field]:
  status: pending | unknown
  value: null
  proposal_count: integer
proposals: bounded pending proposal list
unassigned_mentions: bounded unassigned mention list
coverage:
  record_count
  proposal_count
  unassigned_mention_count
  assessment_complete
  display_truncated
warnings
```

The public projection never trusts a supplied approval flag or proposal ID.
IDs are regenerated deterministically from allowlisted proposal content and
scope; duplicate proposals accumulate occurrence counts, not independent-result
or replication counts. No votes or numerical confidence scores establish truth.

The reserved derived `structure_evidence` envelope is excluded from original
claim/source-record, atomic-property, scientific-filter, material-semantics,
anomaly and Timeline occurrence identities. Adding, updating or publicly
redacting that annotation cannot mint a different original Tc result. Original
`structure_claims` and raw structural labels remain identity-bearing source
content: changing them still changes the corresponding scientific identity.
Unannotated historical identities are unchanged by this exclusion.

Public proposals preserve field/value, bounded declared subject and conditions,
source identity claims, locators, record origin/source role, reasons, and
`representation=text_claim`. Their coordinate artifact ID is always null.
Stored source/subject/value mismatches remain unassigned with explicit reasons;
they are not silently rebound to the containing material record. A stored
association may be retained as `source_declared_association`, never as a verified
public relationship. Raw legacy labels remain pending even without annotations.

Without authoritative source bytes, the public evidence verification is always
`not_rechecked_against_source`. The source lifecycle lookup can add holds, but
cannot authenticate an excerpt, establish canonical revisions, grant a source
license, or promote a pending relation.

All public quotation text is **withheld by default**: `evidence.text=null`,
`text_sha256` and `text_char_count` retain bounded diagnostics, and
`excerpt_status=withheld_pending_source_permission` explains the omission.
Unavailable quotes have null hash/count and `excerpt_status=unavailable`.
This applies to raw legacy proposals, stored annotations and unassigned mentions.
There is no public opt-in until an explicit source disclosure policy exists.
Raw extraction evidence remains governed by its existing ingestion/audit access
policy; source-active status is not redistribution permission.

## Bounds and compatibility

- At most 1,000 records are assessed, with at most 12 typed claims per record.
- A quotation is at most 800 characters; values are at most 160 characters.
- Up to 30 proposals and 20 document mentions are displayed publicly.
- Invalid inputs and assessment limits produce explicit incompleteness; display
  truncation is reported separately and does not manufacture completeness.
- Original input and stored reviewer/private metadata are not copied wholesale
  into this public contract. It is not a general free-text PII detector.
- All three flat structural aliases remain null until an authoritative reviewed
  relation workflow is implemented. The writer clears only these rebuildable
  aliases after legacy overrides; raw records and stored override decisions stay
  intact. Other atomic measurements, including lattice components, are unchanged.
- Structure-phase filtering cannot claim a valid relation by querying an old
  material-wide label. Public integration must expose the unavailable capability
  explicitly rather than return misleading matches.

## Validation and remaining scientific gate

Synthetic tests cover two materials/one phase, pressure-state changes, unresolved
sample/doping links, cited/negative/tentative text, repeated/missing quotations,
typed-channel conflicts, old broadcast labels, forged IDs/approval/source spans,
source holds, bounded context, byte parity, raw preservation and idempotence.
They do not measure corpus prevalence, association precision, recall, or review
time. No real source corpus has been re-extracted or backfilled by this change.

SC11 remains subject to the ML08 reviewed pilot: permitted source revisions,
real state/structure association outcomes, second-review disagreements, failure
and missingness accounting, and curator effort must still be recorded. This
pending-first implementation intentionally cannot satisfy an accepted-relation
or coordinate-artifact workflow by itself.
