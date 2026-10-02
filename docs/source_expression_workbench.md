# Private source-expression workbench

`/dashboard/research/source-expressions` uses the existing authenticated
dashboard and existing research grants. A default-disabled v2 API returns no
editable workspace. Reviewers can read; current curators can preview and save.
No user, grant or publication permission is created by this page.

## File selection and explicit saves

The operator selects a prepared `source-expression-package/2.0.0` JSON file.
Selection reads it locally and makes no API write. The client checks a 1 MiB
file bound, the closed keys and finite registry, duplicate keys, depth, UTF-8,
canonical base64, a 128 KiB retained fragment, one to twenty expressions,
ordered nonoverlapping Unicode-codepoint spans and each exact substring hash.
Scalar values and units have contiguous original spans. Split formula runs
remain a declared formula assembly, not an established physical identity.

The source fragment remains byte-exact in the request. A local file fingerprint
is separate from the server's canonical package metadata fingerprint. Raw
source values, missing units, conditions, roles and source windows are shown
before preview; the client does not infer normalized scientific quantities.
The preview is sent only by an explicit button. A second explicit button saves
the identical package with the returned preview hash. Selecting another file,
refreshing access or changing the record view invalidates the preceding draft.

A successful save writes private pending fragment/expression history. It does
not establish a material, sample, phase or selected-result association, approve
science, change the public catalogue or grant redistribution rights. A timeout,
503 or unverifiable save response is an unknown outcome, not a failed write.
The workbench retains the original actor, request key, request hash, package
metadata and verified preview/manifest pins. Recovery calls only the GET
outcome endpoint. It never retries POST automatically. A missing outcome does
not establish rollback. Account/session notifications clear private state;
late file, capability, record and write responses cannot restore it. Leaving
with an unresolved operation warns before discarding the in-memory reference.

## Bounded reads and provenance

The page lists at most eight current expression heads and twenty-five
capture metadata records per response. Field/source/currentness filters apply
to expression heads; capture lists share only the declared-currentness filter.
Pagination stays within the API's offset bound. Counts describe ledger
fragments and expression revisions, not publications or independent experiments.

An exact revision view binds its source entry to the original receipt package,
entry index/hash, manifest, source metadata and capture hash. Retained canonical
projection/revision/package/request/preview/receipt strings are hashed directly;
JavaScript does not reserialize floating-point projections to imitate Python
canonicalization. Compact list rows omit the full receipt proof. Details carry
that complete binding. The full private source fragment is not returned by
these read endpoints and is not displayed as presumed publication text.

The value view keeps the printed expression primary, followed by the server's
bounded normalized interpretation when available. Unresolved syntax/units stay
explicit. Study extent, synthesis and fit-window conditions retain their role;
ambient labels do not become zero-pressure measurements. London penetration
depth is separate from electron–phonon coupling. Declared computation origin
and its inspection basis remain separate from scientific verification.

Source locators, origin basis and fingerprints sit behind a disclosure. The
server-verified retained-fragment hash is labelled separately from the unverified
declared parent-file hash. Latest capture/current expression head refer to
ledger history. Publication revision, rights and currentness remain unverified.
Source links are metadata links opened explicitly, not automatic fetches.

## Validation status

Focused client tests cover malformed/private input, actual codepoint offsets,
signed and uncertain raw values, absent units, coordinated projection/manifest
tampering, original outcome identity, stale file/account responses, explicit
preview/save behavior, read-only access and bounded filter state. Synthetic
test packages do not represent source inspection or human review. Backend
SQL/native validation, authenticated local browser acceptance and a production
frontend build are separate checks performed after the backend contract freeze.
No production, scientific approval or public acceptance is implied here.
