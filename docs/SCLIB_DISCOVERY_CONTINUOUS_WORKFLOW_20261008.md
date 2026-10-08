# SCLib Discovery continuous delivery and compute workflow

Owner: Jian Zhou, JZ Institute of Science. Started 2026-10-08.

## Authorization and scope

The user requested continued execution of the agreed Mini integration plan and a
persistent workflow coordinating this computer, the research VPS and the Mac mini
through final Discovery deployment. The user explicitly authorized messages to
the remote setup thread for this integration. Existing candidate publication
authorization permits clearly labelled incomplete evidence; it does not turn
unknown calculations into scores or bypass code, evidence, security or rollback
checks. The public API availability gate is the user-approved 99%.

## Ownership and durable locations

- This thread coordinates implementation, scientific protocols, review and release.
- Research VPS `76.13.191.130` hosts the isolated queue and immutable input/output
  store. Origin: `https://discovery-feed.jzis.org`, API prefix `/compute/v1`.
  It has no scientific publication authority or production database credentials.
- Mini thread `01a11ae1-fafb-7500-a6f1-613c6d986686`, title
  `搭建 SCLib M4 计算节点`, host
  `remote-control:env_e_6ac77442fda483288b61ba0bd09e9f22`, owns local installation,
  execution and machine acceptance. Resource root `/Users/Shared/SCLibCompute`.
- Repository checkout:
  `/Users/jackzhou/Documents/SCLib_JZIS-high-throughput-20261006`.
- Private run ledger and receipts:
  `/Users/jackzhou/Documents/YorkMsc/docs/reviews/SCLib_Discovery_Continuous_20261008`.
- Previous batch evidence and operator credentials remain in the existing private
  `SCLib_Batches_1_2_20261008` review directory. Never put keys or tokens in the
  public handoff, repository, messages or progress reports.
- Existing immutable handoff `2026-10-08-v1` is preserved. New integration bundles
  use new version paths and file hashes.

## Work sequence and acceptance

1. Record Mini readiness, actual engine paths/binary hashes, source/build locks,
   public CSR and successful/failed local tests. Preserve macOS authentication,
   FileVault and locking policy. Do not declare logout/reboot/24-hour tests passed
   before actual evidence exists.
2. Sign the Mini-generated CSR with a node-only identity. Its private key stays
   on Mini. Register a dedicated transport identity first; verify real HTTPS/mTLS,
   node/operator separation, claim/reply recovery, cancellation and exact receipts.
3. Review and test fixed native `qe_initialize`/`qe_scf` adapter. Enforce resource
   envelopes, a single heavy job, process-tree cancellation, immutable inputs,
   runtime hashes and durable output replay. A stopped native process is not
   resumed using the dummy checkpoint contract.
4. Run one exact Mg4B8 parent 0% initialization and SCF. Measure 1/2/4-rank cost
   sequentially; freeze subsequent budgets using measurements. Check three k
   meshes before widening the scientific study. Failed checks remain failures;
   protocol revisions produce new IDs and retain prior results.
5. Expand conditionally to the four 0% parent/Al/C/Al+C states, then ±2% strain.
   The prepared 36 inputs are not automatically queued. These known chemistries
   calibrate the workflow; they are not claims of new superconductors.
6. Start actual 24-hour observation after the real worker is active. Track worker
   heartbeat, queue state, memory/swap/scratch, interruption and recovery. Record
   both observation start and end; elapsed time alone does not establish health.
7. Continue Materials evidence review and choose a small source-complete subset
   of the 103 candidates for independent reproduction. Update only the evidence
   actually supported. Keep Source Tc source-labelled and unknowns unknown.
8. Finish PR #154 CI and independent review, then release through the existing
   backup/image/version/SLO/cutover/rollback procedure. Verify Materials/Discovery
   in desktop/mobile browsers, and observe deployed service for at least 10 min.
   Compute soak need not block unrelated website changes; the website must not
   advertise unfinished compute acceptance as complete.

## Each continuation

Read this plan, the private state ledger, git status and current PR heads first.
Inspect the remote thread with a compact wait snapshot and only read new outputs
needed for decisions. Reuse existing agents/threads; do not create parallel
workers, duplicate queues, repeated PRs or a second deployment. Continue the next
authorized, unblocked action and update the ledger with artifact paths, exact
commit/bundle/job IDs, observed status and next action. Keep failed experiments
and receipts. Never carry a pass from an old commit to a changed head.

While one task waits on CI, machine authentication or real elapsed soak time,
advance independent tests, protocol preparation, evidence review or release
packaging. Ask for user action only for an actual missing credential, machine
authentication, ambiguous decision or destructive operation. Do not ask again
for already authorized publishing or routine integration work.

Completion requires verified production deployment, an accurate candidate/evidence
view, archived release/rollback evidence and a handover stating any unfinished
scientific work. When this delivery scope is complete, pause the continuation
automation; 24-hour compute service itself remains a separate managed service.
