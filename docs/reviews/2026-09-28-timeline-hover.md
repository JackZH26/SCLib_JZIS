# Timeline hover refinement

Reading this as a preserve-brand refinement of a scientific data explorer for
research readers: restrained colour, clear type hierarchy, and progressive
disclosure. Design variance 3, motion 1, hover density 3.

The previous hover inherited each family's saturated marker colour and joined
up to three complete provenance records into long lines. The surrounding SCLib
Inter typography, green branding, family colours, symbols, routes and existing
keyboard-accessible results table are retained.

Hover labels now use a white background, a light sage border, left-aligned
13px dark text, bold material/Tc, and a quieter inspection hint. Material names
are bounded with explicit ellipsis and balanced wrapping. Single points retain
Tc, plotted year, origin, pressure qualifiers and current visibility. Overlaps
show received-result/source counts and origin; mixed visibility summaries count
all members rather than describing the cluster with its first member's status.
Long source IDs, date bases, source roles and complete provenance remain in the
existing selectable table. No scientific records, numeric values, classifications,
colours or selection identities are changed. Input text is escaped after wrapping.

Validation: 31 targeted Timeline/component checks, 46 frontend source checks,
and TypeScript checking passed. Browser inspection with live read-only data at
1280px and 390px confirmed light single-point and overlap labels, legibility,
viewport fit and marker-to-table selection. A three-result overlap retained all
three table members and its linked source. No dependencies or production service
configuration changed. This is an integration-branch preview, not a production
release.
