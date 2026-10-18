# SCWiki edge protection candidate

This is an uninstalled release candidate. No production configuration has been
changed. Website content is served by Next.js; the separate FastAPI limiter does
not protect the website's `/api/scwiki/v1` routes.

## Observed topology and proposed placement

Read-only inspection on 19 October 2026 found Nginx 1.24.0 on the VPS, with
`jzis.org` and `www.jzis.org` forwarding website traffic to `127.0.0.1:3100`.
No dedicated SCWiki limiter or explicit real-IP trust directives appeared in the
active configuration. This does not establish whether a CDN exists upstream.

The candidate consists of three files in `nginx/`:

- `scwiki-http.conf`: one shared zone in the `http` context.
- `scwiki-server.conf`: include in the HTTPS website server only, alongside its
  existing TLS, ACME, authentication, interview and ordinary website routes.
- `scwiki-proxy-common.conf`: shared exact-root and slash-descendant proxy policy,
  installed at the include path in the server snippet when a release is approved.

Do not apply the server snippet to `api.jzis.org`, replace the whole active
configuration, or remove any existing service. The normal site generator has not
yet been changed to install these snippets automatically.

## Candidate contract

The exact `/api/scwiki/v1` path and `/api/scwiki/v1/` descendants share a connection
peer bucket: 10 requests per second, burst 20, with excess rejected immediately.
Changing a query, endpoint or supplied forwarding header does not create a new
bucket. Prefix neighbors such as `/api/scwiki/v10` are outside this policy.

An edge rejection returns HTTP 429, JSON code `RATE_LIMITED`, `Retry-After: 3`,
`Cache-Control: no-store` and `X-Content-Type-Options: nosniff`. Three seconds is a
conservative recovery interval, not a reserved future slot; concurrent requests
can consume replenished capacity. Consumers must back off and bound retries.
Rejections can precede any application response, including method validation.
Upstream 429 responses retain their own body and retry guidance.

The limiter uses `$binary_remote_addr`. The proxy overwrites `X-Real-IP` and
`X-Forwarded-For` from that peer and removes alternate user-supplied `Forwarded`,
`CF-Connecting-IP` and `True-Client-IP` values. It does not enable a new trusted
proxy or trust all forwarded addresses. Clients behind a shared NAT/proxy share
capacity. A CDN would require a separate, verified source-address policy and
origin access assessment before treating its header as an end-client identity.
The shared zone is per Nginx instance, not a distributed quota or user account.

## Local evidence and remaining gates

`nginx/rehearse_scwiki.py` takes an explicitly prepared Nginx executable. It uses
owned ephemeral IPv4/IPv6 loopback listeners, a synthetic upstream, then the
existing local preview. It does not reload a service or contact the VPS.
It checks header spoofing, a burst across API paths, independent peer buckets,
retry recovery, unaffected ordinary routes, preserved upstream errors and real
preview GET/ETag/HEAD/OPTIONS/405 behavior. Owned processes are stopped on success
and failure. Reports preserve failed attempts; a successful rerun does not erase
earlier evidence.

The Mac rehearsal binary is Nginx 1.31.7, built in the project runtime with local
PCRE2. Its official source archive matches the Homebrew-published SHA-256; an
OpenPGP signature was not verified. This is not production-version equivalence.

Before release, review a complete candidate against the actual active config,
preserve TLS/includes and rollback files, validate with the target Nginx version,
confirm the origin/client-IP boundary and ensure application ports are not
public bypasses. Production installation/reload and smoke checks require the
specific release approval. The public OpenAPI still correctly states that rate
limiting is not yet a production-verified contract.

Official references:

- [Nginx request limiting](https://nginx.org/en/docs/http/ngx_http_limit_req_module.html)
- [Nginx real-IP trust configuration](https://nginx.org/en/docs/http/ngx_http_realip_module.html)
