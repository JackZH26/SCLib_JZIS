# Materials source observations

The Materials detail page can now show additional source-specific quantities that do not fit the retained Tc record. The first finite batch contains 15 field projections from three source cases, grouped into four reading windows. Each projection retains its original value, unit, role, conditions and locator. These are source expressions, not 15 experiments or formally completed catalogue properties.

## Scientific scope

| Source window | Fields | Interpretation |
| --- | --- | --- |
| [Nominal BaFe1.90Pt0.10As2, Hc2 curve](https://arxiv.org/html/0912.2752v2#S3.SS2.p2.1) | −2.8 T/K slope; approximately 45 T WHH orbital estimate; approximately 65 T linear extrapolation; 50% resistive curve criterion; field parallel to c and T < 20 K | The two Hc2(0) estimates remain distinct model results, not direct measurements at 0 K. Pressure is not supplied in this window. Nominal/refined sample correspondence remains unresolved. |
| [Nb0.07-CVS, ambient prose fit](https://arxiv.org/html/2411.18744v1#S3.p3.1) | Tc 4.70(3) K; London penetration depth 316(5) nm; gap Δ0 0.590(5) meV | Source-reported fits. “Ambient conditions” is preserved as wording and is not silently converted to numeric 0 GPa. |
| [Nb0.07-CVS, pressure-series table, 0 GPa column](https://arxiv.org/html/2411.18744v1#S3.T1.2) | Tc 3.000(6) K; λ(T > 0) 381 nm; gap Δ1 0.54(9) meV | A separate fitting context. The source row λ(T > 0) is not relabelled λ(0) or electron–phonon coupling. Its correspondence to the prose fit and selected result is unresolved. |
| [CrB2, COD 1510641, revision 176435](https://www.crystallography.net/cod/1510641.cif@176435) | Two listed asymmetric-unit sites, 24 declared operations, Hall symbol −P 6 2, Z = 1 | Independent 1954 crystallographic metadata. Rounded fractional coordinates remain as printed; declared operations are not independent space-group validation. Missing temperature/pressure does not become a superconducting measurement condition. |

Parenthetical uncertainties are retained in their original notation and normalized from the last displayed digits. Their statistical interpretation is unspecified in the inspected source scope. This is not an assertion that every parenthetical uncertainty is a standard uncertainty.

## View and source association

The independent page is `/materials/source-observations`, linked from `/materials/source-references`. It displays all four windows and offers the public JSON projection and SHA-256 sidecar. Detail-page observations are collapsed by default, after the existing source-recovery or COD results.

Paper additions appear only when the current material response passes the existing recovery metadata contract and contains the expected immutable seed and source identity. Pt requires the actual paper capture; Cs requires both current classification statement identities, content hashes and v1 revision. The API remains responsible for current retained-record fingerprint and eligibility checks. Formula similarity alone cannot activate the additions.

CIF additions appear only after a user opens the lazy COD query and its actual response contains COD 1510641 at `svn:176435`, with the existing unvalidated/sample-unassociated flags. A different revision, missing match, failed request or material switch removes the old observations. The view context identifies the request; it does not establish a physical sample binding.

## Projection and downloads

`frontend/public/research-pilots/materials-source-observations-2026-10-02.json` uses `materials-source-observations/1.0.0`. Its source-expression batch is pinned by SHA-256 `947e13d7947f27d9d291a3783ad262308babcec14c186de0e5fbf1c70b8a884f`. The earlier batch `1bdc386c9f67bfa4a454ee17c07910ee72ee49b0f1adfb656dba56a60735fdd2` is retained separately. The new batch corrects nine CIF quantities: coordinate, occupancy and Z units are derived from named CIF fields, so their `raw_unit` is null and their normalized unit has an explicit `unit_basis` and `unit_source_field`. It does not invent printed units. All values, uncertainties, conditions, source hashes and anchors remain unchanged. The historical `public_release_completed` flag is renamed to `public_release_completed_at_preparation`; it describes preparation, not the future runtime release state.

The browser loads a closed finite field contract. It checks field roles and units, printed versus field-derived unit provenance, signed raw/normalized number agreement, parenthetical uncertainty normalization, required window conditions and ordered integer source locators. It also requires exact recursive agreement with the inspected bundled snapshot, including every entry in a subset export. Null windows, changed values/model/row labels and nested unknown context are rejected. These checks validate the projection and its pinned snapshot; they do not re-read the original paper/CIF or prove scientific validity. Original-byte agreement is checked separately against captured sources.

“Download this observation window” constructs a real JSON Blob from the current validated subset. The exported `material-source-observation-window/1.0.0` retains the current view context, observation identifiers, values, conditions, source locators, hashes and unresolved association. It includes no captured manuscript text, PDF/CIF files or private reviewer context. Downloads fail visibly and can be retried; changing material cannot export the previous material's response.

## Review and append boundary

The batch is AI-assisted source-expression inspection. Formal human review, scientific acceptance, ML approval and canonical promotions remain zero. API/schema/resources, retained claims and ingestion are unchanged. In particular, the existing Tc `MaterialClaim` cannot hold Hc2 slopes, London depth, gap fits or CIF site arrays. The Tc correction endpoint and sampled-phonon adjudication endpoint are not generic property importers.

A future formal append batch needs a field-appropriate property/result object, an explicit source revision and material/sample/state association, conflict handling, an authorized reviewer decision and a replayable audit receipt. Source observations are usable for comparison and source checking now; they are not a substitute for that workflow. A new calculation is appropriate only after a scientific question, input structure, conditions, method and resource requirements are specified.

## Validation

The first batch was independently inspected against its original HTML/table/CIF captures with 310 checks and no material differences. Separate projection comparison confirms all 15 entries remain equal after the preparation-flag rename. Component tests exercise distinct fitting windows, original units/precision, current-window Blob export and material switching; parent integration tests exercise actual seed presence, lazy COD lookup and revision changes. Malformed-contract probes are recorded separately from scientific/source verification.

Build and local-browser checks validate the current source worktree. Only matching committed CI, signed release, deployment and public runtime verification establish an online upgrade; neither local screenshots nor these preparation records claim production acceptance.

## Finite follow-up

`/materials/source-observations/followup` provides the next finite batch, linked from the first source-observation page. The original batch uses `source-only-finite-followup/2.2.0`, SHA-256 `af823526b7c2764c75c116c2d42e48fde3746feac8e5d6635fecaa34f7a41615`. Its public projection uses `materials-source-followup/1.0.0` and the same preparation-flag rename. The earlier checking and unit-fidelity objects remain separate immutable records.

The planned denominator is 29 tasks: 26 contain source expressions and three YScH10 electron–phonon settings remain unavailable after actual official-access failures. Five Pt preparation/specific-heat tasks are additional. Therefore the public batch contains 34 task records, 31 non-null source-expression objects and three unavailable fields. These are not 31 new scalar properties or independent experiments. Four planned expressions retain unresolved local conditions or dataset correspondence; the printed Pt ΔCp/Tc unit needs interpretation separately.

Eight source groups remain independent: YScH10, La/Sm, Sn/In, Sr/Ni, Ba/Pb/Bi, Mo/Tm, FeSe CIF and the extra Pt tasks. Important distinctions include Tm TN=17 K versus susceptibility-derived Tc=24 K; La/Sm preparation options versus an individual anneal; a database 80% fraction versus its unestablished association with dc/ac shielding curves; optical example temperatures versus Tc; and source BCS/100%-volume assumptions versus directly measured electronic specific heat. Missing printed units remain null; explicit field/guide-based normalization retains its basis.

The follow-up loader accepts the fixed bundled projection with exact recursive key/value agreement, finite counts, false authority boundaries and official HTTPS source links. It is a finite snapshot contract, not a generic external importer or source-byte/scientific validator. A changed batch requires new source inspection, checksum and contract tests. A per-group JSON Blob is derived again from this snapshot, rather than accepting arbitrary caller-supplied context. No catalogue identifiers or material admission are inferred from a source label, and independent FeSe crystallography does not bypass a held material lookup.

The view adds readable spacing to a finite set of captured prose phrases. It does not rewrite downloadable source expressions, values, units, assumptions or locators. Common source-window conditions are displayed once; model-specific conditions and separate database rows remain visible with their own fields. Each of the eight follow-up groups starts collapsed and can be opened with the keyboard.

The final follow-up source object was independently checked with 536 source/anchor/semantic checks. Its public entry values, conditions, roles, hashes and locators are compared separately to the captured-source metadata. Source-expression inspection, projection conformance, browser behavior and actual production acceptance remain separate evidence categories.
