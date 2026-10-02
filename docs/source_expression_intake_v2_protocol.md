# Private source-expression intake v2

This additive 0083 namespace accepts newly captured primary-source fragments.
It retains exact UTF-8 bytes and closed typed expressions privately. It does
not alter 0082/v1, either original public snapshot, material records, source
holds, sample/state associations, scientific approval or publication rights.

`SOURCE_PROPERTY_PENDING_ENABLED` remains false by default and gates both
namespaces. Existing JWT/browser-session authentication and current explicit
curator grants authorize previews/commits; current curator or reviewer grants
authorize reads. No account or grant is created. All errors and responses are
`private, no-store`. Requests fetch no URL and execute no XML/source instructions.

## Closed input

`POST /v1/research/source-expressions/imports/preview` accepts only
`{request_key, package}`. Commit adds `expected_preview_sha256`. Package keys:

```text
version: source-expression-package/2.0.0
source: {
  source_id, url, kind, content_kind, revision, revision_status,
  original_parent_sha256, parent_hash_status, rights_status, currentness,
  captured_at
}
source_text_base64: canonical base64 of 1–131072 exact UTF-8 bytes
source_content_sha256: SHA256 of those bytes
expressions: 1–20 closed entries
```

The retained canonical package (without the base64 fragment) is limited to
131072 UTF-8 bytes; each canonical typed projection is limited to 32768 bytes.
These bounds are checked before any SQL operation and supplied in capabilities.
The timestamp is a timezone-qualified ISO date/time declaration with seconds.

Kinds are primary_paper/conference_presentation/supplement/crystal_reference;
content is plain_text/xml_text. Version and parent-hash statuses are declared
or unresolved, paired with their nullable value. Rights are unresolved,
declared_private_inspection or restricted. Currentness is unresolved,
declared_current or historical. These are caller declarations, not server
verification of publication, parent file or source rights. Only retained
fragment integrity and exact expression spans are verified by this interface.
Private retention does not authorize public redistribution.

An entry has exactly these keys:

```text
field_id
subject: {formula_spans, sample_label_spans}
window: {id, label_spans}
source_role
knowledge_origin: Observed | Computed | unknown
origin_basis: {statement, spans}
model_spans
value_spans
unit_spans
conditions: [{field_id, role, value_spans, unit_spans}]
locator: {page, slide, table, row, column, section, member}
predecessor: null | {revision_id, record_sha256, revision_number}
```

Each span is `{start,end,sha256}` with a zero-based half-open interval in
Unicode codepoints of the UTF-8-decoded retained fragment. Its SHA hashes that
substring's UTF-8 bytes. A maximum of eight exact spans are concatenated in
declared order, supporting split formula XML text runs without executing XML.
All span lists are ordered and do not overlap. Scalar, statement and condition
values require one contiguous original span; their unit permits at most one
span. Formula assembly is explicitly declared, not physical identity. Empty
optional spans mean not supplied in this expression, not absent from the paper.
Adjacent token checks prevent partial numbers, omitted signs/bounds/uncertainty
and partial prefixed units from receiving a normalized scalar. Their selected
raw text stays available with a requires-review status. Bounded adjacent
`t`/`r`/`rPr` text-run tags retain neighboring signs and unit prefixes; paragraph,
cell and other tag boundaries establish no inferred association. This is not a
general markup interpreter.

Capabilities supply the finite field registry: temperatures, pressure, field,
Hc2, London penetration depth, electron–phonon lambda, omega-log, mu-star,
three lattice lengths, and source method/sample/structure/classification
statements. A small versioned scalar grammar supports finite decimals and
symmetric uncertainty. Unsupported syntax and units preserve the raw source
and require interpretation; missing units never use field defaults. Origins
remain declared source interpretations with a separate basis. Conditions
distinguish reported-result, study-extent, synthesis and fit-window roles.
London penetration depth never becomes electron–phonon lambda; pressure study
extent never becomes a Tc condition.

## Append and read semantics

The server derives normalized values and an expression identity from source ID,
field, exact subject, source window, source role and model. Distinct windows or
models stay separate; numerical differences do not automatically create a
scientific conflict. A successor must pin the current preceding revision's
ID, record SHA and number and preserve that identity. Old revisions remain
immutable; this does not revise a canonical scientific property.

Three tables retain private captures, operation receipts and expression
revisions. A SERIALIZABLE operation binds current actor/grant/session and
rehearses actual SQL within a rollback savepoint. Commit requires its exact
preview. Deferred SQL inventory checks require every expression to be appended
atomically. PostgreSQL independently reconstructs spans, values, units and
closed projection, and validates current-head succession. UPDATE/DELETE/
TRUNCATE and nonempty downgrade are refused. Timeout means unknown outcome;
recover with the original actor/key/request SHA through GET, never infer failure.

`GET /capabilities` returns versions, actor/session, curator grant and bounds.
`GET /imports/outcome` uses request_key and expected_request_sha256.
`GET /captures` supports offset/limit/declared currentness; `/captures/{id}`
returns fragment hashes and declared source scopes, not retained full text.
`GET /expressions` lists current expression heads with bounded pagination and
source_id/field_id/currentness filters; `/expressions/{revision_id}` returns an
exact historical revision and its head status. Details carry exact canonical
revision, projection, receipt, package, request and preview bodies, binding the
entry index/hash to its original package without JS floating-point reserialization.
Lists omit the full receipt proof; inspect a detail for its complete binding.
Each canonical revision pins its immutable import receipt's record SHA, so an
original revision digest also anchors the original source declarations. The
receipt manifest omits that receipt SHA to avoid a circular hash. Expression
pages have a maximum/default of eight heads to keep full canonical projection
proofs within the private response byte bound; capture pages remain at 25/50.
Latest retained capture in this
ledger is distinct from current publication verification; every response keeps
that distinction. Listing counts are expressions/fragments, not experiments.

All records remain pending, sample/phase/result associations unestablished,
scientific_acceptance false and canonical_promotions zero. The private API
does not add its content to public distribution or ML allowlists. A later
source-fidelity note or association adapter is separate from this intake.

Canonical request/preview/projection hashes use the existing compact sorted
UTF-8 JSON canonicalizer. Request SHA binds version and package SHA; package
SHA binds source metadata, fragment SHA and complete expression requests.
Preview additionally binds the original key, actor/grant/session and exact
successor manifest. Responses separately identify dry_run, replayed and
pending_ledger_written; declarations never imply runtime writes did not occur.
