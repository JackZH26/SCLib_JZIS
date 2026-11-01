# Materials families and source notation

The vNext Materials browser uses one **primary browsing family** per source-scoped
material. The existing `materials.family` column stores a controlled value;
`material_semantics.family_classification` records the rule, version, original
formula hash and notation status. Original formulas, sample identities, Tc,
conditions, evidence and admission decisions remain unchanged. The current CSV
snapshot does not include this new browsing annotation.

## Scope and precedence

The controlled vocabulary and English labels live in `services/materials_family.py`.
Frontend options are checked against this vocabulary. Classification is deterministic
from the reported formula, never Tc, ambient-pressure assumptions or model labels.
It is a derived search annotation, not a statement extracted verbatim from a paper.

Recognized molecular donors, cuprate aliases and explicit interfaces are handled
before element rules. An explicit list of established heavy-fermion and kagome hosts
precedes chemical families; merely containing Ce, U or V is insufficient. Specific
oxide/iron/MgB2/borocarbide/fullerenic hosts precede broader composition groups.
The fallback groups do not assert conventional or unconventional pairing.
For example, K2Cr3As3 belongs to other pnictides, LaONiAs is not a nickelate oxide,
CeH9 is a hydride, CeRu2 is an intermetallic, and intercalated FeSe retains its iron
chalcogenide host classification. Family membership does not establish structure,
phase purity or heavy-fermion behavior for every specimen.

Primary literature anchors include [Pb-Bi2212](https://arxiv.org/html/0707.1755v2),
[CeCoIn5](https://arxiv.org/abs/cond-mat/0103168),
[CeCu2Si2](https://arxiv.org/abs/2105.12394),
[CsV3Sb5 and related hosts](https://arxiv.org/abs/2011.06745),
[KV3Sb5](https://arxiv.org/abs/2012.09097),
[BiS2 layered hosts](https://arxiv.org/abs/1207.3558), and
[K2Cr3As3](https://arxiv.org/abs/1412.0067).
Further host assignments require source review and a new classification version.

## Formula audit and correction policy

1. Render supported TeX in material names and all scientific free text, with
   trusted HTML/URL commands disabled. Resolve paper macros from the pinned source;
   unresolved expressions receive an English review label and retain the source link.
2. Preserve variable stoichiometry, isotope notation, phase prefixes, interfaces
   and sample distinctions. Do not replace x or oxygen delta with guessed values.
3. Distinguish lexical limitations from chemistry errors. A paper-defined L or M
   site, a molecular abbreviation or an unexpanded macro is not proof of an error.
4. Queue unresolved notation and suspected extraction errors with paper, formula
   and record IDs. Check the original source and macro definition before resolving
   them. A chemistry correction must use the source-backed correction workflow;
   a display change cannot silently overwrite evidence or merge material IDs.
5. All entries receive a known family or explicit `unclassified`. Stale provenance
   after a formula change reads as unclassified until classification is refreshed.

For arXiv:0707.1755v2, the title and Table I support
Bi(2-x)Pb(x)Sr2CaCu2O(8+delta): sample 1 has x=0.28 and Tc=93 K; samples 2 and 3
have x=0.27 and Tc=85 and 83 K. These are separate sample results with a shared
variable formula. Rendering, not chemical substitution, fixes the reported issue.

## Release acceptance and continued review

- Check migration and rollback on an owned disposable database; retain unrelated
  semantic keys and legacy material labels. Check new-intake and replay paths.
- Check family filters, counts, pagination and details against the same admission
  scope. Missing or stale labels must appear in the Unclassified filter.
- Check the screenshot cases, additional formula styles and hostile/unknown TeX;
  no HTML execution, inferred macro definitions or mutation of source strings.
- Audit every currently published material expression; publish counts by category
  and a review queue. Report coverage separately from scientific accuracy.
- Compare query plans and public-page timing; do not cache away immediate withdrawal
  checks. Verify full download snapshots only when requested, keeping browsing fast.
- Review the queue incrementally by recurrent source pattern, prioritizing frequent
  custom macros, descriptive prefixes and ambiguous sample compositions. Promote
  only evidence-backed corrections; unresolved cases do not block this release.

## Source-bound display repair (2026-11-01)

The API keeps every original field and adds a sparse `display` object. Apply an
entry only when assertion ID, material ID, paper, source revisions, evidence-bundle
SHA-256 and the original field hash all match. Source TeX is parsed offline as a
bounded literal-macro subset, never executed. Conflicting definitions, recursion,
unsupported defaults and external-file commands fail closed. PDF Symbol glyphs
are decoded only after checking the actual source font (including embedded font
names); other glyph corrections require a recorded source-page review.

The checked-in registries contain short derived strings and their definition,
font or source-review provenance. `scripts/build_materials_display.py` rebuilds
them from the public read model, immutable dataset and retained source cache.
It preserves parameters, vacancies, oxygen delta, isotope/phase notation and
all numerical observations. This projection is not a new composition measurement
or a replacement for the original evidence or immutable CSV snapshot.

`frontend/scripts/audit-materials-display.mjs` runs the actual display renderer
across every nonempty formula, composition, quantity, sample, substrate, method,
criterion, condition and title. It reports unresolved expressions and visible
commands, private glyphs and control characters separately. Require zero visible
leaks and no unexplained formula failures before release. Review any fallback;
a passing fallback scan alone is not a scientific accuracy assessment. Source
fixtures include PCCO, BaFe1.8Co0.2As2, PDF oxygen delta, vacancy notation, clipped
math delimiters, subscripts outside math, units, and prohibited commands.

After this audit, `scripts/build_materials_display_families.py` derives compact
search/family annotations from resolved formula text. Migration 0106 checks the
original formula hash and each assertion's pinned source before applying them,
retains previous semantics for rollback, and preserves unrelated keys. It adds
no columns and changes no claim, pressure, Tc, admission or sample identity.
PCCO is consequently displayed as Pr1.85Ce0.15CuO4 and browsable under Cuprates;
search also includes the source-resolved formula. Unresolved chemistry stays
Unclassified. Rebuild and rerun this audit for each new NER release; do not copy
macro definitions between papers or treat review-queue entries as applied fixes.

Source fidelity does not establish chemical correctness. In 1207.5070v3 the
experimental paragraph labels its sample Bi2212 but omits Cu's subscript in the
formula; 2210.02124v2 explicitly defines and reports CuCa2. These seven results
retain the literal source compositions and show a source-bound stoichiometry
review note next to the material. Do not silently infer or swap their occupancies.
