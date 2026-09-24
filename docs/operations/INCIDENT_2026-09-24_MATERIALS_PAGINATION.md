# Materials pagination reliability incident, 2026-09-24

## Impact and corrective release

After the previous corrective release (`b842ced818db5b91dcdaf1f29db8252911788bc4`), the user reported very slow Materials initial loads and pagination and explicitly requested production deployment of the fix. An unseen page repeats the full source-policy scan and ranking of 10,507 materials. Read-only production-data diagnostics measured 19.887 and 21.904 seconds for new pages; the candidate reuses a revision-fenced ranking and measured 0.396 and 0.263 seconds with byte-identical responses.

This incident covers only PR #87, https://github.com/JackZH26/SCLib_JZIS/pull/87, and its release record. See SCLIB_MATERIALS_PAGINATION_2026-09-24.md for implementation, bounded cache behavior, native captures and local validation. There is no schema, scientific scoring or feature change. A fully cold ranking still requires a scan; release acceptance must warm the default list.

## Gate and narrowly scoped exception

Preflight at 2026-09-24 06:23 UTC reports public availability 99.99834% (240,471 requests, four errors), AI availability 98.59156% (71 requests, one error), and data freshness DEFERRED under the existing intentional ingestion pause. Public availability passes; AI availability fails. The historical AI failure has not been attributed to this Materials regression. The measured failure must remain recorded; this is not an SLO pass.

docs/OBSERVABILITY_SLO.md permits emergency reliability corrections with an incident record and an explicit rollback owner. The previous incident exception is closed; this record applies only to the present Materials correction. It does not permit a feature release, changed thresholds, artificial traffic, disabled security checks, a resumed ingestion timer or external alert messages.

**Deployment and immediate rollback execution owner:** Codex in the active Materials pagination task, carrying out the user's explicit production deployment request. The owner must complete acceptance or verify rollback before ending the deployment window.

Require the exact main revision to pass the full Test and Security workflows and require three immutable digests signed by the main release-images.yml workflow. Preserve credential validation, a verified pre-release PostgreSQL backup, migration locking/schema checks, health and deployed-version checks. If automatic deployment stops solely at the recorded AI availability gate, the remaining normal verified-image procedure may proceed under this incident exception. Any other failed gate remains a blocker. Do not change the normal deployment workflow.

## Rollback and acceptance

Before replacement, preserve the current checkout SHA, immutable image configuration and running images in a private production incident directory. The expected baseline is `b842ced818db5b91dcdaf1f29db8252911788bc4`; its current API digest is `sha256:08c2404eda235478c8225a3c1ae5021e4c5fdbd4f22b7cc7ad21969c865b25d4` and frontend digest is `sha256:936ec0f1da3c6b82c19dd68876a8b6d2f9b11d666957cfd7fd88316e52b2d0ff`. The preserved configuration remains authoritative. No reverse schema migration is needed for this correction.

After replacement, require local/public health and expected version. Warm the default Materials list (limit 50, offset 0), confirm its repeat is an X-Materials-Cache HIT with identical bytes, and measure first visits to offsets 50, 100 and a deep page. Compare total counts and response bytes with the captured baseline; verify complete Materials HTML and browser pagination. Retain Discovery's 268 historical candidates and Timeline's 19,338-result coverage. Record first-cold and subsequent timings separately.

Roll back to the preserved signed images and configuration if replacement or acceptance fails, if source-scoped result content changes unexpectedly, or if a new server failure occurs. Verify baseline health and version after rollback. Retain the deployment outcome and acceptance evidence in the operations record; this exception ends when the present deployment window completes.
