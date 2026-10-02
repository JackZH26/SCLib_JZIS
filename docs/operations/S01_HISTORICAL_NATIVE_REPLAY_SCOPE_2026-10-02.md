# Historical R8 provenance during the S01 upgrade

The seven retained R8 SQL/HTTP archives describe their actual capture inputs,
not a new execution against the S01 backend. Their 4,123 source pins match the
635 distinct Git blobs at immutable ancestor
`748bb23710b409ebb927806e945048bd2608e5ec`. Original wire bytes, manifests,
literal archive hashes, pin counts and earlier capture documents are retained.

S01 intentionally changes configuration, application/model registration,
pending-history retention and migration helpers. Comparing R8 capture pins to
those current files incorrectly treats a historical capture as a fresh one.
Six frontend replay suites now verify each pin against that fixed capture
revision. The test-only reader requires the revision to exist and be an ancestor
of the checkout, accepts only known closed R8 pins and fails for an unknown
path, altered pin, missing blob or hash mismatch. It has no fallback to current
files, a different revision or a network fetch. Frontend CI checks out full
history to make this explicit immutable source proof available.

These assertions establish historical capture provenance and current frontend
parsing of retained wire responses. They do not establish fresh native runtime
compatibility for the seven older workflows against S01. Current S01 behavior
is validated separately by its exact-snapshot mapper, native authorization,
SQL/migration and DTO tests, and the isolated private workbench browser proof.
Those tests preserve pending status and do not authorize scientific acceptance,
canonical promotion or physical sample/result/phase associations.

The initial PR93 frontend failure is retained separately: 2,105 tests passed
and six historical pin assertions failed before the build step. Its failure is
not reclassified as a pass. This scope correction preserves the old expected
hashes rather than assigning new pins to previously captured responses.
