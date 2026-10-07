# Fixed-payload Discovery publication on 2026-10-07

The operator explicitly authorized: “不用等 API 回归，开始部署发布正式环境”.
This waives waiting for the full API regression for application payload
`bcf2d8549348646ca0908a6ee8144fec59ab3ce7` only. It does not claim that regression
has passed or change the full Test-success requirement for future revisions.

The payload contains the 103 unscored research hypotheses and the approved 99%
public-API availability policy. Test run `37592295851`, attempt 1, has five
completed successful jobs; API offline contracts and candidate-runtime parity
have passed. The owned-service API regression continues in the background.
Security run `37592295808` for the payload has succeeded.

`Release images` has a temporary manual dispatch lane with no revision input.
Its control workflow runs from main, while every image is built from the fixed
payload checkout. Control and payload revisions are recorded separately. The
lane checks the actual partial Test state and matching Security success,
records the authorization, compares final API/ingestion image digests with
freshly captured locked Python package inventories, and retains the existing
vulnerability scan, SBOM, GitHub OIDC signature and build provenance.
Fresh package inventory parity is not application regression or OS/ABI proof.

Deploy this successful manual Release run through `Deploy to VPS2`'s manual
`release_run_id` input. The manifest must contain the same fixed payload for
all three images. The 99% public / 99.5% AI availability checks, intentionally
paused ingestion marker, credential checks, backup, signature verification,
schema check, health smoke tests and atomic release-pin persistence remain in
place. Production acceptance still requires real browser checks and at least
ten minutes of observation. Rollback uses the accepted `2012d0a` images and
unchanged schema `0091_material_table_fields`.

For this payload only, the later automatic Test completion does not rebuild or
automatically deploy a second set of images during acceptance. Future payloads
retain the original automatic Test-success release path. A previous successful
manual run prevents another manual publication. Remove the temporary manual
lane after this release is accepted; retain this record and actual CI evidence.

This website publication does not publish formal RPS scores, independent
scientific approval, experimental superconductivity or room-temperature claims.
