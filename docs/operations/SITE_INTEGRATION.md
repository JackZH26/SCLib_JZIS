# Unified JZIS / SCLib website rollout

This change makes SCLib the root website and retires the former product site.
It does not migrate user data, rotate session secrets, change the public API
prefix, or grant new research permissions. This document is a cutover runbook,
not evidence that production has been changed.

## Audited topology (2026-09-24)

- One `/etc/nginx/sites-available/jzis.org` file contains the main website,
  retired website, API and HTTP-to-HTTPS servers.
- `jzis.org` and `www.jzis.org` currently serve `/var/www/jzis` at `/` and
  proxy `/sclib` to `127.0.0.1:3100`.
- The retired host serves `/var/www/asrp`, including installation scripts,
  download metadata and images. Its `/api/` location proxies port 3000.
- The separate `/york-interview/` private presentation is included from
  `/etc/nginx/snippets/york-interview.conf`. Preserve it and its noindex policy.
- The public API is `https://api.jzis.org/sclib/v1`. The existing Google server
  callback is `https://api.jzis.org/v1/auth/google/callback`; leave it registered
  and operational. Only the browser return destination changes.
- Existing frontend config values include the `/sclib` prefix. Old links remain
  compatible, but update `FRONTEND_URL=https://jzis.org` and
  `FRONTEND_CALLBACK_URL=https://jzis.org/auth/callback` at cutover. Do not alter
  JWT keys, cookie names, Google identities, users, API keys or quota records.

## Release prerequisites

Use the existing exact-revision Test, Security, signed-image, workload identity,
database backup and schema-compatibility requirements. Run the current SLO gate.
The AI availability failure observed during this implementation is a feature
release blocker, not an exemption for the website migration. The Materials
reliability exception from the previous release is closed.

The first root migration is a coordinated release. Automatic deployment refuses
an unconverted main-site configuration before replacing any application image.
Do not merge and rely on an ordinary automatic image replacement to switch Nginx.

Establish a tested, ASRP-free SCLib rollback baseline before the production
cutover. Keep its signed images and routing available. Restoring the old product
landing page is not an acceptable rollback. This prerequisite must be recorded
in the release receipt, not assumed from the availability of old images.

## Candidate preparation (no live reload)

1. Export the active Nginx file into a private release directory. Record its
   SHA-256 and review all server blocks, includes, ACME/verification paths and
   any changes since the audit. Never put `.env`, private keys or account data
   in this repository.
2. Generate a separate file, passing the audited input hash:

   ```bash
   python3 scripts/prepare_site_integration.py \
     --input /private-release/nginx-before.conf \
     --output /private-release/nginx-candidate.conf \
     --expected-sha256 <audited-sha256>
   ```

   The renderer replaces exactly the two HTTPS website blocks. API server
   blocks, HTTP redirects and other top-level configuration remain byte-for-byte
   unchanged. It preserves TLS directives and the private presentation include.
   It never installs files or runs Nginx. Reject unexpected diffs.
3. Validate the candidate in a separate Nginx `http` wrapper with the production
   MIME types, certificates and includes. Run `nginx -t -c <wrapper>`; do not
   reload while testing. Check that no old static root fallback survives.
4. Retain the currently running frontend's `.next/static` contents in
   `/var/lib/sclib/site-migration/legacy-static/`. Only this public asset directory
   is exposed for old open tabs. Do not copy the old site root, `.env`, application
   source, `.git` or server build files into a public alias.
5. Validate the new signed frontend on an unused loopback port before the main
   switch. Use the existing internal API and a read-only smoke test; do not send
   test registration emails or create real accounts for a smoke check.

## Coordinated first cutover

Keep the first cutover under the same release owner as the signed-image release.
Back up the active Nginx file, protected runtime configuration and immutable
image digests before changing them. Retain the ASRP-free rollback baseline.

1. Complete the normal release preflight, backup and schema compatibility checks.
2. Update only the two frontend URL settings. Keep the API host, Google server
   callback and all identity secrets unchanged.
3. Replace the application with the verified signed root-mounted images and
   wait for local frontend `/login` and API health checks. The frontend health
   check is independent of data scans. Keep the cutover window bounded; restore
   the clean baseline if readiness fails.
4. Recheck that the live Nginx hash still matches the audited file. Install the
   candidate atomically, run `nginx -t`, and reload only on success. A failed
   validation requires restoration of the prior config and clean baseline;
   never leave half of the routing change active.
5. Serve the retired host's old pages, scripts, downloads, images and `/api/`
   paths as actual 410 responses. Keep DNS and TLS controlled. Do not redirect
   those unrelated URLs to the library homepage. Retain ACME renewal access.
6. Move the old product/site HTML, backup HTML and `.git` directories to a
   protected archive outside all web roots once the cutover is verified. Purge
   any configured CDN content. Check deployment jobs cannot restore public
   static routing; an old content update alone must not expose the retired site.
7. Prewarm default Materials and Timeline requests if the API restarted. Measure
   cold and warm timings separately and record the data/version identifiers.
8. Save a release receipt with test runs, image digests, original/candidate
   config hashes, account smoke-test results and rollback locations.

Subsequent normal releases may use the existing automatic workflow once the
unified routing is installed. Do not enable a bypass of its SLO checks.

## Acceptance

- `/` loads the search-first library; all public copy, navigation, registration
  and mail templates refer to JZIS/SCLib only. Default UI remains English.
- `/about`, `/research`, `/about/join`, `/docs` and `/docs/data` are real pages.
- `www + /sclib` links redirect to their canonical root destination in one hop.
  Query parameters and percent-encoded paper/material IDs survive unchanged.
- Unknown old paths return a genuine 404. Old auth/email/account paths use
  temporary, no-store compatibility redirects. Current auth pages also use
  no-store and no-referrer; auth queries are not written to edge access logs.
- Current mailbox/Google sessions, email verification, password reset and API
  keys retain their original semantics. Validate with authorized existing test
  identities; do not claim a public page GET proves successful Google login.
- Root and old policy/docs URLs remain reachable. Canonicals and the static and
  sharded sitemaps point to the root website; personal pages stay noindex.
- The API servers and the private presentation continue to work.
- All retired host URLs, including direct downloads, return 410. Main-site HTML
  backups and old product assets are not reachable through static fallbacks.
- Materials order, pagination totals, scientific fields, Discovery publication
  boundaries and research workspace permissions remain intact.
- No claimed performance improvement relies on fabricated counts or hides a
  cold cache. The homepage reads only a bounded cached anonymous stats snapshot.

## Rollback

Use the recorded ASRP-free baseline if a key account flow, business page or
performance check fails. Keep the retired domain on 410. Permanent redirects
may already be cached, so root business paths must remain available during
rollback even if the clean baseline uses the old application prefix. Retain
legacy assets for the bounded compatibility window, then remove that directory
and its Nginx alias together after checking old-client traffic.

The implementation branch and local rehearsals do not satisfy these production
acceptance steps. Record the actual outcome after the feature-release gate and
the coordinated cutover prerequisites pass.
