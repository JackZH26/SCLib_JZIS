# Versioned content answer capture

The `content_answer_evidence` capture and closed `ask-answer-evidence/2.0.0`
models preserve final request/response bytes and selected v2 identities.
Revision 0113 stores them in `content_answer_evidence_receipts_v2`, with a
separate nullable marker on new AskHistory rows. Existing v1 tables, functions,
decoders and stored receipt bytes remain unchanged. Existing history cannot be
retrofitted, and an answer cannot claim both receipt versions.

The shared transactional answer writer dispatches only on actual typed capture
objects, checks the original account/session again, and commits history and its
complete immutable receipt together. A v2 prepared object cannot enter the v1
writer. The owner-scoped history list/detail/delete endpoints accept both
versions; v2 detail uses retained content/origin/evidence rows and saved bytes.
It never calls a provider, resolves the active pointer, requires the old ANN
table, or reruns the current scientific parser. Current source governance is a
separate bounded overlay. Integrity checks do not confer current permission or
scientific acceptance. Deletion follows owner deletion/account cascade/normal
retention. Nonempty downgrade and direct receipt mutation are refused.

The browser has a separate closed v2 receipt decoder and displays real content,
build and origin identities. The existing v1 decoder continues to reject v2.
The committed synthetic cross-stack fixture was captured from the guarded SQL
writer and actual owner HTTP detail. Public v2 Search/Ask/Similar execution and
production release remain separate integration gates.

Bindings retain explicit content/build/event/root/policy/profile, logical index,
content-member hash, real legacy generation or native revision, original-record
hash, vector/revision/content/source-snapshot hashes and exact evidence/parent
references. Native members never receive fabricated provider generations. The
selected-input pin uses an explicit content-pin field; its digest binds the
complete private v2 identity, including the logical index and embedding space.

Capture accepts only actual typed retained chunks/selection pins or validated
`ContentScientificInputs`. It verifies source text/vector bytes, frozen
bibliography and snippets. Numerical projections are recomputed once from the
complete raw parent using the current query implementation before capture; real
parent IDs alone cannot legitimize a changed scalar. Future historical replay
must verify the saved bytes and retained sources without rerunning a newer
scientific parser or consulting the active index.

Process-private MACs detach selected presentation from mutable aliases before
provider I/O. Final output must match the captured source/result inventories;
complete withdrawal clears every previously selected origin ID. Quota and
persistence disposition fields are excluded. Closed models reject mixed
versions, wrong origins, unbound parents, duplicate or reordered items, opaque
coercions and oversized payloads. These checks preserve process consistency;
they do not replace SQL retained-row and owner verification.

Fresh owned-service checks cover real legacy/native numeric and citation
capture, frozen attribution, vector-byte tampering, scalar changes with real
parent IDs, MAC replacement, detached output, final withdrawal and the v1 writer
boundary. Existing v1 saved-answer tests run alongside them. Pure wire fixtures
are structural tests rather than stored-row or scientific evidence.

Current focused validation: 117 freshly owned PostgreSQL/vector/API checks,
88 frontend history checks, TypeScript checking and eight historical projection
checks passed. The schema harness additionally exercises an empty 0113 round
trip and refusal to downgrade a real committed synthetic v2 receipt. Its full
result is retained separately; these counts do not establish production,
relevance or full-service load acceptance.
