# Private research ingress: scoped limits and disposable verification

Install `nginx/sclib.conf` and `nginx/private-intake.conf` together. These are
transport controls, not source permission, account admission, scientific
acceptance or permission to run ML. No private API flag is enabled by this
configuration, and no existing application deadline or byte bound is enlarged.

## Exact upload limits

Public URLs below start with `/sclib/v1/ml/`. Nginx strips `/sclib` upstream.
The application still independently checks each body, source pin, role and
operation. Raw-file sums are not valid JSON/base64 envelope size estimates.

| Exact route suffix | Nginx request-body ceiling | Application budget |
| --- | ---: | --- |
| `pilots/registrations`, `pilots/participation/accept` | 22,435,160 bytes | Two 8 MiB files in base64 plus 65,536-byte envelope allowance |
| `pilots/review-preflight`, `pilots/review-attestations`, `pilots/review-attestations/coverage` | 44,804,784 bytes | Four 8 MiB files in base64 plus 65,536-byte envelope allowance |
| `pilots/review-attestations/evidence` | 130 MiB | Smaller exact binary-frame ceiling: magic + length header + 129 MiB; per-file and total context limits also apply |
| `use/preflight/reconstruct`, `use/preflight/reconstruct/current`, `use/requests/preview`, `use/requests` | 32 MiB | Existing bounded reconstruction envelope |
| `scientific-program-imports` | 24 MiB | Existing scientific import request envelope |

Other routes retain the 20 MiB proxy ceiling; their application ceilings may be
much smaller. Only the eleven exact upload routes above receive larger limits.
Trailing-slash/neighbor paths do not inherit those exceptions. Private pilot,
ML-use and scientific-import controls/recovery paths inherit the privacy policy,
but public research distribution/download paths are not moved into this scope.
Each nested exact upload location explicitly declares `proxy_pass`; merely
inheriting a parent's settings is insufficient to establish its content handler.

The shared upload rate is 12 requests/minute/IP with burst 6. Evidence replay
retains 6/minute/IP with burst 2. Non-upload controls retain the generic rate.
These are gateway protection settings, not empirically calibrated capacity or
per-account scientific quotas. A shared institutional IP can reach the limit;
clients must not infer success from 429 or automatically repeat a declaration.

## Privacy and timeout policy

The shared location-only snippet explicitly disables request and response
buffering, request file-only mode, proxy temporary response files, cache/store,
automatic upstream retry and upstream-error interception. It uses upstream
HTTP/1.1 and ignores `X-Accel-Buffering`, so an upstream response cannot re-enable
buffering through that header. These details matter for chunked uploads as well
as declared lengths. See the official [proxy buffering documentation](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_request_buffering).

