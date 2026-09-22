# Isolated research-workbench browser regression

The `frontend-e2e` CI job now runs two distinct suites. The original
`pnpm test:e2e` production-mode public-page assertions are retained with the
isolated server and network restriction described below. The added
research suite exercises every `frontend/tests/e2e/*.visual.ts` file using
synthetic HTTP adapters and the existing isolated development server.
It is not a real backend, scientific pilot, permission grant or Linux image
parity check. The older standalone `ml-pilot-report.visual.cjs` report renderer
is not a Playwright TypeScript suite and is not included by this glob.

## Coverage

The current collection has 42 desktop/mobile cases across nine files:

| Workbench | Interaction scope |
| --- | --- |
| Saved answer history | Exact historical receipts, legacy and private boundaries |
| Research distributions | Explicit preview, uncertain-outcome recovery, access invalidation |
| Pilot participation | Original-file acceptance, protective withdrawal, session changes |
| Pilot reviews | Original-byte replay, field report, joint coverage, declarations and withdrawal |
| ML source rights | Exact resource review, lost-reply recovery and admission clearing |
| ML runs | Independent-account handoff, conditional approval, revocation and recovery |
| Scientific imports | Local files, exact preview, read-only recovery and denial clearing |
| Scientific review | Scoped adjudication, original evidence, bounded impact and recovery |
| Source task operations | Scoped operation, original-key recovery and denial clearing |

Each suite uses its existing synthetic adapter and assertions. An unexpected
external browser origin is blocked and recorded; a passing suite must satisfy
its existing empty-unexpected-request checks. These are browser transport doubles,
not new SQL receipts or extra independent human scientific evidence.

## Run locally

Use already installed project dependencies and the matching Playwright Chromium.
The launcher itself installs nothing. From `frontend/`:

```bash
node tests/e2e/run-research-workbenches.cjs --list
node tests/e2e/run-research-workbenches.cjs
```

By default, each invocation creates and prints a fresh temporary artifact root.
To select a destination, set `SCLIB_RESEARCH_BROWSER_OUTPUT` to an absolute
**nonexistent** directory whose parent already exists. Existing directories,
files and symlinks are rejected; old evidence is not erased for a rerun.
Use the launcher, not the shared config directly: Playwright loads configuration
in multiple processes, while artifact-root creation must happen exactly once.
The individual earlier per-workbench configs remain available for focused QA.

The launcher permits only the optional `--list` argument; CI executes the whole
selected suite with no filtering, no retries, one worker and `forbidOnly`.
The server uses port 32078, binds only `127.0.0.1`, and refuses to reuse an existing
server. If the port is occupied, inspect that process instead of killing or
attaching to it. The shared server copies application source into a fresh
temporary directory, links installed dependencies and does not copy `.env` or
replace the development checkout's `.next` output. Server API configuration is
an inert loopback address; browser requests use the local synthetic adapter.
No production database or provider is started.

## Evidence and boundaries

Each artifact root contains `results.json`, the HTML report and test outputs,
including synthetic screenshots and failure traces. CI uploads the required
`research-browser-attempt-N` artifact, with 14-day retention. Missing output fails
the upload step. A collected test, skipped test, startup failure or generated
HTML file is not a passing interaction: inspect terminal exit and JSON result
counts. An interrupted run must not be called complete.

The isolated development server intentionally uses the existing offline font
hook and an empty base path. This suite therefore does not establish production
font rendering, `/sclib` prefix behavior, deployed CSP or authenticated API/SQL
semantics. Keep the separate production build/public-page suite and
[owned API/migration tests](TESTING_SAFELY.md). A local browser run is not evidence
that the Linux CI job has run. Real scientific review and source permissions
remain independent requirements.

Temporary source copies and browser artifacts are retained locally for diagnosis;
the server's owned child is stopped when Playwright finishes. Do not include real
private documents in fixtures or upload them as CI traces.

## Production-mode public pages

`pnpm test:e2e` separately collects the public `.spec.ts` suites. It builds an
owned temporary copy including the actual `types/` declarations, links already
installed dependencies, then starts that build on `127.0.0.1:3102`. The server
places its unique copy under the ignored `frontend/tmp/` directory and sets only
that copy's file-tracing root to the original frontend directory. This contains
both the copy and the linked dependencies, preventing standalone tracing from
writing outside its output tree on macOS. Standalone output remains enabled;
the original configuration and build directory are not modified. Temporary
copies are retained for diagnosis.
The frontend TypeScript project excludes this ignored `tmp/` directory so
retained test copies cannot become application type-check inputs. The launcher
regression resolves the real TypeScript file set while a copy exists and also
checks that the actual application layout remains included.
The server
refuses reuse, copies no `.env*`, preserves the checkout's `.next`, and passes a
small allowlist of environment settings rather than service credentials. The
normal production font loader is used: this build can download public Google
font assets and fails if those required dependencies cannot be prepared. It is
not an entirely offline build or a new locked dependency installation.

The production `/sclib` prefix, CSP and public OAuth href remain intact. Only
the server-side API base is changed to unavailable loopback port 1. Every public
browser test installs a fixture before navigation that allows same-origin HTTP
only. The one exact `GET https://api.jzis.org/sclib/v1/auth/me` request is answered
in memory with a synthetic anonymous 401, because public pages check session
state on mount. It is never forwarded; other methods, paths and query variants
are not admitted. All other external HTTP requests are aborted and WebSockets
are closed without connecting upstream. Service workers are blocked. Unexpected
attempted egress fails the test even though the request was aborted. A dedicated
negative-control browser case verifies the synthetic 401 and rejection of both
an unknown API GET and a POST to the same session path. It does not call the
live API or exercise real OAuth/email delivery.

The original 11 public auth/privacy/mobile assertions remain, with two added
cases for production headers/prefixed assets/English and actual egress denial.
This is still not authenticated API E2E or proof of deployment. Runtime font
assets are served by the owned frontend; build-time downloads and browser-time
network restrictions are different scopes, not a claimed OS network sandbox.

CI retains `playwright-results.json` and `playwright-report/` in its required
public-page artifact. For local reruns, preserve existing reports by choosing
new absolute `PLAYWRIGHT_JSON_OUTPUT_FILE`, `PLAYWRIGHT_HTML_OUTPUT_DIR` and
`--output` destinations, with `--reporter=list,json,html`. The research launcher
already creates a new root automatically; this public command retains standard
Playwright output behavior unless those destinations are explicitly selected.
