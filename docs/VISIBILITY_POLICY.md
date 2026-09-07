# Material visibility policy

Version: `material-visibility/1.0.0` (SC07, local implementation, 2026-09-06).

This is a read policy, not a scientific approval workflow, source-license grant,
claim correction, calibrated reliability score, or ML-training admission rule.
`catalogue` means eligible for the default public read view under the currently
available governance inputs. It must never be presented as “verified.” Every DTO
therefore includes `scientific_acceptance: false`, even when eligible.

## Authoritative inputs and boundaries

`api/services/material_visibility.py` is pure: it does not query a database,
modify records, contact a service, consult the clock, or persist its output.
`visibility_for_material(material, *, anomaly_review, source_statuses,
parent_visibility, ancestry_error)` accepts a material-like mapping or object. Its caller must
resolve current data before calling it:

- Material `needs_review`, `disputed`, `retracted`, `status`, and an explicit
  `provenance_quarantine*` review-reason prefix govern visibility.
- `anomaly_review` must be freshly calculated using the current anomaly policy,
  not copied from a stored/incoming response. Missing, malformed, contradictory,
  or unsupported assessments hold the default view. “No findings” is not approval.
- `source_statuses` is a mapping of relevant paper IDs to current authoritative
  publication statuses, or a sequence of those statuses. Missing source lookups
  must be supplied as `None`. An empty/absent lookup is unknown, never active.
  Raw NER record flags and source prose do not establish publication status.
- `parent_visibility` must be a separately resolved current parent DTO. A child
  with a parent ID but no valid parent DTO is held. Callers must detect cycles and
  unresolved ancestors and fail closed instead of recursively trusting stored
  visibility. Missing, cyclic and depth-exhausted chains make **public Archive
  access unavailable**, not merely catalogue-ineligible: an unresolved ancestor
  could contain a provenance restriction. `ancestry_error` is an internal signal
  from this resolver, never a source-supplied permission flag. Parent holds are
  transitive when callers resolve ancestors first.

Explicit negative governance in retained records also imposes a conservative
whole-material hold: `needs_review`, `disputed`, `retracted`, `corrected`, and
recognized negative `status`, `review_status`, `source_status` or `validity_status`
tokens. An occurrence marked retracted does **not** establish that the entire
material is retracted or that the authoritative paper lifecycle is retracted;
it produces `pending` with a specific record-level reason. Positive raw
`reviewed`/`approved` labels cannot cancel a hold or confer acceptance. Explicit
record provenance quarantine blocks all material read views. A bounded
record-governance scan that cannot inspect all records closes public Archive
access instead of ignoring potentially restricted later records. More precise
claim-dependency adjudication belongs to SC08.

Stored `visibility`, stored anomaly summaries, `admin_decision`, raw `reviewed`
flags, and alleged acceptance fields are ignored. A nonempty historical
`review_reason` with `needs_review: false` does not itself hold a material unless
it has the explicit quarantine prefix. Legacy categorical notes are not proof of
a current scientific anomaly or a scientific approval. An unspecified legacy
material status adds a warning without inventing acceptance; an explicit
unrecognized status, including a free-form `approved` or `accepted`, is held.

No automated evidence-matching or correction/retraction propagation is added by
this pure policy. The caller can only evaluate the sources it actually resolves.
Historical missing links, source lifecycle synchronization, stale extraction
refreshes, and revision-bound scientific approvals remain separate work (SC08).

## Policy matrix

Precedence is quarantine, retracted, disputed, corrected, pending, unknown, then
catalogue. Every applicable reason is retained, even when a stronger state wins.

| Governing condition | State | Default catalogue | Explicit Archive |
| --- | --- | --- | --- |
| Active/unspecified legacy status; current anomaly clear; no hold | `catalogue` | Yes | Yes |
| Material `needs_review` or current anomaly finding | `pending` | No | Yes, with warning |
| Material disputed or authoritative source disputed | `disputed` | No | Yes, with warning |
| Material or linked source corrected | `corrected` | No | Yes, with warning |
| Material retracted, or all supplied sources retracted/withdrawn | `retracted` | No | Yes, with warning |
| Active and retracted sources mixed | `pending` | No | Yes, with warning |
| Unknown explicit material status / missing current anomaly / malformed input | `unknown` | No | Yes, with warning |
| Parent held from catalogue | `pending` or stronger own state | No | Yes, with warning |
| Explicit negative retained-record governance | `pending` or stronger own state | No | Yes, with warning |
| Missing/unresolved/cyclic/depth-exhausted parent provenance | `unknown` or stronger own state | No | No |
| Record-governance scan budget exhausted | `unknown` or stronger own state | No | No |
| Material/ancestor provenance quarantine | `quarantined` | No | No |

