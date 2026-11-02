# Public content identity boundary

`index-read/2.0.0` identifies a content snapshot, physical backend build,
activation event, content manifest, query-policy artifact and exact retained
embedding profile. It never invents a provider generation or resource for
native content. Its formatter accepts the internal database-resolved v2 pin;
a caller-supplied public mapping is not authorization. Both server and browser
parsers reject mixed fields and incompatible embedding spaces. Browser parsing
returns a frozen detached copy and grants no scientific or source authority.

The v1 class, formatter, default fields and serialization remain unchanged.
Retained v1 answers and receipts must continue to use their original format.
The public Search/Ask/Similar response models and routes deliberately still
use v1 until scientific bindings, mixed evidence, v2 saved-answer history,
lexical/formula navigation, currentness, and the complete read coordinator are
implemented together. Merely widening a response type would bypass those
remaining integration gates. This component does not switch production or
start the seven-day observation period.

Validation uses fresh owned disposable API test services plus browser parser
regressions and TypeScript checking. Full-corpus timeout acceptance remains
separate from structural protocol validation.

`PgvectorQueries.query_many` adds the Similar transport boundary: one to twenty
source vectors, one outer request deadline, the same process-wide SQL semaphore,
ordered all-or-nothing results, and cancellation/await of all unfinished sibling
queries. Queue and pool waits consume the outer budget. Invalid complete input
is rejected before any SQL starts. Real owned-database checks cover twenty-vector
filter/exclusion semantics, queue exhaustion, table-lock contention, recovery of
connections/permits, and caller cancellation. This transport does not yet wire
the public Similar route or claim full-corpus batch latency acceptance.
