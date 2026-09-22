# Website cutover preparation — 2026-09-22

The operator explicitly deferred both ingestion resumption and outbound alert
activation/testing, and requested that website upgrade work continue. This
supersedes the two pending operational questions in the September 21 report.
It does not establish scientific review or waive failed application checks.

## Delivered operating modes

- The production deployment environment now selects
  `SCLIB_INGESTION_MODE=paused` and `SCLIB_ALERT_DELIVERY=console`.
- An explicit paused mode verifies the existing nonempty regular pause marker.
  Freshness retains its measured age and reports `passed=null`,
  `applicable=false`; public and AI availability checks remain mandatory.
  Missing, empty, directory and symlink markers fail admission.
- Console alert delivery uses the repository's receiver-free configuration.
  The SMTP credential is mounted only with the separate email Compose override
  after explicit opt-in. No verification message was sent.
- Existing ingestion guards remain in place. The Discovery feed pull timer was
  also disabled and stopped to preserve the requested collection pause. Its
  prior state was retained privately; the maintenance backup timer stays active.

## Verified revision and production boundary

PR #80 revision `e673df86c2ecb5c6d263f0e747643636bbf732b1` completed
[Test](https://github.com/JackZH26/SCLib_JZIS/actions/runs/35610357807) and
[Security](https://github.com/JackZH26/SCLib_JZIS/actions/runs/35610357607)
successfully, including all eight Linux API batches and capacity checks.
These successes precede the subsequent operating-mode changes; the updated
revision requires its own CI result.

That revision's complete API and frontend images were built on the production
host and started in the owned, internal-network full-data rehearsal environment.
They use the upgraded restored database, separate Redis, disabled background
writers and no cloud credentials. This is a rehearsal, not a signed release
or public cutover. Eight frontend routes returned HTTP 200 with English HTML;
these are server-rendered page checks, not hydrated-browser acceptance.
API health, version, statistics, materials and paper detail returned 200.
The full material response hash remains
`3dc509d9acc8e10247930101534359a1de66ea9c186863031e54e29aba472931`.

The existing Similar route returns 503 because no compatible retrieval
generation has been activated. Search/Ask admit only the explicit lexical
fallback. Accepting that temporary functionality change is a separate product
decision, presented to the operator; it is not inferred from deferring ingestion
and email. Cold material/timeline work remains slow and is not a latency pass.

The fresh production SLO read observed 241,047 public requests with zero errors,
only 2/20 required AI observations, and a retained pipeline age of
1,609,412.923322 seconds. Availability therefore still fails admission on
insufficient AI traffic. The intentional pause reports freshness as deferred.
No artificial traffic, timestamps, scientific approval or index-completeness
receipts were created to pass a gate. Production remains on `d26fc09` / `0043`.

## Local verification of operating-mode changes

- Error-budget/security workflow tests: 26 passed, 6 subtests passed.
- Complete offline suite: 2,309 passed, 97 subtests passed.
- Final timeline/native wire suite: 83 passed; all seven fresh r2 archives bind
  the actual current source (297 or 598 source pins).
- Frontend: 1,895 passed; TypeScript passed; 46 frontend source contracts passed.
- Actual production Compose configuration was parsed in both console and email
  modes: the console mode has no SMTP credential mount; email includes exactly
  the read-only secret mount. No services or outbound messages were started by
  that configuration check.

## Timeline initial display

The initial display now requests at most 2,000 points; an explicit expanded
view retains the 10,000-point option. The API accepts the additional bounded
budget. Coverage totals, unsampled record summaries and dataset version are
computed from the same full eligible selection; scientific filters and the
selected display budget survive navigation in both directions.

The actual complete-data API comparison retained 19,338 eligible results in
both views, with identical full coverage/summary/version. API body sizes were
3,772,935 versus 18,846,439 bytes. The resulting HTML was 4,268,501 versus
20,991,842 bytes (79.7% smaller); actual request times were 17.519 versus 24.852
seconds. This reduces transport and browser work, but **does not resolve cold
backend computation or constitute a latency/SLO pass**.

An actual in-app browser loaded the canary through a private SSH forward. It
showed 2,000/19,338 results, all 321 strata represented, no rare groups omitted,
the full-data summary, SVG compatibility chart and the 2,000-result paginated
table. The logarithmic view control was exercised after hydration. No public
frontend traffic was switched to this canary.

The first frontend invocation ran before refreshed archives were installed and
failed five source-pin assertions; its log is retained. The final run must use
the fresh archives, not weaken those assertions. Operational HTTP probing also
retains the initial host-port connection failure; the internal-network container
and direct container HTTP paths were subsequently verified.

The first new HTTP test incorrectly expected display-specific returned and
available counts to remain equal between budgets. It was corrected to require
unchanged full totals/year bounds/record summary/version while checking the
proper 2,000 versus 2,500 displayed counts in that synthetic case. The initial
failed run is retained; the final 83-case run passed.
