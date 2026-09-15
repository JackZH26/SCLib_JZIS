# Batch 77 — scoped private ingress and actual transport verification

Base HEAD: `02949468802db042e56645e2932b08863a174074`, branch
`codex/sclib-research-v2`. Preserves uncommitted batches 74–76. This batch fixes
the host-proxy contract needed to carry existing private research envelopes;
it does not change the scientific schema, application budgets or feature flags.
No commit, push, deployment, migration, account grant or issue closure occurred.

## Priority and delivered scope

The next practical dependency for [ML08 #54](https://github.com/JackZH26/SCLib_JZIS/issues/54)
was a mismatch between the generic 20 MiB proxy limit and the existing larger
JSON/base64 envelopes. Extending byte replay alone did not make registration,
review and ML-use intake transport-compatible. This also affects operational
delivery under [EN02 #58](https://github.com/JackZH26/SCLib_JZIS/issues/58) and
private research boundaries under [ML07 #68](https://github.com/JackZH26/SCLib_JZIS/issues/68).

The complete operator contract is [PRIVATE_INGRESS.md](../../PRIVATE_INGRESS.md).

| Exact upload group | Routes | Proxy ceiling |
| --- | ---: | ---: |
| Registration and participation acceptance | 2 | 22,435,160 bytes |
| Review preflight, declaration and joint coverage | 3 | 44,804,784 bytes |
| Canary/context evidence replay | 1 | 130 MiB; smaller exact application frame bound still applies |
| ML-use reconstruction and request intake | 4 | 32 MiB |
| Scientific program import | 1 | 24 MiB |

All other routes retain their 20 MiB proxy ceiling. Upload exceptions are exact
locations, including an explicit upstream content handler for each nested
location. Application validation and smaller per-file limits remain independent.
Private pilot, ML-use and scientific-import recovery/control routes share the
privacy policy; public research distribution/download routes are not included.

The shared location snippet disables request/response buffering, temporary
response files, cache/store, retries and upstream-error interception, uses
upstream HTTP/1.1, suppresses location logs and sets private/no-store responses.
Existing security headers are repeated to preserve their inheritance semantics.
The evidence rate remains 6/minute/IP with burst 2; other exact uploads use
12/minute/IP with burst 6. These are protective defaults, not capacity benchmarks.
Proxy inactivity timeouts do not relax existing absolute API deadlines.

The bootstrap installs the absent policy before the main server configuration,
leaving existing operator-managed files untouched. Deployment instructions now
use the migration-only service and the new API image's read-only schema check
before replacing application services. They no longer instruct migration through
the running API's credential. A source regression locks this ordering; no such
operator command was executed in this batch.

## Actual disposable Nginx evidence

The standard-library [runner](../../../nginx/rehearse_private_intake.py) starts
only owned loopback Nginx and synthetic upstream instances. It imports no API,
uses no database or user credentials, and downloads/installs nothing itself.
Each instance passes real `nginx -t` and uses a verified local HTTPS connection.
Temporary processes, threads and TLS material are cleaned up before an exclusive
mode-0600 passing report is created. Source hashes are checked before and after.

The final native run passed all eleven routes, verifying:

- Full-ceiling content-length and chunked uploads, upstream byte counts and
  SHA-256 equality: **949,966,208 bytes** across the 22 successful full uploads.
- Declared limit+1 rejection before upstream admission, plus actual chunked
  limit+1 rejection. The latter report's byte field is a requested length,
  not proof that all requested bytes were transmitted or forwarded.
- A synthetic upstream's early 403 before body consumption, correct stripped
  paths and cookie/Origin/participant-header forwarding. This is transport
  evidence, not actual API authentication testing.
- Paused uploads reaching upstream before EOF, with no observed active body
  temporary files. The observer checks open file descriptors, including unlinked
  files, rather than relying only on a directory listing.
- A deliberately buffered synthetic negative control that exposes a temporary
  file and does not reach upstream before EOF. This demonstrates the observer
  can detect the condition it is intended to reject.
- Two independent 8 MiB responses: **16,777,216 verified bytes**, no observed
  response temporary files, preserved private/security headers despite upstream
  public-cache and buffering headers, and two actual upstream responses.
- Neighbor/public 20 MiB limits, hidden metrics/admin routes, seven 200 then
  three 429 responses in the shared upload-rate check, and no private synthetic
  body/query/cookie/participant markers in owned proxy logs.

The owned build used Nginx **1.30.4**, clang 21 and OpenSSL 3.6.1 on macOS arm64.
The official archive SHA-256 was checked, and its detached signature verified
with the official Roman Arutyunyan key, fingerprint
`43387825DDB1BB97EC36BA5D007C8D7C15D87369`. GPG reported a good signature with
unknown key trust; this is not a pre-established independent web-of-trust claim.
No package/service installation or `make install` occurred. Sources:
[official downloads](https://nginx.org/en/download.html),
[official signing keys](https://nginx.org/en/pgp_keys.html).

### Failures found and corrected

The first actual run passed syntax validation but returned 404 on the first
nested exact upload: inherited proxy settings alone had not installed its
content handler. Each exact child now declares its own `proxy_pass`.

Subsequent full-route runs exposed a blind spot in the negative control:
directory-only inspection missed an unlinked body file, and the first descriptor
check missed macOS `/var` versus `/private/var` aliases. The runner now inspects
owned-child descriptors and normalizes real paths; a unit test opens and unlinks
its own temporary file to preserve that regression.

A final target-safety guard initially misread the word `include` inside a
comment as an active directive. The source test failed (1 failed, 56 passed),
and native verification stopped before launching Nginx. The guard now matches
actual directive lines. Both full native verification and source tests were
rerun successfully. No failing attempt emitted a passing report.

### Immutable artifacts and pins

The [final report](Private_Ingress_Native_Rehearsal_Batch77_Final.json) is the
current selected-source observation. The
[earlier successful report](Private_Ingress_Native_Rehearsal_Batch77.json)
is preserved unchanged as pre-final-target-guard evidence, not current script
attestation. No archive was overwritten or resealed.

| Artifact/source | SHA-256 |
| --- | --- |
| Final report | `8dfe7fafd1737d29bc08819654cca6b66797083af2259f4f01f9dba2bae743d4` |
| Earlier report | `ee7a9c0c3208a6ea84efb3365d5f5a4228c52741a1738095f8440ed5321cf407` |
| `nginx/sclib.conf` | `337b66f82d79ea893704714a55d1eab27982a255810cf66e30c364079d5a2c3a` |
| `nginx/private-intake.conf` | `0c326806e4cc2c8cc50cc11e15eba9234ec5b097c1785ce94c0e24cf1b98d84b` |
| `nginx/rehearse_private_intake.py` | `db4540f72c893abe0fc23a20f29522c47a00dca7b152109fc9554713eee69827` |
| Native Nginx executable | `43873584f8567508ebb94d865f97872f5fd2f1c77a3181c4f1d0f9d6a0003ce6` |
| Official Nginx source archive | `4261dc90e9e47c1c4041276e9aaa3d48ebe2e664f728e14fa95ae6c67d57a08b` |

Random owned ports, temporary paths and generated test certificates differ
between runs; rendered-config hashes are per-instance, not deployment hashes.

## Regression and CI record

- Final focused scripts: **58 passed, 43 subtests, 8.73 s** across private
  ingress, evidence worker, field fixture and security workflow tests.
- Full frontend: **1,887 passed in 53 files, 65.96 s**, two workers. Existing
  unrelated React `act(...)` warnings remain.
- Frontend source checks: **38 passed, 1.70 s**.
- Ruff lint/format, bootstrap shell syntax and workflow YAML parsing pass.
  All six existing CI jobs remain present.
- Seven batch75 native HTTP archives remain unchanged, with all **3,852**
  selected source pins matching. The API/kernel/schema is unchanged in this
  batch; those archives and the previous native API run are historical evidence,
  not new database execution. Schema remains 0077.
- The Operations CI job now builds the exact SHA-pinned official Nginx source,
  installs development libraries but not a system Nginx daemon, and runs the
  same owned rehearsal. Its actual report is a required artifact. This workflow
  change has **not** been dispatched or run on Linux in this batch.

## Remaining delivery and scientific boundaries

The fresh read-only issue check still found **38 open issues (#41–78)**. This
batch improves local implementation evidence; it does not satisfy every issue's
remote, independent-human or scientific acceptance criteria.

Before real private intake, authorized operators must review the intended host
Nginx version/effective configuration and all preceding CDN/WAF/APM/logging layers,
including debug logging before location selection. Local log suppression cannot
undo earlier logging. The rehearsal does not attest production TLS options,
HTTP/2, certificates, neighboring live vhosts, host swap/core dumps or cloud
retention. It is not a whole-infrastructure no-retention guarantee.

Next delivery work is exact-revision Linux CI/image evidence and a reviewed
two-file host-policy handoff, keeping private flags off until their gates pass.
Real permitted source evidence, independent 60-event pilot review, empirical
ML/RPS evaluation and approved publication remain separate unfinished work.
