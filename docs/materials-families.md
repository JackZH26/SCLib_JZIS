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
   trusted HTML/URL commands disabled. Keep unknown macros as escaped source text.
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
