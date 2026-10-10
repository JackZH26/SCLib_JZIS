# Isolated compute staging control plane — 2026-10-08

The original acceptance below describes the deployed dummy-only version. The
subsequent opt-in native worker contract and separate acceptance requirements are
documented in [Native QE worker](sclib_compute_native.md). Code availability does
not change the historical deployment receipt or imply Mini acceptance.

This implementation provides a persistent transport coordinator and a **dummy
adapter only**. It has no production database connection and cannot publish or
approve scientific candidates. `structure_check`/`qe_*` are contract vocabulary;
they are disabled in the supplied service configuration. A native solver adapter,
M4 node acceptance and the 24-hour soak remain separate work. The existing QE pilot
does not become a queued native worker through this implementation.

## Files and checks

- `scripts/sclib_compute/`: closed contracts, SQLite transactions, loopback API,
  durable dummy worker. It imports no website API.
- `scripts/sclib_compute_service.py`: fixed loopback service entry point.
- `scripts/sclib_compute_dummy_worker.py`: separate executable worker. An Agent
  installs/maintains it; the Agent is not the 24-hour execution loop.
- `scripts/sclib_compute_probe.py`: opt-in HTTPS/mTLS roundtrip with lost claim and
  complete ACK injection, process-object restart and same receipt replay.
- `scripts/sclib_compute_deploy/`: non-root systemd and dedicated nginx examples;
  JSON templates contain placeholders, not secrets and not executable defaults.
- `tests/test_sclib_compute_staging.py`: T01–T10/T13 transport fault tests.

Use a dedicated environment (recommended Python 3.11+; local tests also ran on
Python 3.9.6). Install `scripts/sclib_compute_requirements.txt` plus pytest for the
test suite. The runtime requirements freeze all installed production packages
from the verified local environment; retain the deployment's actual `pip freeze`
as evidence as well. `.github/workflows/sclib-compute-staging.yml` runs this suite
in an isolated Python 3.12 job without changing the existing API gates.

```sh
python3 -m venv /absolute/private/test-venv
/absolute/private/test-venv/bin/pip install -r scripts/sclib_compute_requirements.txt pytest
/absolute/private/test-venv/bin/python -m pytest tests/test_sclib_compute_staging.py -q
```

The 2026-10-08 local test result was 20 passed. These tests do not establish an
external TLS deployment or native M4 calculation. External evidence is generated
only by the real staging probe and retained as a private `report.json`.

An actual research-VPS deployment and verified HTTPS/mTLS dummy roundtrip were
subsequently completed on 2026-10-08. The sanitized acceptance projection is
[`compute-staging-acceptance-v1.json`](data/discovery-batches-20261008/compute-staging-acceptance-v1.json),
including denied anonymous/unknown identities, lost ACK recovery and an identical
receipt after an actual service restart. This does not change the M4/native-solver
or 24-hour-soak status above. Operator and dummy client private keys remain outside
the repository and the public handoff directory.

## Authentication and privileges

The server always binds `127.0.0.1` and runs with `proxy_headers=False` and access
logging disabled. It requires the **actual TCP peer** to be loopback; an
`X-Forwarded-For` claim cannot satisfy that check. Nginx verifies a client certificate
against a dedicated staging CA, forwards the verified certificate PEM as an
escaped header, and authenticates itself with a separate private proxy secret.
The application computes the certificate's DER SHA-256 and looks it up in a
fixed configuration map. Subject names and caller-supplied node IDs/fingerprints
grant no authority. The default configuration rejects direct bearer credentials.

Only an operator certificate can stage input blobs, enqueue frozen jobs, cancel,
drain a node, reconcile or read fleet status/events. A node certificate has one
fixed node ID, one runtime and an explicit capability list. Registration can only
declare a subset of that grant, cannot select another identity or budget, and
cannot change an existing registration. Nodes see only their own attempts/events.
Certificate issuance, replacement grants and CRLs remain operator-controlled
private provisioning actions. Remove a compromised certificate digest from the
service config, apply nginx CRL when applicable, restart/reload and cancel its
active attempts. Never place CA/client keys or proxy secrets in static assets.