Private routes suppress access/error logs at that location. Recovery queries can
contain private keys, and debug logs can include payloads. Responses handled in
these locations, including the tested 413/429 rejections, receive
`Cache-Control: private, no-store`; upstream cache
headers cannot override it. The complete existing security-header set is
repeated because local `add_header` directives otherwise replace inherited
headers on older Nginx. See [header inheritance](https://nginx.org/en/docs/http/ngx_http_headers_module.html#add_header).

Connect timeout is 5 seconds, client-body/send inactivity limits are 30 seconds,
and upstream read/send inactivity limits are 120 seconds, above the longest
current private API operation deadline of 100 seconds. These are **not total
request-duration limits**. Existing application upload/operation deadlines,
including the ML08 JSON upload's 10-second absolute limit, remain unchanged.
A slow upload may still fail at the API; larger proxy allowance is not unlimited
runtime or a guarantee of successful intake. Nginx's [size limit](https://nginx.org/en/docs/http/ngx_http_core_module.html#client_max_body_size)
rejects over-limit requests with 413.

This is not a whole-infrastructure no-retention guarantee. Before enabling
intake, inspect effective CDN/WAF/ingress/APM configuration, body/request logging,
debug logging **before location selection**, custom error-page redirects,
host swap/core dumps, storage permissions and retention rules. Location-level
suppression cannot undo earlier logging by another layer. Use payload-free
application metrics for diagnostics; do not temporarily turn on source-body
logging to debug real research uploads.

## Operator installation and rollout

1. Keep private feature flags off. Review both files and separately retain any
   existing operator-managed configurations for rollback.
2. Install `nginx/private-intake.conf` as
   `/etc/nginx/snippets/sclib-private-intake.conf`, then install the matching
   `nginx/sclib.conf` as `/etc/nginx/conf.d/sclib.conf`. Both should be ordinary
   owner-controlled configuration files, not writable by the application.
3. The bootstrap script installs an absent policy before its dependent server
   file, but leaves existing operator-managed files untouched. It is not an
   automatic upgrade tool: compare existing copies explicitly. The deployment
   workflow does not silently update live host Nginx policy.
4. Run the disposable rehearsal below with the intended Nginx version/modules,
   then validate the **actual effective** deployment configuration and approved
   ingress/privacy conditions. Local temporary certificates do not validate
   production certificate paths, TLS options, HTTP/2, other vhosts or cloud layers.
5. Only after authorized configuration testing/reload and release approval may
   the appropriate application flags and accounts be enabled. Rollback restores
   both reviewed files; verify syntax before reloading. Keep intake off if the
   old proxy cannot safely carry the required bodies.

Do not run the bootstrap or reload production Nginx as part of a test. The
rehearsal never invokes `systemctl`, `nginx -s`, Compose, an API or a database.

## Executable disposable rehearsal

Prepare a trusted Nginx binary with its HTTP SSL and rewrite modules and an
OpenSSL executable explicitly. The rehearsal itself downloads or installs
nothing. Example using already prepared absolute paths:

```bash
api/.venv/bin/python nginx/rehearse_private_intake.py \
  --nginx /absolute/owned-build/objs/nginx \
  --openssl /absolute/prepared/bin/openssl \
  --output /absolute/private-output/new-ingress-report.json
```

The output must not exist. It is created exclusively with mode 0600 **after**
cleanup, containing selected source/binary hashes, observed version, route
results and explicit false application/deployment assertions. A failure produces
no passing report. Reports are immutable historical observations: changed source
or binaries require a new report, not resealing an older artifact.

The standard-library runner starts only owned loopback Nginx/upstream processes
with temporary TLS keys and a verified local TLS connection. It uses the actual
server/location snippets, replacing only listeners, upstream, include paths and
external deployment certificate/TLS-option paths with owned test equivalents.
Every instance passes real `nginx -t` before starting; every child is stopped and
reaped. No account, source corpus, scientific package, provider or database is
used. Payloads are synthetic transport patterns, not valid scientific submissions.

It checks:

- Actual full-ceiling content-length **and** chunked transmission on all eleven
  routes, with independent upstream byte counts and SHA-256 equality.
- Declared and streamed chunked limit+1 rejection; declared oversize rejection
  before the synthetic upstream receives a request.
- Synthetic upstream denial without body consumption, unchanged URL stripping,
  cookie/Origin/participant header forwarding and private security/cache headers.
- Paused in-flight uploads reaching upstream before EOF, with no observed body
  files or open temporary-file descriptors; directory inspection alone is not
  accepted because temporary files can already be unlinked.
- A deliberately buffered synthetic negative control which must expose an
  active temporary file. The observer uses `/proc/<owned-pid>/fd` on Linux or
  `lsof` scoped to the owned child on macOS, with normalized real paths.
- Two 8 MiB responses, exact bytes, no observed response temporary files and no
  response reuse despite upstream public-cache/buffering headers.
- Neighbor/public 20 MiB limits, hidden metrics/admin routes, actual 429 rate
  limiting, and absence of private synthetic markers in the owned proxy logs.

This is transport/privacy regression evidence, not throughput benchmarking,
authentication testing, a real scientific pilot or production deployment proof.
Application authentication and scientific admission still use their separate
[disposable API tests](TESTING_SAFELY.md).

## CI and compatibility

The Operations job builds Nginx 1.30.4 from the exact official source archive,
verifying SHA-256
`4261dc90e9e47c1c4041276e9aaa3d48ebe2e664f728e14fa95ae6c67d57a08b`
before extraction/compilation. It installs development libraries only, not the
distro Nginx daemon, and never runs `make install`. The job runs the same owned
rehearsal and uploads its actual report; a missing report fails the step.
See [official downloads](https://nginx.org/en/download.html) and
[official signing keys](https://nginx.org/en/pgp_keys.html).

Adding this CI step is not evidence that Linux CI has run. Native macOS tests
do not attest the production Nginx package, native libraries or final Linux
image. Keep the reviewed report and exact implementation revision with the
authorized release handoff.
