# Discovery candidate list

The `/discovery` main view prioritizes published candidate materials. A user
explicitly selects a scientific publication before any candidate is shown.
An unavailable catalog and an unpublished catalog retain their different states;
neither is replaced by demonstration data or the historical lead feed.

## Display ordering

Each material already has one explicitly selected representative state and
research action in the scientific publication. The list displays that
representative's existing `assessment.result.score_display` in descending order
within the chosen publication and research role. Null scores follow scored
materials. Equal scores retain publication order. Sorting uses a copy and never
changes the receipt, original assessment rank, policy, weights or selected
representative. A higher-scoring alternative action does not replace the
published representative. RPS remains a research-priority score rather than a
superconductivity probability or physical design-space coordinate.

The default columns are material, research priority, family, selected state and
pressure, and next action. Opening a material inserts its details immediately
below that row. Full state/action text, scientific observations, local review
scope, exact source pins, barrier interpretation and alternative assessments
remain available. Closing details restores focus to the material button.
Optional scientific comparison columns preserve the eight existing native
fields, their units and distinct availability states.

The version selector, search, research role and refresh action share an aligned
desktop control row and stack on narrower screens. Ranking and publication
context are compact disclosures; full campaign and release identifiers remain
inside publication context. This keeps the list close to the page heading
without choosing a version automatically or changing any filter behavior.

## Progressive disclosure

Research plans, host/structure/calculation tools, source studies, methodology,
dictionary and original assessment archives are available on demand. They do
not fill the initial candidate view. Closing a disclosure does not unmount its
form; existing source-identity and page-visibility clearing remain in force.
The Host + Modification + State + Conditions research framework and the
approximately 300 K / 1 atm target are in methodology.

Existing source-study and research-plan fragment URLs reveal their containing
disclosure, including initial visits, history restoration and repeating the
current fragment after manually closing it. Modified clicks, new windows and
links to other pages retain their normal behavior. These display changes do not
publish scientific data, submit calculations or write to the production database.

## Validation

Behavioral coverage checks stable score ordering, unranked placement, unchanged
representatives and receipt order, compact columns, inline expansion and focus,
retained scientific units and scope, disclosure state retention and fragment
navigation. Production build and repository source checks run independently.
Synthetic view-model copies used to test multi-row ordering are explicitly test
data and never enter the production page. Browser acceptance and release gates
remain separate from component tests.
