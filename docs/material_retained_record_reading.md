# Retained record fields and field-coverage reading

This change exposes existing catalogue extraction fields in the material detail
Evidence table and makes the verified field-coverage report inspectable per
record. It adds no API, database table, scientific dictionary field, source
import, review decision or sample/state/run association.

## Actual reader gap and bounded evidence

A read-only inspection of the frozen October 4 actual200 capture found 200
material detail DTOs and 367 retained records. Of these records, 143 supplied a
nonempty `tc_type`: 101 onset, 28 midpoint and 14 zero-resistance, across 78
materials. Forty-eight supplied `hc2_tesla`. These are existing record fields,
not independently verified experiments or newly completed scientific facts.
The previous Evidence comparison table did not read the criterion fields or
Hc2. Selected-property disclosures remain a separate reading path.

The implemented API contract provides `MaterialRecordCoverage.records`: at most 32 inspected
records with result/source IDs, eligible inventory offset, record origin,
classification, field status and reasons. The previous coverage UI showed only
aggregate field counts. No new response or source-data snapshot is required.

## Tc and Hc2 mappings

`material-retained-record.ts` reads each row independently:

| Retained key | Display | Boundary |
| --- | --- | --- |
| `tc_type` | Retained Tc type | Coarse retained token, preserved verbatim |
| `tc_definition` | Retained Tc definition | Separate alias; does not replace another field |
| `tc_criterion` | Reported criterion | Original lexical token, not a normalized winner |
| `criterion` | Criterion alias | Separate token even when inconsistent with `tc_type` |
| `hc2_tesla` | Retained Hc2 | Finite scalar preserved without rounding; T is the API field unit |
| `hc2_tesla_unit` | Stored input unit | Separate source/input declaration; non-T or unknown unit is not relabeled T |
| `scientific_values.hc2_tesla.raw_value` | Stored source token | Preferred over a stale scalar or a stored normalized value; no parsing or conversion |
| proposal `input_unit` / `raw_unit` | Stored unit tokens | Kept separately; no guessing missing units |
| `hc2_conditions`, `hc2_direction`, `field_orientation`, `magnetic_field_orientation` | Hc2 field context | Same row only; missing context is not borrowed from Tc or a headline |

The unit T comes from the existing API scientific-value field registry, not
proof that T was printed in a source. An explicitly stored raw/proposal token is
rendered verbatim, without appending the API unit. Unsupported structured values,
nonfinite numbers, malformed proposals, control characters and oversized tokens
remain unavailable. An unresolved preserved proposal never falls back to a
possibly stale scalar. Explicit zero is preserved.

The Hc2 column appears only when at least one currently displayed, unrestricted
record supplies a readable Hc2 token. A material headline, a restricted row or
an unresolved proposal cannot create an otherwise empty column. Tc criteria
remain readable in every retained row regardless of the Hc2 column.

The table does not reinterpret Hc2 as Hc2(0), direct measurement, or a specific
probe. Shared record membership does not establish that Tc and Hc2 were measured
together. Existing record sorting, retained-row restrictions, anomaly disclosures,
selected properties, recovery eligibility and SEO are unchanged.

## Coverage disclosure

Each field's existing coverage cell adds a default-closed `Inspect … records`
disclosure. A focusable local-scroll table presents only rows in the verified
report: one-based eligible inventory position, exact result ID, linked source ID,
record origin/classification, field status and readable reason. Unknown reason
codes are explicitly unmapped; a missing reason is labeled unsupplied.

`record_offset` belongs to the eligible source pool. It is never treated as the
detail response's raw index, a sorted table index or a physical sample number.
There is no implicit link between these two tables. Unchecked records have only
the supplied aggregate count; their IDs/statuses are not fabricated. Empty or
old responses without per-record coverage do not acquire synthetic rows.
Internal source links use the existing AppLink/NextLink router, with encoded
source IDs and disabled prefetch, so the framework retains its deployment prefix.

The existing closed DTO validation, asynchronous SHA verification, material
switch/abort fence, authority checks, 32-record bound and aggregate counts remain
unchanged. No response, coverage hash, source/candidate identity or recovery
download content is reserialized or rewritten by these display helpers.

## Verification to run

Focused component tests cover parallel criteria, preserved Hc2 precision and
raw units, malformed proposal fallback refusal, zero, independent context,
equal-Tc row separation, restricted-row exclusion, closed coverage disclosures,
source/result IDs, missing/unknown reasons, unchecked inventory, immutable DTO
bytes, old/corrupt responses, over-budget refusal and omission of all-missing Hc2
columns. The source-link test models framework prefix handling to verify routing
delegation; the built application's real prefix routing still needs browser QA.

The subagent authored these tests without running tests, builds or services.
The root should run the focused suites and existing material property surfaces,
then verify the detail table and opened coverage disclosure at desktop and
320 px widths, keyboard focus, local scrolling and source navigation. These
engineering checks do not establish human scientific review or formal-property
completion. Additional formal fields need an explicit applicable registry,
quantity definition, units, method/condition scope and review rules. No specific
152-field registry or pending user approval was verified in this audit.

## Root execution and current public response

The six focused material suites passed 171 tests. The full branch passed 2,695
unit tests in 117 files, 46 source checks, TypeScript checking and a normal
production build from 284 byte-matched inputs. The prefix test verifies
AppLink/NextLink delegation; it does not claim a separate browser build with
a nonempty deployment prefix.

The actual current public `mat:caffe0.9co0.1as` DTO was captured between equal
version responses (`ab2760b`, dataset `v2026.09.03`, API `1`). Its 56,053 bytes
matched the earlier frozen sample exactly. The local production browser
displayed the one record's `tc_type=onset`, `hc2_tesla=102` and
`hc2_conditions="0 K, estimated by WHH formula"`, while the headline remained
23 K. The API unit and unavailable printed source unit were distinguished.
Desktop and 320 px had no outer overflow; the evidence table retained keyboard
focus and local horizontal scrolling. Hc2 context was closed initially and
opened successfully. This is reading of existing fields, not a new extraction
or independent confirmation of the reported result.

That public API version did not provide the new source-recovery response.
The browser truthfully showed the unavailable state and fabricated no
per-record coverage rows. New coverage rows, IDs, bounds, disclosure and routing
have component-level verification; live browser acceptance against a deployed
coverage response remains pending. The local build and screenshots do not
establish deployment of this change. Scientific acceptance, native physical
associations, formal-property completion and contracts for additional quantities
remain separate work. A remembered field count is not an approval requirement.
