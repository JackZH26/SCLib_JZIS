# Scientific import workbench

Route: `/dashboard/research/imports`. Scope: private curator operation over the
existing [pending scientific importer](SCIENTIFIC_PENDING_IMPORTS.md).
Issues: [ML05 #67](https://github.com/JackZH26/SCLib_JZIS/issues/67) and
[UX02 #73](https://github.com/JackZH26/SCLib_JZIS/issues/73).

## What this workflow does

The workbench makes the already implemented, bounded QE matdyn import available
without manually encoding an API request. A curator selects actual local source
bytes, independently supplied hashes and an existing material binding, inspects
a rollback-only preview and separately commits the same package. It does not
run QE/DFPT/phonopy, fetch a URL or program input path, create materials or infer
pressure, phase, simulation temperature, scientific approval or source rights.

Only the existing sampled `phonon_min_frequency` adapter is supported. This is
not a full-Brillouin-zone stability measurement, a superconducting label or a
universal cross-family ranking feature. Signed native observations and absent
uncertainty remain governed by the existing parser. Nothing in this UI expands
the frozen scientific registry or admits an ML example.

## Operator sequence

1. **Refresh curator access.** Admission requires a current explicit curator
   grant and an enabled research feature gate. An ordinary administrator flag
   is insufficient. The capability response identifies the current account,
   grant and installed compiler hash; all six scientific/source/ML authority
   flags are false.
2. **Inspect material.** Enter an existing material ID. The read returns its
   current formula and complete-row SHA-256 without exposing the complete row.
   This pin binds the import target; formula agreement does not prove phase or
   sample identity.
3. **Load local manifest.** Select the original canonical UTF-8 package manifest
   and enter its independently supplied SHA-256. Loading reads only local bytes.
   The workbench requires exact sorted-key, whitespace-free canonical JSON with
   no BOM or trailing newline. Duplicate keys, noncanonical number spellings,
   invalid Unicode and extra fields reject; the UI never silently repairs them.
   This is deliberately narrower than arbitrary JSON formatting accepted by
   other clients. Use the existing package workflow to prepare the source, not
   a hash copied from an untrusted replacement.
4. **Select source files.** Choose one file for each logical inventory entry.
   Physical filenames may differ, including content-addressed `<sha>.bin`
   captures. Actual bytes must match the manifest size and SHA-256. Logical
   references sharing a hash remain distinct, but the upload stores their bytes
   once. No browser directory traversal or automatic URL fetch is performed.
5. **Optionally select FC.** Provide the actual force-constant file, its logical
   `flfrc` basename from the native input, and its independent SHA-256. Do not
   substitute the physical content-addressed filename for that logical name.
   All three may be empty; unavailable validated coordinates yield quarantine,
   not formula-derived coordinates.
6. **Preview pending import.** This is the first explicit source upload. The
   server exercises its real parser and transaction path, then rolls back all
   writes. Proposed UUIDs are not durable lookup targets and no result-review
   link is shown for a preview. Editing any binding, file or pin invalidates it.
7. **Commit exact preview.** The UI rechecks account, grant and compiler, sends
   the same request key and actual byte/context body, and includes the preview
   package pin. The server checks that pin before the durable-start boundary.
   Double clicks cannot launch a second concurrent submission from this UI.
8. **Inspect the receipt.** A committed `success_pending` result remains pending
   scientific review. Its actual property ID is shown with a link to the
   existing evidence inventory; that link is not an implicit review or a claim
   that the general inventory route supports a property-ID deep link.

## Package identity and compatibility

`expected_manifest_sha256` is SHA-256 of canonical manifest bytes. Source hashes
are hashes of the actual original program-file bytes. Browser preparation uses
UTF-8 byte lengths, not JavaScript string lengths, and preserves the original
logical inventory order.

The independent augmented package key, `expected_request_sha256`, is different
from a hash of the HTTP body. It binds the versioned manifest/context, their
hashes, the installed compiler-inventory hash and the complete augmented file
inventory. It excludes the operator key, actor, dry-run flag and base64 transport
format. The browser derives this key independently from its closed local inputs
and the authenticated capability compiler pin; actual Python-to-browser fixture
parity tests verify the construction. Native reports contain floating-point
values and are not reserialized through this integer-only metadata codec.

The new POST pin is optional for compatibility with old clients; this workbench
always supplies it for both preview and commit. A mismatch returns a sanitized
409 before starting an import. This closes the previous gap where a compiler
change between preview and commit could create a different package from the same
selected source files.

The existing compiler inventory includes `scientific_pending_import.py`, so
this additive service update changes the compiler hash for newly prepared
packages. It does not rewrite old retained packages or outcomes. An old package
receipt can still be recovered by its original key and pin, without requiring
the current compiler hash. Replaying execution under a different installed
compiler is not silently treated as the same old package.

## Unknown outcomes and private state

The existing two-stage process is retained:

`current authorization → durable source/attempt start → bounded pure parser → atomic pending rows/terminal`

An unsuccessful HTTP acknowledgement cannot establish whether the start or
terminal committed. The browser locks new imports and exposes only the original
account, request key and package pin. **Check original outcome** performs a
read-only GET, never another upload, worker resume or failure write.

| Observed state | Meaning |
| --- | --- |
| GET 404 | No original actor/key was observed in this snapshot; an in-flight request may still commit |
| `outcome_unknown` | A durable start exists but no terminal was observed; neither success nor failure is inferred |
| `success_pending` | Pending result rows and terminal were recorded, not scientific acceptance |
| `quarantined` | Source/attempt history and reasons retained; no new canonical result rows |
| `failed` | A technical failure receipt exists; no partial canonical result rows |

There is no automatic polling or write retry. This increment intentionally does
not provide a browser resume button. A current authorized operator can use the
documented existing API workflow with the original complete package when an
explicit recovery action is appropriate; a new key is not an automatic fix.

Authentication changes clear File references, base64 drafts, bindings, previews
and receipts. Only the opaque original-account/key/package locator survives in
memory. A replacement current curator grant for that same account may inspect
its old receipt, whose historical grant is unchanged. Other accounts cannot
reuse that locator through the new actor-scoped endpoint. An invalid or delayed
response cannot repopulate an obsolete view.

Keep the page open while unresolved and retain the references in the approved
private operation record. No localStorage/sessionStorage/IndexedDB is used.
Full-page unload warnings do not intercept every client-side navigation. Reload
or navigation loses this in-memory locator; the original package and private
operation records are still necessary.

## Added API surface

All paths below are under `/v1/ml/scientific-program-imports`.

| Interface | Closed contract |
| --- | --- |
| `GET /capabilities` | `scientific-import-capabilities/1.0.0`, actor/grant, read/import capability, compiler SHA and six false authority flags |
| `GET /outcome?request_key=...&expected_request_sha256=...` | Exact current-actor/key lookup and independent package pin; existing attempt DTO with `replayed=true` |
| Existing `POST` | Adds optional nullable `expected_request_sha256`; checked after byte capture but before durable start or parsing |

Recovery requires exactly two unique query fields. A 1,024-byte raw query limit
runs before framework query parsing; overlimit requests return a generic 413,
including before authentication. Normal private GETs use current session/grant
checks and read-only repeatable-read snapshots. Missing/foreign original keys
return the same 404, and wrong package pins return 409. Neither response grants
retry authority. The historical attempt-ID inspection endpoint retains its
existing curator-access policy; it is not relabeled as actor-private.

## Bounds and displayed evidence

The browser validates sizes before reading large files: manifest 64 KiB, 2–16
logical originals, each original 4 MiB, manifest plus unique original bytes
8 MiB, and optional FC 8 MiB. Canonical base64 expansion must fit the existing
24 MiB request limit. Access/binding responses are limited to 4 KiB and import/
outcome responses to the existing 8 MiB ceiling. API calls are abort-bounded at
55 seconds in the browser; existing server/worker/recovery budgets remain
independent and cancellation does not imply SQL rollback.

The UI validates closed envelopes, exact package pins, false authority flags,
status/row consistency and limited report semantics. It projects only bounded
status/reason codes, IDs, package pin and parser-worker times; it never renders
the raw native report. The report hash is a server receipt identifier, not a
claim of browser-verified raw-report integrity. Historical worker times may
differ from a new preview; calculation CPU, wall and monetary cost remain null,
not zero. No simulated data is injected into public material or discovery rows.

Tests use owned synthetic native-format files through actual disposable SQL and
HTTP. No real import, source-rights decision, scientific adjudication, model
training, production migration, deployment or remote issue closure is implied.
