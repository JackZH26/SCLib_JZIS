# Reported Tc Timeline: result and chronology contract

Contract: `timeline-result/1.0.0` (SC06, 2026-09-06).

This document specifies the pure occurrence extraction contract implemented by
`api/services/timeline_points.py`. Both the materialized projection and the live
JSONB fallback must use that extractor. It is not a scientific adjudication,
training-dataset release, canonical result registry, or complete discovery history.

## Identity: preserve evidence, do not deduplicate chart coordinates

The former year / rounded Tc / rounded pressure bucket is removed. Equal or nearby
numbers do not establish result identity. Different papers, samples, material
states, Tc criteria, source locations, reported versions, and result revisions
remain separate occurrences. The chart may group overlapping marks visually,
but must not discard their membership or source counts.

Each point has a stable SHA-256 `id`. Its identity input consists of the contract
version, material scope, supplied result ID/revision when present, a canonical raw
occurrence-content fingerprint, and the resolved chronology. Raw JSON key order,
input array order, numerical display rounding, current time, classification output,
visibility decisions, and database update timestamps are not identity inputs.
Eligibility can still change with the evaluation year and governance policy;
unchanged surviving occurrences keep their IDs.

When a bounded `result_id` is supplied, it is retained. A supplied
`result_revision`, or the legacy `revision` alias, is retained without creating a
revision number when absent. The basis is `result_revision_content`: it means
the supplied identity plus its occurrence content, **not** that this function has
verified the identifier against an adjudicated registry. Conflicting content under
the same supplied ID/revision is retained as separate points and marked with
`identity_conflict=true` and
`supplied_result_revision_has_conflicting_occurrences`. Those warnings describe
the current material extraction set, not a global registry-wide conflict audit.

Without a usable supplied ID, `result_id` is
`legacy-timeline-result:<sha256>` and the basis is `legacy_occurrence_content`.
The transitional ID is material-scoped. It is not an independently verified work,
sample, experimental replication, or source-result identifier. Any non-derived raw
content change creates a different transitional occurrence; this deliberately
prefers retaining possible duplicates over losing independent evidence.

Only exactly matching canonical occurrence content and resolved chronology can
consolidate. The survivor has an `occurrence_count`; no arbitrary first record is
selected to represent differing evidence. Repeated identical occurrences do not
constitute independent experimental replication. Sorting uses year, descending
unrounded Tc, then point ID, so equal-coordinate ordering is deterministic.

Fingerprint exclusions are applied recursively to known derived envelopes
(`result_classification`, `pressure_semantics`, `property_evidence`,
`anomaly_review`, `visibility`, `result_metadata`, `occurrence_count`) and known
governance-only fields (`review_status`, `review_reason`, `reviewed_at`,
`reviewed_by`, `admin_decision`, `review_metadata`, `needs_review`,
`scientific_acceptance`, `retracted`, `disputed`, `corrected`, `source_status`,
`validity_status`, and reviewer/curator/private-review/internal-review key
prefixes). These omissions do not waive any visibility policy. Other original
scientific/source content stays in the fingerprint. The raw source record is
never modified. This local identity contract does not silently replace the
already-versioned identity contract of other exports or property evidence.

## Chronology: a plotted year is not necessarily a measurement or discovery year

The extractor resolves chronology in this order:

1. `measurement_year`, then `measurement_date`;
2. `report_year`, then `report_date`;
3. legacy `year`;
4. a reported bibliographic publication date;
5. a reported bibliographic submission date;
6. the legacy integer `paper_years` value, when supplied by an older caller.

An explicit year must be an integer or an ASCII four-digit string. Boolean,
floating-point, fractional, nonfinite, and malformed years are not coerced.
An invalid explicit chronology field causes that occurrence to be omitted, even
if a valid bibliographic fallback exists. Date fields accept an ISO calendar date
or timestamp; a year-only string does not become an invented January 1 date.
The existing operational display window remains 1900 through the evaluation
year plus one. This window is not evidence of a verified discovery date.

Valid but disagreeing explicit fields retain the stated precedence and add
`chronology_fields_disagree`. The raw alternatives remain available in the
source material archive. Generic `year` has basis
`legacy_record_year_unspecified`, not "measurement", "discovery", or "report".
An explicitly supported `year_basis` can supply a source-asserted measurement,
report, publication, or submission basis; unknown assertions generate a warning
and do not upgrade the legacy basis.

