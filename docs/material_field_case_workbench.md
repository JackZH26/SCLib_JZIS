# Private material field-case workspace

The workspace at `/dashboard/research/material-field-cases` uses the existing
dashboard session and current curator/reviewer capabilities. The default-disabled
backend feature flag still applies. The public material detail page provides only
an explicit, non-prefetched link with its exact material ID. It performs no
private capability, authentication or field-case read on public mount.

## Operator flow

1. Explicitly load material cases by exact ID. An optional `material` query
   parameter pre-fills the ID; formula text is never a join key.
2. To create a target, select a scientific field and exact retained record index
   or native entity ID. Load its current context, inspect closure and original
   context SHA, then preview and explicitly save the target. The concise retained
   summary preserves known Tc, pressure, origin and criterion metadata. Generic
   or inline quantities keep raw units; it performs no conversion or pressure
   inference. Stored scalar precision is distinct from printed source precision.
3. Inspect a returned target. Record a bounded source check, including inaccessible
   full text/supplements, interpretation needs, independent references or need
   for new calculations. Full-text and supplement checkboxes start false and
   remain operator declarations. A bounded negative result is not a whole-paper
   statement that a quantity is unreported.
4. When supported by the authoritative field map, load current typed expression
   heads and inspect the exact source revision separately. Values, printed units,
   uncertainty, origin, models, locators and condition roles stay in their source
   window. Proposed existing paper/Work IDs start empty; neither a URL nor formula
   match verifies publication identity. Preview/save appends a pending proposal.
5. A curator can preview withdrawal only of their own current preceding proposal.
   The prior row and scientific source values remain immutable. Other operators
   can append their own views; backend transaction guards arbitrate current heads.

Target, source association and source-check histories remain distinct. Multiple
Tc criteria, fitting models or source windows are not merged. Unsupported typed
fields can still have explicit source-check attempts, rather than invented
expression values. The material adapter withholds source-expression text when
current target/source eligibility fails and returns the actual reasons.

## Integrity and bounded reads

The client hashes exact `context_canonical_json`, `record_canonical_json`, and
request/preview/receipt strings. It does not reserialize source decimals as JS
numbers to generate their original proof. Row proofs bind payload, target,
predecessor, actor, context and expression pins. Detail reads also retain the
original list row SHA. Source revision detail uses the existing v2 immutable
revision/receipt binding. Association and source-check receipts additionally bind
the original verified target context, scientific field and expression chain;
self-consistent rehashing does not substitute for these original pins.

Material paging uses server `next_offset`, calculated from actual returned cases
after complete-row byte trimming. Returned, total and omitted counts are explicit.
Association/attempt histories are limited to their returned window. Source
expressions have a shared material response budget and their omissions are
reported separately; none of these counts denotes independent experiments.

Mutations have a fresh request key and explicit preview/save. Once a save has an
uncertain outcome, writes and scope changes lock. Recovery sends only GET with
the original actor/key/request digest and verifies the original preview and full
immutable receipt SHA. No POST retries automatically. An unavailable receipt
does not prove rollback. Account/auth/material/source changes invalidate stale
responses and scoped drafts. No private data is stored in localStorage.

## Scientific boundary and validation status

Ledger writes append private pending targets, proposals and checks. Public values,
scientific acceptance, selected-result/sample/phase identity and ML approval are
unchanged. Record closure IDs are provenance links, not physical identity checks.
Retained fragment integrity is distinct from declared parent-file hash, rights,
publication revision and currentness.

Focused synthetic tests cover closed payloads and false authority, coordinated
proof tamper, exact saved/unknown-outcome identity, actual returned pagination,
unavailable source checks, read-only access and stale account/material responses.
These are engineering tests, not human or scientific review. Native authenticated
API/browser and production build acceptance were completed locally against frozen
inputs on 2026-10-02. The focused frontend scope passed 33 tests; the full frontend
run passed 46 source checks and 2,192 unit tests across 80 files. The production
build completed static generation 50/50 and the post-build TypeScript check exited
successfully. An independent captured owned-HTTP DTO contract check passed 15
assertions; the final heads-first history behavior has separate current backend
native tests and browser evidence.

An isolated Chromium profile used the owned API's real password login, HttpOnly
session and existing test-only curator grant. The browser created exact retained
targets, source proposals, an own-proposal withdrawal and a bounded unavailable
source check. It kept retained YScH10 116 K/140 GPa separate from the genuine
conference 94.5 K/200 GPa expression; Pt onset 23 K and zero-resistance 21.5 K
remained different retained records, and 250 K crystallography stayed in its own
source window. One actual saved response was deliberately aborted to exercise
original-request GET recovery without repeating the commit POST. This tests
engineering behavior, not the scientific correctness of the synthetic catalogue
or an operator's source-review declaration.

Both 1280 and 320 pixel viewports had no whole-page horizontal overflow. Keyboard
proof expansion and sign-out clearing were exercised. The original mobile image
includes the existing cookie-preferences overlay, so that image alone does not
show the lower field-case content unobscured. An initial browser harness stopped
after expecting a normalized criterion token instead of the correctly preserved
raw `zero resistance` label; its response evidence remains separate from the
successful continuation. Earlier test failures and pre-correction builds are
preserved as historical evidence. No deployment, production or public acceptance
is claimed here.
