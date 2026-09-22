# Result-origin contract — SC05

Status: implemented locally for review; not a scientific adjudication or a production backfill.

## Independent axes

`classify_result(record)` returns a versioned envelope with:

- `knowledge_origin`: Observed, Computed, Inferred, AI-Proposed or Unknown.
- `classification_status`: resolved, unknown or conflicted.
- `source_role`: primary, cited, unknown or conflicted.
- Deterministic reason codes and `classifier_version=sclib-result-origin/v1`.

Only explicit result-level labels and allowlisted result methods supply origin.
Pressure, paper genre, source tier, citation count, review state and extractor
identity do not. A legacy primary_experimental/primary_theoretical value maps
both axes; bare primary/cited maps only role. Missing information stays Unknown.
Conflicting explicit result signals are not silently resolved by precedence.
Paper-type-only legacy records, including computational papers, remain Unknown
until their individual result evidence is recoverable.

An LLM-extracted measurement may remain Observed; an explicit AI-generated
hypothesis is AI-Proposed. These are not the same operation. Observed does not
establish bulk superconductivity, a valid Tc criterion, independent replication,
approval or applicability at another state. Cited experimental evidence remains
Observed + cited rather than being promoted into a primary result.

## One policy, independent deployments

Canonical source is `ingestion/ingestion/result_semantics.py`; the API's
`services/result_semantics.py` vendors identical bytes because the Docker build
contexts are independent. Edit both together. API and ingestion tests enforce
byte parity and the same 15-case golden fixture in
`docs/schemas/result-origin-v1.golden.json`. This avoids coupling the API runtime
to the ingestion package or silently maintaining two classifiers.

The API classifies material records, paper records and search metadata on read.
Ask receives only a bounded formula/classification projection, not arbitrary
nested raw/provenance payloads. The claim mapper exports both axes in
`extraction_metadata.result_classification`; the v1 combined evidence_role enum
is only a conservative compatibility representation. A method alone does not
establish primary authorship. Classification conflicts cannot remain accepted
through this mapper.

Material list/detail summaries check the origin support for stored experimental/
theoretical split values; unsupported legacy split values are hidden rather than
mislabelled or recomputed as a new maximum. This does not replace the later atomic
result/state selection and review policies in SC02/SC03/SC07.

## Source identity and immutable evidence

Classification annotations are not persisted into raw material records during
normalization/aggregation. API envelopes are derived presentation metadata.
The reserved top-level `result_classification` envelope is excluded from the
existing v1 source-record identity hash so an API export round trip does not mint
a new occurrence. Existing unannotated v1 hashes are unchanged; real raw scientific
field changes still change identity. The raw payload itself is retained.

The mapper version is now `legacy-material-record/v1.2`. Origin/status/role and
classifier version participate in semantic fingerprints. Existing interpretations
or released snapshots must not be overwritten: run the offline impact/parity
plan and the future revision-aware loader before any production application.

## Timeline compatibility

Migration `0046_result_origin` adds four point fields and a classifier-version
readiness field; it changes no original scientific result. It invalidates the old
Boolean-only projection so fallback can serve until a transactional rebuild.
Readiness is bound to projection schema, classifier version and source year.
A classifier-version change requires a rebuild, not a ready but partial result.

`experimental_only` means resolved Observed and a non-conflicting source role;
it is not `not is_theoretical`. The Boolean remains for old clients but False
does not imply an observation. Updated clients show explicit origin/role/conflict
text and distinct marks. Cache keys include classifier version. Backend and
frontend must be rolled out together; do not enable the new refresher before the
new columns exist.

The broader Timeline record-identity, date-basis, visual clustering and sampling
work remains SC06. This change only prevents different classification states from
collapsing together; it does not claim that all legacy points are independent
results or that the existing numerical/date policy has been fully redesigned.

## UI and remaining limits

Source tier is labelled as source tier, not experimental confirmation. Reported
conditions are not universally called measured conditions. Small temperatures
are displayed without forcing 0.001 K into 0.0 K. All new UI copy is English.

Classification is deterministic legacy interpretation, not a learned classifier,
curator approval, quantitative extraction-quality estimate or a complete RAG
support validator. Unknown pressure, same-result filtering, atomic aggregation,
review visibility and retraction propagation remain separately tracked work.