Bibliographic source context is fetched for every referenced paper, even when a
record already has a year. The source-date preference is the occurrence's
`date_published`/`publication_date`, current paper `date_published`, occurrence
`date_submitted`/`submission_date`, and current paper `date_submitted`.
Publication and submission are distinct events, so their dates need not match.
Disagreeing assertions of the selected kind generate
`source_date_assertions_disagree`. Invalid source dates are warned about and a
valid documented fallback may be used. Missing dates do not fall back to
`updated_at`: an ingestion/edit time is not a scientific event date.

Axis-year bases are `explicit_measurement_year`, `explicit_measurement_date`,
`explicit_report_year`, `explicit_report_date`,
`legacy_record_year_unspecified`, `source_publication_year`,
`source_submission_year`, `source_publication_date`, `source_submission_date`,
or `legacy_source_year`. A legacy integer source year carries no more specific
event assertion. `source_date` and `source_date_basis` describe the independent
bibliographic context and can therefore differ from the selected axis year.
`source_version` is populated only from an explicitly reported bounded version;
neither publication dates nor database timestamps are invented as version IDs.

## Point metadata and public bounds

`result_metadata` contains:

| Field | Interpretation |
| --- | --- |
| `version` | Result/chronology contract version. |
| `result_id`, `result_revision` | Supplied or transitional identity; absent revision remains null. |
| `identity_basis` | Supplied-ID/content or transitional legacy-content basis. |
| `identity_conflict`, `identity_warnings` | Current extraction-set collisions under a supplied ID/revision. |
| `year_basis`, `chronology_warnings` | What the plotted year asserts and unresolved chronology warnings. |
| `source_date`, `source_date_basis`, `source_version` | Available bibliographic context; missing values stay unknown/null. |
| `state` | Bounded identifiers and explicitly reported sample/state descriptors from this occurrence only. |
| `tc_criterion` | Bounded original `tc_criterion` or `tc_type`; otherwise `unknown`. |
| `source_locator` | Allowlisted page/table/figure/row/column/section/chunk/span coordinates. |
| `occurrence_count` | Count of exactly matching occurrences, not independent replications. |
| `review_status` | Always `legacy_unreviewed` for this legacy read path. |

State and locator dictionaries do not copy arbitrary nested source dictionaries,
reviewer profiles, evidence quotations, or long source prose. Oversize identifiers
are omitted rather than truncated into another identifier. Numeric state values
must be finite. Identity hashing can use original source content without exposing
that content through these public metadata fields. Existing source disclosure and
licensing policies remain separate requirements; this is not a general free-text
PII sanitizer. The legacy pressure metadata locator is also projected onto the
same bounded allowlist.

`review_status` is never inferred from source genre, numerical plausibility,
"Observed" classification, lack of anomaly findings, catalogue eligibility, or
stored reviewer/admin labels. The result can be browsable without being accepted
or suitable for ML training. A reviewed-only control must remain unavailable until
an actual reviewed-result path exists.

## Numeric safety and governance remain independent

Tc must be a finite, strictly positive, exact parsed scalar with no parser error,
approximation flag, unresolved uncertainty, or bound/range substitution. There is
no display-rounding threshold: 0.03 K and 0.031 K remain distinct exact values.
The established per-field anomaly and pressure contracts still apply. Unknown
pressure is not ambient pressure; the result-origin classifier remains independent
of pressure and source genre.

Malformed occurrence containers, individual non-record entries, nonfinite input,
malformed scientific notation, unsupported non-JSON objects, and excessively nested
content are omitted individually by the pure extractor. Their raw values remain in
the archive; extraction does not delete, repair, approve, or write data back. A
bad occurrence cannot crash extraction of a good sibling.

SC07 live parent/source/material visibility remains a mandatory caller-side gate.
It can conservatively hold an entire material when one occurrence requires review,
so successful per-record parsing does not force publication of a sibling point.
Archive inclusion must not bypass provenance quarantine or numeric anomaly gates.
Sampling, full-population summaries, cache freshness, and visual overlap handling
are separate layers and must not redefine scientific occurrence identity.

## Regression coverage

`api/tests/test_timeline_identity.py` covers close/equal values across papers,
samples, states and onset/zero criteria; permutation and source-filter order;
exact duplicates and conflicting supplied identities; unrounded low Tc; date
bases and conflicts; source versions and update timestamps; malformed/nonfinite
inputs; bounded public metadata; and preservation of the original raw records.
Tests run only through the capability-checked disposable PostgreSQL/Redis runner.
