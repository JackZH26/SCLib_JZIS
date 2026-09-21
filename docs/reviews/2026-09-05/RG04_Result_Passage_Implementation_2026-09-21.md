# RG04 result–passage implementation — 2026-09-21

Status: the previously missing positive association software path is implemented
locally. This does not close RG04/#75 because no authorized real source pair has
been reviewed and the issue's gold-set, adjudication and evaluation criteria are
still outstanding.

## Delivered behavior

- Alembic head 0078 adds an append-only `scientific_result_passage_links`
  ledger. Each row binds an immutable extraction revision, an immutable original
  passage, exact content/locator/source hashes, closed claim/sample identities,
  one active reviewer grant and one predecessor head.
- Private context, preview, commit and receipt routes support exact establish and
  withdraw decisions. Preview uses the real SERIALIZABLE SQL path and rolls back;
  commit requires its digest. Actor-scoped request keys replay only on an exact
  match.
- Mixed Ask resolves current link heads inside the same fresh repeatable-read
  snapshot that checks the complete selected numerical and original evidence
  inventory. A missing, withdrawn, stale or no-longer-authorized link is not
  exposed as positive. Resolver failure withdraws both inventories.
- Wire version 1.1 carries complete positive bridge pins while retaining 1.0
  history compatibility. The English interface separates reviewed relation
  metadata from unresolved pairs and continues to deny causal explanation,
  independent-support counts and scientific acceptance.
- Research account deletion now treats the reviewer actor reference as retained
  audit history. Empty-ledger downgrade/upgrade, populated-history downgrade refusal and
  exact establish/withdraw/replay run on the migrated disposable database.
- The restore fixture retains one current link and one established-then-withdrawn
  link. Actual dump/restore verifies all three rows and historical receipts and
  exposes only the current link in a fresh snapshot.
- Historical 1.0 mixed answers keep the original closed association field set
  after Python serialization; new 1.1 responses require explicit null or complete
  reviewed-link pins. Positive pairs must share the exact source snapshot.

## Scientific boundary

All positive-path tests use synthetic paper, extraction and original-passage
fixtures. They verify software behavior only. No source right, real reviewer
judgment, causal conclusion, publication approval, model-training permission or
scientific acceptance was created.

## Remaining RG04 acceptance

- obtain authorized original-source custody and exact passage roots;
- acquire the planned stratified real question/pair inventory;
- complete independent blinded review and disagreement adjudication;
- run the preregistered held-out comparison and retain failures, costs and
  uncertainty;
- run remote Linux Test/Security after the branch can be published.

## Validation record

See the September 21 delivery record for exact completed commands, results and
revision identities. Scientific acceptance remains open regardless of software
test outcomes. The sample hash pins one retained result record; it does not
establish canonical real-world specimen identity or cross-paper independence.
