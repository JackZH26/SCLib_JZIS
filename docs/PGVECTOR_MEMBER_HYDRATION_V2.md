# Retained content member hydration v2

This is an unwired read component. It accepts a database-authoritative current
v2 pin, not a provider generation or a caller-selected table name. Public route,
lexical/formula/scientific lookup, saved-answer/frontend and final publication
barrier integration remain separate work. None of the v2 schema is deployed in
production.

`retrieval_members.load_members` resolves at most 1,000 unique content members
and eight MiB of retained reference/origin/vector payload. It verifies each
content record, the original legacy/native record, original revision identity,
reference/origin bindings, retained text hash and exact original vector bytes.
A native origin also checks its actual input-receipt record/hash/parser/chunker
binding. A temporary bytea setting makes original v1 hashes independent of a
caller's escape setting and is rolled back after reading. The caller must
flush outstanding ORM changes before this private savepoint operation.

The original legacy generation remains inside its own origin. A native origin
retains its actual `rv2_` identity and has no invented generation field. Both
carry explicit v2 content-member and origin record hashes. Private archive paths
and source URIs are not selected or returned. Unknown members and conflicting
payloads fail instead of turning into successful empty results.

Candidate verification binds the complete SQL batch to the same build/content/
manifest pin and compares paper/text/vector/revision hashes before scores can
influence ranking. Retained hydration uses frozen text and bibliography after
mutable Chunk changes/deletion. The current Paper is a live source-policy
overlay. `GenerationChunk` is reused only as the existing internal retained
snapshot policy view; its pin explicitly has v2 metadata and no v1 resource.
It cannot be passed through the existing v1 saved-answer capture contract.

Evidence resolution reuses the existing retained-source policy. Missing
extraction parents, root uncertainty, historical parser/lineage warnings and
scientific nonacceptance remain intact. Historical restrictions, source holds
and renderer currentness remain live after native capture or mutable Chunk
deletion. A native input-file observation creates no root, permission,
independent evidence or scientific support. Mixed pins/evidence and superseded
backend pins fail. The later whole-request coordinator must additionally
recheck all live rights and currentness at its final publication barrier.

Both exact-filtered and graph candidate sorts now use the frozen canonical ID
collation for equal-distance ties. The ordinary API remains on its original
reader. Search/Ask/Similar, history and website acceptance are not inferred from
these private component tests.