`loopback_test` is an explicitly selected local-only testing mode with SHA-256
bearer mappings. Do not expose or proxy it. The deployment probe refuses it.

## Frozen envelopes and durable lifecycle

Operator enqueues a closed `JobSpec` with material/state/action refs, exact staged
input hash/size pins, runtime, capability, output basenames and maxima, deadline,
1–3 attempts and bounded resources. Job ID is an idempotency key: same bytes return
the same job; altered contents are rejected. The job envelope cannot be changed
after queueing. No job can exceed server caps.

The worker fsyncs its `claim_request_id` before the claim request. SQLite persists
the key, the attempt and its increasing fence in one `BEGIN IMMEDIATE` transaction.
Replay returns the same attempt's **current** lifecycle/receipt, including lost
or ended attempts. Empty claims also stay empty on replay. Claim retries never
reserve CPU twice. A new request is required for a new actual attempt.

Heartbeat renews an unexpired matching lease only, with monotonic phase/progress
and memory checks. Expired leases become lost, with a retry grace period before
the job can be assigned again. Reconciliation runs on claim/status-mutating
attempt operations or explicit operator request; it is not a second scheduler
daemon. Heartbeat says `continue=false` for cancelled/expired/fenced attempts.
Drain permits the present live attempt to finish but prevents a fresh claim.

Each actual attempt reserves its full CPU×wall envelope against a persisted
campaign cap; this conservative reservation is never refunded, even after loss.
It is a bound on potentially consumed work, **not measured billing or an RPS
budget**. Job/claim counts and artifact bytes are also capped. This initial dummy
is bounded closed JSON and fixed tiny Python operations; OS sandbox/cgroups/native
solver watchdogs are required before enabling any real calculation adapter.

Input/output objects are immutable SHA-256 files, written with `O_NOFOLLOW`,
fsync and atomic rename in a service-owned directory. Only closed basenames are
accepted; symlink/non-regular files, wrong lengths/hashes, excess bytes, full
quota and low disk are rejected. The transport verifies blobs again at complete.
Output uploads from an ended attempt may stage private bytes so an already-saved
outbox can still produce an auditable **quarantined** receipt. They cannot revive
the lease, overwrite a newer attempt, or grant scientific acceptance.

The worker fsyncs exact output bytes and the complete body before uploading.
Complete binds every declared output to staged bytes and the frozen input/runtime.
An accepted identical retry returns the original receipt, even after lease expiry
or a server restart; same attempt with a changed complete body is rejected. A
wrong fence cannot poison an otherwise live attempt. Unaccepted stale results or
input/runtime mismatch are quarantined; cancellation still prevents acceptance.
Solver failure, non-convergence and the **synthetic dummy checkpoint** remain
explicit outcomes with `scientific_status=not_assessed`. They are never Tc results.

Recoverable transport/worker failures can retry only within frozen attempt/deadline
and campaign limits. Solver failures do not automatically retry. State/outbox
directories have a process lock and owner-only permissions. Operator maintenance
must archive and rotate a full staging campaign; there is no automatic retention
GC or distributed object storage in this first implementation. Do not delete the
DB while keeping workers' claim keys or unacknowledged outboxes.

## Separate non-root VPS deployment

Review free port 8092 and the existing nginx configuration first. Install only this
namespace into an isolated immutable release, such as
`/opt/sclib-compute/releases/<revision>/scripts`, with
`/opt/sclib-compute/current` selecting it. Create a dedicated `sclib-compute` system
user without login. The source and venv must be administrator-owned/read-only to
that service; the service only owns `/var/lib/sclib-compute` (0700). No website
environment file, production database URL or production storage credential is
provided to this unit.