Archive access remains subject to authentication, authorization, licensing, and
endpoint-specific retention policies outside this function. `archive_available`
does not authorize disclosure of full text, source quotations, or private review
data. It only means this visibility policy does not prohibit an otherwise
authorized Archive response. An Archive flag cannot bypass provenance quarantine.

Current source status is summarized independently as `active`, `corrected`,
`retracted`, `mixed`, or `unknown`. `published` normalizes to `active`;
`withdrawn` is held with `retracted` for eligibility only, not asserted to be the
same bibliographic event. Authoritative `disputed` creates a dispute hold while
the lifecycle summary remains unknown. Unknown source status creates an explicit
warning but does not, by itself, revoke compatibility catalogue eligibility or
pretend that the source has been checked. A mixture of known and unknown statuses
is `mixed` with a source-status-incomplete warning.

## Public DTO and privacy

The DTO contains only the policy version, state, catalogue/Archive booleans,
`scientific_acceptance: false`, fixed `reason_codes` / `warning_codes`, matching
fixed English `reason_messages` / `warning_messages`, source-status summary, and
`review_revision`. It does not copy arbitrary review reasons, user names, email
addresses, reviewer identifiers, admin notes, source text, evidence locators, or
raw source/status strings into public reasons.

`safe_public_review_reason(dto)` reconstructs bounded compatibility prose from
recognized reason codes. It never trusts supplied messages. Response models
must still allowlist their own material fields: this helper is not a generic
sanitizer for nested material records. Raw record access needs its own scientific
allowlist and existing provenance/rights checks.

`sanitize_review_metadata(value)` is a separate recursive, non-mutating public
projection that removes known private review containers and keys (including
reviewer/curator fields, raw review reasons/notes, admin decisions, and bare
name/email identity keys). It preserves other scientific/raw fields subject to
depth and node limits, emits explicit limit markers, and does not attempt to
detect private information embedded in arbitrary prose. Derive result IDs from
the untouched raw source before applying this projection. This is not a full
text-disclosure, licensing or general PII policy.

`review_revision` is a deterministic SHA-256 fingerprint over this version,
material identity/update timestamp, governing status/flags, public reason/warning codes, anomaly policy/evaluation
year/counts/rule counts, authoritative source identity/status pairs, and parent
revision/state. Private prose is neither copied nor hashed into this fingerprint;
changing a private note alone does not change read eligibility. Source-map order
does not affect the fingerprint. This fingerprint is **not** a content hash of
every scientific record, a signed approval, or an immutable scientific revision.
Caches need the visibility version plus current governing-input invalidation;
the fingerprint alone cannot refresh a stale database/source lookup.

The read adapter resolves at most 32 parent edges and checks each requested
material's chain independently before constructing parent-derived revisions.
Cycles do not use partially resolved parent fingerprints, so requesting the same
cycle from another node or in a different batch order produces the same per-node
visibility revision. Preloading extra ancestors does not relax the depth limit.
Ancestry errors use explicit fixed reasons, not fabricated scientific retractions
or claims that a specific unknown source is quarantined. Both source and parent
SQL lookup batches are limited to 1,000 identifiers.

## Required read-surface integration

Callers must use one resolver to obtain current inputs, then apply
`visibility_allows_view(dto, include_archive=False)` after any SQL prefilter.
A SQL `needs_review = false` predicate is insufficient: a newly recomputed
anomaly, linked source change, dispute, or ancestor hold may invalidate it.

- Lists, default variants, Timeline and specialized scientific subqueries use
  catalogue eligibility, including the parent's policy.
- Direct material detail can return Archive-held rows with the same DTO and an
  unmistakable English Archive warning, not a verified-looking scientific page.
- Explicit Archive variants/downloads need their own intentional mode; no such
  flag can reintroduce quarantined rows.
- Search and paper source occurrences remain distinct from a material catalogue
  row. Only explicit source/material links may apply material holds; no formula
  matching may manufacture identity or approval.
- Structured metadata must not expose Archive-only scientific claims as eligible
  results. Quarantine must apply to direct routes, subqueries, cached variants,
  downloads and JSON-LD, not only the top-level list.

The policy-matrix tests in `api/tests/test_material_visibility.py` cover active,
pending, disputed, corrected, retracted, mixed-source, unknown and quarantined
fixtures, fresh-anomaly enforcement, parent inheritance, deterministic revisions,
private-note exclusion and non-mutation. Run API tests only through the guarded
disposable PostgreSQL/Redis runner. Route, export, Timeline and frontend coverage
must separately verify actual endpoint wiring; pure policy tests are not evidence
that all production surfaces use the policy.
