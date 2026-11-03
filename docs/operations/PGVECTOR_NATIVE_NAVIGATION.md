# Native content lexical and formula navigation

Revision `0111_retrieval_navigation_v2` adds deterministic navigation for retained
native revisions. It never rewrites legacy generations, evidence, paper text,
extraction parents or scientific approvals. Source text stays in its immutable
origin. The derived table binds the exact native ID, vector ID and original
record/content hashes, with its own immutable record hash. English full-text
tokens and publication year are computed from that origin by PostgreSQL; formula
terms use the existing `formula-query/1.0.0` normalizer.

Native publication sealing creates navigation in the same transaction. Direct
publication sealing, backend validation and activation independently refuse
missing or inconsistent native navigation. A prior validation cannot bypass the
activation check after an inactive derived index has been rebuilt. Preview work
rolls back the derived rows with the rest of the operation.

The opt-in readers require an exact internal v2 read pin and recheck its current
database identity. They restrict both native and legacy branches to that content
**before** ranking and limiting. English lexical queries use bound parameters,
year and live retraction filters. Formula candidates merge existing retained
corpus navigation with native GIN terms; only small, bounded non-corpus legacy
fixtures use direct retained-text matching. Selected formula terms are checked
against exact retained text. Missing origins, corrupt records, oversized input,
stale pins and inconsistent text fail closed. This navigation selects candidates;
the existing live rights, evidence and final-currentness barriers remain required
before a public result can be released.

`load_text_bindings` validates exact content/origin/text hashes without returning
vector bytes or archive paths. Its inventory and total text budget remain 1,000
members and 8 MiB. No Google service or new embedding call is involved.

Downgrade refuses to drop navigation needed by any active native content.
Inactive deterministic tokens can be rebuilt from retained original revisions;
dropping them does not authorize deleting originals or unique history. The
migration adds only named navigation triggers and indexes; earlier functions,
trigger definitions and rows remain unchanged. Fresh disposable schema rehearsals
compare those objects across empty round trips and verify an active-native
downgrade refusal preserves rows, SQL objects and the physical projection OID.

This component does not switch public routes, publish production content, run
production migrations, or establish scientific/performance acceptance. Tests run
only through the owned disposable-service runner.
