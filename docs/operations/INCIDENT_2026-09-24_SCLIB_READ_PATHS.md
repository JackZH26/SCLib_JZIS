# SCLib read-path reliability incident, 2026-09-24

## Impact and observed cause

The user reported slow Timeline and Search after the upgrade and no historical candidates in Discovery. Production revision `f33cbe8adbcdf8d1c370da65e808acc2d45372a3` returns an unavailable Discovery feed even though its mounted input validates with 268 candidates. A recovery-sidecar write on the read-only mount incorrectly invalidates that input. Timeline redundantly rebuilds a large response; Search serializes provider and SQL work and performs expensive formula verification before limiting candidates.

The corrective change is PR #84, <https://github.com/JackZH26/SCLib_JZIS/pull/84>. Measurements, scope, regression coverage and byte-equivalence checks are in `SCLIB_PERFORMANCE_DISCOVERY_2026-09-24.md`. There is no schema or product feature change. This record does not assert that the fix has been deployed.

## Release exception and owner

Preflight on September 24 reports public API availability of 99.99833% (240,313 requests, four errors), but AI API availability of 98.33334% (60 requests, one error), below its 99.5% target. The failing error-budget gate must remain recorded as a failure. The small request volume does not waive the target. The particular historical AI error has not been attributed to this regression. Data freshness is explicitly deferred under the already configured ingestion pause; that is not a freshness pass.

`docs/OBSERVABILITY_SLO.md` permits emergency security and reliability fixes with an incident record and an explicit rollback owner. This record covers only the above corrective reliability release. It does not authorize feature releases, modification of SLO thresholds, manufactured traffic, disabled security checks, or reuse of untested images.

**Deployment and rollback execution owner:** Codex in the active SCLib performance/discovery task, carrying out the user's requested repair with the existing authenticated production connection. Codex remains responsible for the deployment window and immediate rollback if acceptance checks fail. Do not leave a failed or partially verified replacement running and end the task.

Release only after the main revision passes the full Test and Security workflows and the release pipeline produces three immutable image digests signed by the repository's `release-images.yml` workflow on `main`. Preserve normal credential validation, pre-release PostgreSQL backup, migration lock/schema checks, health checks and version checks. If the automated deployment stops solely at the recorded error-budget gate, execute the same remaining verified-image deployment procedure under this incident exception, retaining the failed gate output. Do not modify the normal deployment workflow to bypass its gate.

## Rollback and acceptance

Before replacement, preserve the production checkout revision and `.env.release` in a private incident directory on the server and record the actual running API/frontend image references. The baseline images observed before this release are:

- API: `ghcr.io/jackzh26/sclib-api@sha256:3f5560bab29ef15e5e88ccb5beafb88c0911c4ab7ebdb214bae374816bf84ea4`
- Frontend: `ghcr.io/jackzh26/sclib-frontend@sha256:2e165a05f1ab5508b72e76c29ffc0816550d94222f0dafc8f36c5c052137e4a5`

The stored pre-release configuration remains authoritative for all three component images. Keep it private and do not log environment credentials. Roll back by restoring the previous checkout and immutable image environment, running the same production Compose configuration with `--no-build`, and verifying local/public health and version `f33cbe8`. No reverse database migration is required by this change.

Accept only when local/public health and deployed revision match the verified release, Discovery metadata is ready and its candidate endpoint returns the retained 268-candidate feed, and the default Timeline response retains 2,000 display points and coverage of 19,338 records with a successful subsequent cache hit. Execute an ordinary Search and a repeat, verify grounded results, and record actual response durations. Roll back if these checks show new server failures, changed Timeline content/coverage, missing candidates, or a search correctness regression. A cold cache alone is not a failure; first-request and repeat timings must be reported separately.

Deployment evidence and the final outcome must be added to the operations record after execution. The incident exception ends with this corrective deployment window.
