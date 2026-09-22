# Thirty-eighth implementation batch: private answer-time evidence receipts

Date: 2026-09-09. Base commit: `56c7b35`.
Issue advanced: [RG03 / #69](https://github.com/JackZH26/SCLib_JZIS/issues/69).
Related contracts: RG02 typed evidence, RG01 scientific support, SC08 current
source warnings, EN01 isolated tests and EN02 explicit schema admission.
New additive head: `0068_answer_evidence`.

## Outcome and scientific boundary

New authenticated Ask answers now preserve final returned output and exact
selected references in an immutable, owner-private receipt. Ordinary, numerical,
mixed, clarification, empty and withheld paths share the same atomic save
boundary. Numerical and mixed history no longer replace actual returned values
and association dispositions with a request-summary placeholder.

This is final-output retention, **not** a complete provider-input archive,
deterministic regeneration, authentication of original scientific documents,
scientific acceptance, training approval or source redistribution permission.
The final question/result/source inventory is bounded and versioned. Removed
or withheld pre-generation references are not redisclosed by the receipt.
Missing pressure, detection limits and unknown token usage preserve their
existing scientific/operational meanings.

See the [operator and client contract](../../ANSWER_HISTORY_RECEIPTS.md) for
wire versions, resource limits, authorization, migration and retention details.

## Database and capture integrity

`answer_evidence_receipts` is a one-to-one child of a newly marked `ask_history`
row. Three SQL-canonical JSON texts retain request, response and bindings. Native
guards check their exact UTF-8 hashes, closed inventories, ordered citations and
extraction results, exact generation/activation/member identities and applicable
0060 evidence/extraction parents. A native aggregate record checksum binds the
history ID, version and reference/header hashes.

Actual selected input objects are detached and process-sealed before rollback
or provider work. Capture checks citation attribution and snippets against those
inputs and recomputes numerical projections from retained raw parents and the
request. A changed outgoing DTO cannot silently reuse untouched provenance.
Historical reading never reruns a later parser or follows the active pointer.
Promotion and mutable Chunk replacement do not replace old retained references.

The history marker is nullable for compatibility. Preexisting rows remain NULL,
byte-preserved and explicitly `legacy_unpinned`; in-place retrofit to v1 is
rejected. New marked parents cannot be updated or backdated. Deferred native
completeness requires the receipt at the real outer commit. UPDATE/rebinding,
standalone receipt DELETE and receipt-table TRUNCATE are rejected. Ordinary
owner deletion, account deletion and 90-day parent pruning still cascade: this
is not indefinite retention of private questions.

Frozen older migration definitions are unchanged. Historical empty-roundtrip
comparisons exclude only the independently asserted-empty new table and the
new nullable marker on AskHistory; every older column remains compared. Failed
downgrade snapshots stay complete and strict. The dedicated 0068 rehearsal
checks pre-upgrade legacy preservation, atomic completeness, outer rollback,
duplicate refusal, historical verification, owner cascade and populated
downgrade refusal after every independent older guard has already run.

## HTTP and interaction

The final save uses a fresh bounded UTC SERIALIZABLE transaction. It rechecks
the original JWT/cookie or API-key authorization without charging quota twice.
The answer remains usable if history cannot be saved. Success is reported only
after outer-commit acknowledgement. Lost acknowledgement returns `unknown`
with the original recovery ID, no checksum and no automatic duplicate write.
Cancellation and capacity exhaustion do not fabricate a successful save.

The list endpoint loads small receipt summaries, not large receipt bodies.
The new owner-only detail resolves authentication and private history in the
same bounded read-only REPEATABLE READ snapshot. Byte preflights precede
hydration. Cross-owner and missing IDs have identical 404 semantics apart from
their independent request IDs. Responses and errors are private/no-store;
API-key-only detail reads remain disallowed.

The English dashboard adds a receipt detail page and honest save/recovery
notices. It displays the actual saved structured/mixed data and historical
labels. Current metadata for citation source papers and numerical-result source
papers appears in two separate warnings; a new retraction changes only those
warnings, not stored values or their checksums. Current-paper links are not
presented as immutable document links. Strict parsers reject malformed or
cross-bound records; navigation aborts stale private responses.

Account exports explicitly include per-history receipt-access paths and explain
that complete receipts are fetched individually using owner authentication.
They do not silently embed up to 1 MiB of extra private payload per history row
in the existing account snapshot. Old records do not acquire invented payloads.

## Verification

All API and migration work used independently owned, capability-guarded native
PostgreSQL/Redis services. No inherited database, deployed service, embedding
provider, model provider, paid calculation or real source was used. Native
execution is not Linux final-image/remote CI equivalence or production rollout.

| Evidence | Result |
| --- | --- |
| Final integrated 16-module API regression | **401 passed**, 112.58 seconds; one existing FastAPI `regex` deprecation warning; owned cleanup completed |
| New actual HTTP save/read/privacy tests | **27 cases**, included in the integrated result |
| Dedicated service/native schema/preparation regression | **101 passed**, 19.57 seconds; overlaps the integrated API result |
| Native raw-SQL schema guard cases | **39 cases**, included above |
| Receipt service cases | **38 cases**, included above |
| Full scripts suite after final migration-source freeze | **1,200 passed + 36 subtests**, 20.72 seconds |
| Complete native migration/recovery rehearsal | **Passed**, 31.039 seconds; source `0050_timeline_identity` to `0068_answer_evidence`, existing retained-generation rollback and all independent ledger guards |
| Frontend full unit suite | **796 passed**, 32 files, 26.73 seconds; includes **85** focused history cases |
| Frontend source checks | **35 passed** |
| Actual SQL-to-HTTP-to-frontend artifacts | Five complete received JSON documents copied byte-for-byte: ordinary, structured, mixed, clarification and legacy; strict parsing and rendering passed |
| Desktop/mobile browser checks | **2 passed**, 18.0 seconds; actual captured mixed/legacy documents, no unexpected API/external requests, no horizontal overflow |
| TypeScript and scoped lint/whitespace | TypeScript clean; Ruff I/F passed for the new files and changed routers/services/tests/harness, db.py F-only passed; `git diff --check` passed |

The browser uses a dedicated local synthetic response interceptor, not a live
production backend. Its fixture documents came from the real authenticated
native HTTP save/read tests without reconstructing IDs or checksums. Screenshots
were inspected on desktop and mobile; the dedicated port was closed afterward.
This establishes client integration, not live-site deployment or scientific
correctness of synthetic 39 K data.

The exact successful [migration measurement receipt](measurements/RG03_Answer_History_Schema_2026-09-09-01.json)
is retained byte-for-byte, mode `0600`, with full-file SHA-256
`a2badb5ef509ef47c4acbd8223339cd78fba3a5e243c9f14b8d881cb4b5743d2`.
It records macOS arm64, CPython 3.12.14 and PostgreSQL 16.13, verified cleanup,
three unchanged legacy/source/release-pin retention checks, actual index rollback
and **562** executed source inputs. Its source-inventory checksum is
`e4f5fbf9324cb09023d6ea2d59329657d830b87c3907aad351e168168badd440`.
The report preserves the actual pre-commit head `56c7b35` and dirty-state flags;
it is not rewritten to claim a later commit existed during measurement. The
existing report's fixed fixture-outcome list is unchanged; new 0068 assertions
run in the pinned harness before success publication, not as invented extra
fields in an old measurement format. All authority flags remain false.

### Corrections during verification

The first five-module selection returned 124 passed and one test failure: it
compared the middleware's independent random request IDs as if two 404 requests
must have identical IDs. The assertion now compares the public error semantics
while preserving the middleware IDs. An initial broader selection also named
two nonexistent test modules and collected no tests; it is not counted as
verification evidence.

The next integrated selection returned 400 passed and one new fixture failure.
The question included “pairing,” so the existing mechanism route correctly
excluded `legacy_unknown` passages. The fixture now asks an ordinary summary
question; no original-evidence admission rule was weakened. The focused pair
then passed, followed by the final clean 401-case integrated run.

Frontend's initial unrestricted parallel run encountered one existing 5-second
Discovery test timeout during concurrent browser compilation. A bounded,
two-worker final run passed without relaxing that assertion. Browser checks
were corrected to target the application's named error region, separate from
Next's route announcer, and to account for development Strict Mode's aborted
first GET; an explicit retry still creates exactly one new GET.

The first full migration rehearsal failed because the new harness opened a
transaction before invoking the existing fresh-connection schema admission.
That guard correctly refused. The harness now checks admission on a fresh
connection; production admission was not weakened, cleanup completed and no
success measurement was published from that failure.

The expanded final lint selection also identified one preexisting I001 import
formatting warning in `models/db.py`'s unchanged 0067 registration line. The
same check against `git show HEAD:api/models/db.py` reproduced it at the base
revision. It is recorded rather than modifying unrelated frozen input bytes;
the new 0068 registration and all F checks pass. No whole-repository lint-clean
claim is made.

## Remaining acceptance and next dependency-ready work

The live RG03 issue was read again during this batch and remained OPEN. Its
acceptance permits a disposable fixture corpus; it does not require an
uncontrolled full-production re-embedding. Remaining local work is a retained
before/after index-migration measurement report covering chunk coverage,
rejection/truncation accounting, generation transitions, query/build timing and
explicit known/unknown provider-cost fields. It must preserve the new answer
receipts while measuring five-to-three replacement, activation and rollback.

Known-ID public vector readback still cannot enumerate arbitrary unknown remote
IDs. A declared-member pass is not full-index cleanup or measured scientific
recall. Real provider measurements, agreed deployment thresholds, reviewed
scientific evaluation, authorized source use and any production/full-corpus
rollout remain separate. No synthetic receipt grants scientific or ML authority.

No push, PR creation, live issue closure, deployment, real backfill or retention
change was performed. The broader goal remains active.
