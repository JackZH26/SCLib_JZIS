# Timeline transfer truncation, 2026-09-24

## Cause and impact

The integration agent invoked `nginx -t` as root with a temporary wrapper at
09:36:57 UTC. It did not specify the active `www-data` worker user or isolated
temporary paths. Nginx defaulted to `nobody` and changed the owner of the shared
`/var/lib/nginx/{body,proxy,fastcgi,uwsgi,scgi}` directories from the service user
to UID 65534. Mode remained 0700. The live worker processes use UID 33.

The first observed permission error was at 09:37:35 UTC. Large API responses
could not spill to proxy temporary files. A Timeline request returned HTTP 200
with Content-Length 3,772,935 but only 64,823 body bytes, then closed. This can
affect other buffered requests too; the observed Timeline failure is not a
claim that no other requests were affected. HTTP-status-only monitoring did
not establish body integrity.

The frontend compounded the issue by converting a failed JSON read to `{}`.
It passed an undefined `points` value to the chart, which crashed on `.filter`.
The agent responsible for the rehearsal acknowledged the cause to the user.

## Immediate production repair

Owner: the integration agent executing the user-requested Timeline repair.
This was restoration of an accidental operational change, not a feature
release, SLO bypass, application deployment or website routing cutover.

- Checked the active Nginx configuration still declared `user www-data;`, and
  live worker UIDs matched 33.
- Required the main site configuration hash to remain
  `30923c925c00926677139d1aeba4ac404711486f3a4d5897168789d90f547523`.
- Required each of the five directories to match the observed bad state:
  UID 65534, GID 0, mode 0700, real directories rather than symlinks.
- Saved a private metadata receipt, then restored only their owner to UID 33.
  Preserved GID/mode and descendants. No recursive chown, reload or restart.
- Restoration completed at 10:13:32 UTC. A follow-up audit confirmed all five
  directory owners matched UID 33, the site configuration hash was unchanged,
  and no new temporary-file permission errors appeared after restoration.
- Receipt location on VPS2:
  `/root/sclib-incidents/20260924-nginx-temp-owner/permissions-restored.json`.

Restoring the broken `nobody` ownership is not an acceptable recovery. If
further faults appear, keep the verified worker ownership and investigate the
specific path or service. The site configuration and immutable images remain
at their existing production revisions.

## Verification and prevention

A subsequent identical public Timeline request completed with all 3,772,935
bytes in 1.20 seconds, parsed as JSON, and contained 2,000 display points and
19,338 full-selection results. Timing is one observation, not a benchmark.
The local browser again displayed the completed chart, full-selection summary
and result table.

The integration frontend now rejects interrupted or malformed successful JSON
responses rather than reporting success. It preserves HTTP error status and
retry guidance, performs no automatic retries, validates Timeline point-array
shape, and presents an error with a filter-preserving retry link instead of a
fabricated empty selection. Frontend changes are separate from the immediate
directory repair and remain on the integration PR until normal release gates pass.

The runbook now requires isolation of all Nginx temporary/PID/lock/log paths,
matching worker identity, inspection of included path overrides, and before/after
checks of live directory metadata. `nginx -t` is explicitly treated as potentially
mutating even when the candidate is never installed.

Local regression validation: 46 source checks and 1,940 component/protocol tests
passed, along with TypeScript checking. The production-mode browser suite passed
its 29 existing scenarios; the added Timeline recovery scenario passed after
scoping its alert locator to the main content (Next also renders a route
announcer). It verifies a failed read, no fabricated empty selection, a document
retry, and preservation of family, origin, source and expanded-display filters.
Three existing API-wrapper tests now return a fresh Response per fetch rather
than reusing an already-consumed body that the former JSON fallback concealed.
