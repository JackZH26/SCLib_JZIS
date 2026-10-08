# Discovery source103 evidence cards and provisional support

This increment implements the first two research-plan batches for the public Discovery source catalogue. It creates a dossier for each of the 103 exact source states and a provisional P/E/N presentation. It performs no new scientific calculation, independent reproduction, experiment, formal RPS assessment or publication of a first-discovery claim.

## Frozen inputs and regeneration

The original public source catalogue remains byte-identical (SHA-256 `4a9089bc569f99ad7f5f469280814fb22bfcc86252b1fb7c1e1be446f8bcac98`), as do its 103 original detail files. Source Tc values, model, μ*, direction, unknowns and 280 control occurrences remain unchanged.

Run `python3 scripts/build_discovery_evidence_cards.py` from the repository. It requires the frozen source hash. The output is the versioned companion index `frontend/public/research-hypotheses/2026-10-08-evidence103-v1.json`, its byte/hash pins, and one independently pinned dossier per state under `evidence-cards/2026-10-08-evidence103-v1/`. A new source or substantive rubric revision requires an explicit new version, rather than silently reusing these inputs.

Each dossier has prior work, bottleneck, proposed contribution, next action and a falsifier. Prior summaries and case-specific context are copied from the retained source assessment, with an explicit non-exhaustive search boundary. All states are E1 (published source theory). Auditing source output and assembling comparisons are not independent E2/E3 evidence. All exact experimental status and search completeness fields remain unresolved/unknown. Other-phase experiments remain context, not validation of the proposed phase.

## Provisional ordinal P policy

`discovery-provisional-support/1.0.0` uses the versioned provisional common profile: stability20, electronic20, pairing25, coherence15, geometry10 and competition10. These percentages are policy weights, not measured causal contributions. Mechanism-specific profiles and campaign mixtures are not inferred automatically from a formula.

The rubric records an explicit anchor, target correspondence and quantified coverage for each axis. Unknown evidence retains the policy support interval [0,100]. Missing weight is never reassigned. Source coupling and source isotropic Eliashberg Tc form one correlated pairing chain and are never counted as separate independent axes.

For the narrow goal of testing the source pairing response, the sole quantified axis is pairing. Its **uncalibrated policy-derived ordinal** anchor [25,50] yields P bounds6.25–87.5 and weighted quantified coverage25%. These bounds are neither physical measurements nor calibrated potential, success probability, predictive accuracy or confidence intervals. The source contrasts do not quantify a causal geometry intervention, physical bandwidth, mobile carrier density, target-condition coherence, global phase retention or competition. Consequently all 103 remain C (exploratory), with overlapping bounds and no fine ranking among them.

For approximately300K at ambient pressure, none of the source chains corresponds directly to the intended target. All six axes remain unknown [0,100], weighted quantified coverage0%, and the label is **no direct support**. This is not a physical-impossibility judgment or a deduction that every phase of the composition has the source Tc.

The implementation supports explicit future independent/robust positive anchors [50,75]/[75,100] and scoped adverse anchors [0,25]. These are also provisional policy assumptions, not calibrated quantities. The tentative A/B cutoffs75/55 require independent evidence (E3/E2) and relevant coverage (100%/75%). Any explicit adverse axis prevents a high aggregate from producing A/B. Unknown identity yields U. Old support3/4 never converts to P75, and formal RPS remains a separate action/budget assessment.

## Counterevidence and group sorting

The generator extracts only explicitly target-oriented stored numeric controls. It preserves the original control index, original reference, quantity/unit, separate Tc direction and claim scope. It handles explicit target-minus-control fields and reverses fixed-A/fixed-B fields only when the target identity is known. Selected-control discordance is included with an explicit selected-source origin and null countercontrol index; duplicates already retained among alternative controls are omitted. It never derives adverse evidence from the presence of hydrogen, technetium, magnetic elements, a concern tag or a missing field.

At this version 53 states have 101 explicit limiting comparisons:74 joint adverse comparisons (both coupling and separate source Tc lower than an alternative) and27 discordant comparisons (coupling and separate source Tc move in opposite directions). These counts refer to source comparisons, not independent experiments. They limit a particular comparator or a monotonic explanation; they do not reject a composition, establish geometric causality or become negative evidence for all possible300K mechanisms.

For the source-response goal the default ordering groups C/E1 exploratory rows without these explicit comparator limits, then C/E1 rows requiring alternative-control review. Within the overlapping support bands, formula and source identity resolve ties. This is a transparent research grouping, not a calibrated potential ranking. Source Tc and concern tags never set priority. For the300K goal the source comparator groups are inapplicable and every state retains formula order. Formula order is also independently selectable.

Real retained examples underpin the contracts: Nb6GaSb loses to AlNb6Sb but beats Nb6GaRh; TiZr3 has lower coupling but higher Tc than Zr3Lu; TiZr has an empty element-risk-tag list while retaining its23.25meV/atom source free-energy and sampling limitations. The source evidence and dossier preserve all these observations. The extraction covers numeric comparator limitations; it does not claim that every physical bottleneck is exhaustively machine-classified.

## UI and verification

Design audit: redesign-preserve, using the existing native CSS/React foundation and SCLib sage/green palette (surface white, ink `#253c2f`, muted `#52675b`, accent inherited from `--accent-deep`). Design variance2, motion1 and information density7 suit a research catalogue. Page slug, title/navigation, brand, existing tab/anchor IDs and source attribution stay intact. Static rows, native controls/disclosures and focus restoration remain the interaction pattern; secondary filters and repeated explanatory text are reduced. No new dependencies, font, imagery, animation or theme changes are introduced.

The candidates tab preserves one closed row per material. Rows show C/E1, source Tc and concise concern/alternative-control information. Search and target stay visible; secondary concern/order/page-size fields start in a closed disclosure. Explanations, prior context, policy bounds and next actions appear only when expanded. Research/tools remain in the separate existing tab. The initial projection includes summaries and pins, not full dossiers. Expanding a row lazily fetches and verifies its original source detail and companion dossier; a failed hash/identity check hides unverified detail content and exposes retry. Keyboard focus, pagination, English labels and responsive table scrolling remain intact.

Contract tests cover103 unique state/composition identities, all103 dossier hashes, frozen source equality, Source Tc retention, unresolved experimental/novelty fields, unknown coverage, old-score isolation, adverse-vs-high-aggregate behavior, target correspondence, countercontrol direction, deterministic goal-specific ordering, duplicate/cross-material rejection, public-field privacy and English defaults. Browser acceptance covers closed rows, lazy evidence, research-tab separation and desktop/mobile horizontal scrolling.

Remaining scientific work: execute independent matched calculations, resolve target-specific stability/competition/coherence, freeze future benchmark comparisons before their outcomes, calibrate ordinal policy against held-out outcomes, and obtain exact-state experimental evidence where possible. No current C/E1 group is promoted by merely completing this UI increment.
