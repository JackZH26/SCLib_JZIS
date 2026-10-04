# Private calculation returns

This implements the durable return part of Discovery's
**hypothesis → calculation → observation → next decision** workflow. The API
retains original QE files associated by their owner with an exact saved research
question. It does not infer that a file describes the intended physical sample,
that a job actually ran on an authenticated machine, or that a material is stable
or superconducting.

Version: `discovery-calculation-return/1.0.0`. Migration:
`0090_discovery_calculations`. Default setting:
`DISCOVERY_CALCULATIONS_ENABLED=false`. No production import is part of this
change. The browser's QE preparation/reading tools remain local tools until the
new private API is connected to them.

## Research and scientific scope

The saved design must belong to the current explicit curator, remain the latest
revision, not be withdrawn, and declare a `calculation` next action. All three
existing baseline kinds are supported: unanchored research hypotheses, retained
results, and native properties. Catalogue-linked baselines also retain the
existing current source/governance checks. A host label or matching formula
never establishes a structural or physical association.

An owner supplies findings, a `continue` / `stop` / `redirect` decision, a reason,
and unresolved questions. These are researcher notes. The request explicitly
declares `association: researcher_linked_unverified`. Native energy, convergence,
forces, stress and geometry are read by the independent Python PWSCF parser;
uploaded JSON readings or scientific authority flags are rejected.

An SCF energy is `Hartree/cell` for the declared numerical calculation. It is not
formation energy, hull distance, a 300 K free energy or an inferred Tc. A zero
step initialization has no physical observations. An output's convergence claim
does not establish basis/k-point convergence, phonon stability or experimental
validation. See [the parser's supported scope](discovery_qe_server_preflight.md).

## Transport and workflow

Prefix: `/v1/research/discovery-calculations`. All routes require current curator
access and use private, no-store responses. Browser session CSRF rules apply.

| Route | Purpose |
| --- | --- |
| `GET /capabilities` | Supported parser, roles and byte/count limits |
| `GET /designs/{design_id}/context` | Exact current design/action pin and eligibility |
| `POST /operations/preview` | Parse native files and rehearse an atomic save, then roll it back |
| `POST /operations/commit` | Save exactly the reviewed preview |
| `GET /operations/outcome` | Resolve an uncertain save by request key and request SHA-256 |
| `GET /designs/{design_id}/returns` | Paginated private receipt/decision history |
| `GET /returns/{return_id}` | Reconstruct the report from retained original files |
| `GET /returns/{return_id}/files/{ordinal}` | Download exact original bytes after current access and replay checks |

Preview body: `{request, files_base64}`. Commit adds
`expected_preview_sha256`. The closed request contains:

```text
version: discovery-calculation-operation/1.0.0
request_key: owner-scoped idempotency key
design: {design_id, revision_id, record_sha256, next_action_sha256}
files: [{role, name, sha256, size_bytes}, ...]
association: researcher_linked_unverified
findings, decision, reason, unknowns
```

Inventory order is ascending `(role, name)`, using ASCII logical filenames.
`files_base64` has the exact same order. There is one `input`, one `xml`, one
`stdout`, and one to eight `upf` files. No path or URL is opened or fetched.
Metadata is at most 32 KiB. Input is at most 1 MiB, each other file at most 8 MiB,
and the package at most 81 MiB. The uncompressed JSON body is at most 109 MiB
(including base64 expansion), with an eight-second body deadline. These are
operational limits, not statements about scientific adequacy.

Authentication runs before body consumption and its database connection closes
before upload/parse. The writer checks the same live actor/grant/session again.
There is one upload and one native parsing worker per API process. A cancelled
or timed-out request does not release the worker's capacity until its thread
actually finishes. The shared private-route deadline and admission limit also
apply. An enabled deployment must configure its reverse proxy's request size,
process count, memory and private-file retention budget explicitly; default-off
is not evidence that any production deployment has this capacity configured.

A fresh preview includes `report`, its exact `report_canonical_json`, and the
report digest in the receipt. The write response contains custody proof, not
scientific approval. An identical retry returns the original receipt. Changed
bytes or metadata under the same key conflict. After an uncertain HTTP outcome,
query the original key/digest before creating another submission.

## Durable integrity

`discovery_calculation_returns_v1` stores the closed request, design pin, parser
version, report digest and canonical preview/receipt. It stores no parsed
scientific quantity. `discovery_calculation_files_v1` stores every original byte
with its inventory ordinal. Both tables are append-only. SQL independently
checks owner, grant/session, current design/action/source pin, metadata shape,
byte counts and hashes. A deferred inventory constraint forbids a committed
parent with missing files. Preview checks that constraint before rolling back.
Migration downgrade refuses to discard a populated ledger.

SQL does **not** parse PWSCF physics. On detail/download, the API reconstructs the
report from all saved bytes and verifies its digest. A well-formed but fabricated
SQL report digest cannot produce a report. Integrity failure returns unavailable
with no partial values. A changed/withdrawn plan or held source preserves private
receipt history but withholds native readings and file downloads. Reads recheck
current role/source state and the design after potentially slow native parsing.

## Remaining user workflow

Connect the existing saved-plan and QE panels to preview/commit/outcome/history,
then independently replay downloaded bytes in the browser. The UI must show
the saved research question, execution status, numerical convergence, original
file links and next decision without repeating technical policy prose in every
row. It must separately verify candidate/source-coordinate construction;
current file custody does not establish that association. Authenticated runner
receipts, scientific adjudication, Materials field promotion and ML admission
remain separate unfinished work.

## Validation scope

Owned PostgreSQL and HTTP tests exercise preview rollback, actual commit,
idempotent recovery, original-file equality, native reconstruction, owner
isolation, role/session change, design revision/withdrawal, source holds,
append-only guards, deferred inventory rejection, forged report digests and
populated downgrade refusal. Native XML/stdout are earlier QE captures;
repository UPF fixtures are explicitly synthetic headers. These tests establish
software behavior, not scientific certification.