Create a dedicated venv at `/opt/sclib-compute/venv`, install the requirements and
record its package freeze. Place the populated private service JSON at
`/etc/sclib-compute/config.json` (root:sclib-compute 0640), certificate material in
a private TLS directory, and the nginx proxy-secret include at root:root 0600.
Only the secret's SHA-256 is placed in the app JSON. Keep the issuing CA key offline
or in a separate operator directory. Issue separate operator and dummy-node client
certificates, calculate their DER SHA-256 pins and grant the node **dummy only**.

The service CLI is:

```sh
/opt/sclib-compute/venv/bin/python /opt/sclib-compute/current/scripts/sclib_compute_service.py \
  --config /etc/sclib-compute/config.json --data-dir /var/lib/sclib-compute --port 8092
```

The unit example adds `ProtectSystem=strict`, `ProtectHome=true`, no capabilities,
private temp, bounded process/memory/CPU and only the staging data write path.
Apply it only after inspecting the current host. Add a **dedicated** nginx staging
vhost using the example; do not replace the existing app or discovery-feed vhosts.
Validate `nginx -t` before reload, verify direct peer/header checks and confirm
port 8092 is never publicly bound. A deliberately new HTTPS port can also be used
in a dedicated staging block with firewall review when DNS is unavailable. Use a
server certificate trusted by the explicitly configured probe CA, never disable
verification. The old static handoff v1 must remain unchanged.

## Actual external TLS acceptance

Prepare private operator and node client JSON files from the client template.
Each needs staging origin, server CA bundle and its own client certificate/key.
Keys/configs must be owner-only; no URLs contain credentials. The probe output
directory must be new and private. It stages one fixed dummy job and injects lost
claim ACK and complete ACK, restarts its worker object from disk, verifies node
operator denial, identical receipt replay, and exactly one envelope reservation:

```sh
python scripts/sclib_compute_probe.py \
  --operator-config /absolute/private/operator.json \
  --worker-config /absolute/private/dummy-node.json \
  --output /absolute/private/new-probe-receipt
```

Also verify an absent/untrusted client certificate fails TLS, a valid but unpinned
certificate is refused by the app, wrong proxy token fails direct loopback auth,
worker recovery after a service restart preserves its receipt, and public
application/feed health remains unaffected. These are concrete deployment tests;
do not label them complete until the actual report and host evidence exist.

To run the standalone dummy worker against this staging service:

```sh
python scripts/sclib_compute_dummy_worker.py \
  --config /absolute/private/dummy-node.json --state-dir /absolute/private/dummy-state
```

The default is one bounded cycle. `--serve --max-jobs 0` is an explicit standalone
poll loop with capped network backoff and 30-second idle intervals, not an Agent
polling turn. Do not enable a 24-hour daemon on the mini until its native bootstrap,
FileVault/network/cold-start checks and node-specific resource enforcement pass.
Real QE restart/checkpoint rules must not inherit the idempotent dummy execution.

## Fault coverage

| ID | Verified locally |
|---|---|
| T01 | Actual loopback peer, proxy token/verified certificate pins; node/operator separation; denied identity/budget injection |
| T02 | Staged input hash/size and immutable job-content binding |
| T03 | Lost claim ACK, queue reopen, ended attempt and durable empty-claim replay |
| T04 | Complete ACK loss, exact receipt replay after lease expiry and restart; changed content rejected |
| T05 | Old attempt quarantined after higher fence; new accepted result unchanged |
| T06 | Expired lease cannot heartbeat-renew or download; retry grace respected |
| T07 | Concurrent claims assign one attempt; persistent accounting |
| T08 | Dummy solver failure/non-convergence/checkpoint stay explicit; no scientific approval or automatic solver retry |
| T09 | Basename/hash/size/body caps, symlink/corruption/low-disk rejection |
| T10 | Cancel, drain, bounded infrastructure retry and conservative campaign reservation |
| T13 | Runtime/capability matching, frozen input mismatch quarantine and wrong-fence rejection |

M4 sleep, cold boot, live process cancellation and a 24-hour soak are not covered
by this local transport suite. They require the actual node.
