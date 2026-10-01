# Materials sample-form and returned-window corrections

This iteration addresses two observed defects before claiming the Materials
upgrade complete. It does not promote source candidates or change retained
database records.

## Source-field correction

A read-only AI-assisted audit compared the frozen 41 numeric candidates and two
classification statements with their original HTML captures. Two Pt-doped
BaFe2As2 paragraphs used `bulk` to describe superconductivity or its thermodynamic
character, rather than a physical sample form. The affected historical candidates
were `enrichment:6aef053f54d142ba6e797452196e2cd57575cf14f9351bc8f8e1f95ee6082996`
and `enrichment:657257034fab2f7de8b00c67729421e17733dd1eedae7104d235aeef978d7a4d`,
in original captures 16 and 20 of [the Pt-doped source v2](https://arxiv.org/html/0912.2752v2).
They remained pending, but their field interpretation was incorrect.

`materials-literal-extractor/1.0.1` now requires an explicit physical sample,
specimen or material context for a bulk form. It rejects direct form negation
and ambiguous multiple-material contexts. An explicit single-crystal form is
preferred over bulk-property wording; a parent compound's form is not transferred
to the doped subject.

The original 31 source projections and their rectangular table were regenerated
from unchanged HTML. Before the fix, the reconstruction reproduced all 41 old
candidate identities. After the fix, only the two incorrect bulk candidates were
removed: the current numeric resource contains **39 pending candidates**, five
for YScH10 and 34 for Pt-doped BaFe2As2. All 14 quantity/source/subject/reference
sets and four genuine single-crystal hits remain. Candidate IDs are regenerated
under the new numeric extractor version; a representative legacy reference can
change with hash ordering, while each surviving fact's complete reference set
remains unchanged. Reference associations decline from 141 to 133, not eight
independent experiments.

The current numeric seed file SHA-256 is
`405109c67636a5157cbc9efcf8e4fbbc9570864fdffe097dbb91eb895a72619c`;
its independently sealed document digest is
`810b25f4bec44212efe739a1b03d60bfc83c71cabd89bdfd332b9c1fde70c534`.
The classification seed remains byte-identical and retains two pending statements.
Old 41-candidate resources, reports and captures remain historical evidence in
their original commits; current tests explicitly verify the corrected resource.

The audit also documented unresolved associations: heat-capacity features near
20 K must not become evidence that specific heat measured a 23 K Tc; YScH10's
140–250 GPa calculated stability interval is distinct from its 116 K result at
140 GPa; Cs/Nb ambient-pressure fit and pressure-table values have unresolved
method/state correspondence. Retained references are identity guards, not
approval to assign a source statement to every retained temperature/pressure.
No source, sample, phase or scientific acceptance flags were advanced.

## Returned-window correction

The exact PR head `7840b46769606bc86cd95e448ea192ef17ca678e` failed its real native
API CI case for sparse second-paper recovery. Input reading admitted the second
paper, but lexicographic truncation of more than 100 candidate IDs could drop
its 17.5 K result. This was an output-selection defect, not a missing source or
an invitation to relax the assertion.

Overflow windows now select deterministically in paper, capture and field
round-robin order. That order also puts sparse sources within the first 40 UI
rows. Candidate identities and values are untouched. Numeric candidates,
classification statements and scope findings remain independently bounded to
100 rows; seed merging uses the same policy rather than restoring the old hash
prefix. Complete offline reports remain complete. Numeric returned/omitted
counts refer to candidate facts, not independent observations. Findings without
IDs use a content digest only for ordering; no finding IDs are invented.

## Verification and remaining gates

Fifteen real native API cases passed in 3.11 seconds using owned disposable SQL
and Redis services, including the formerly failing sparse-source case and five
bulk/sample contexts. The retained records were unchanged and cleanup completed.
Eight focused pure modules passed 356 tests and seven subtests in 3.30 seconds;
Ruff passed. Installed-only execution with Python `-S` checked all 361 packaged
Python files and five resources against the frozen repository, 39 numeric/two
classification candidates, and the actual offline MDR Nb/NbN inventories of
19/15 rows. Its wheel was 4,200,009 bytes, SHA-256
`90f10a8cd6bc2da8c02ea9c149c3caef58e958dcee4d3f6aa6382affc1b3d00a`.

Seven unchanged native protocol producers generated fresh genuine R6 captures
in 55.19 seconds. Their 4,123 source pins and five separately verified resources
match the frozen source bytes. All 370 preceding wire archives, 46 preceding
capture/manifest/triage documents and every prior archive assertion retain their
original bytes or occurrence counts; R6 adds seven archives and six assertions.
The focused protocol suites passed 384 cases. The final complete frontend run
passed 2,032 cases across 64 files, its source suite passed 46 cases, and
TypeScript checking and the production build passed.

A separate read-only rerun used the same 19 materials, 2,257 retained records
and 321 source captures as the historical 65-candidate report. It now returns
61 numeric/text candidates with 67 retained-reference associations, withholding
four sample-form candidates in ambiguous local contexts. No semantic facts were
added; each surviving fact's complete metadata and reference set are unchanged
apart from version-bound identity and representative-reference ordering.
Classification remains zero candidates and 122 unchanged review findings.
The private reproducible metadata receipt has SHA-256
`a01ead7cd84989c42c5821da8700fe5f856a17f7c7c2997a0164a2dcac400055`.
This historical-source inventory is distinct from the 39-candidate primary seed.

An independent original-source review subsequently found that two of the four
withheld forms are explicitly bound NbN thin-film descriptions. One passage
compares another NbTiN study, and the other contains `SI` as a defect-layer label.
The blanket multiple-formula guard is therefore too restrictive for those two
literal associations. This R6 checkpoint preserves genuine engineering evidence
but is not the final recovery source: direct target/form association must be
restored, then verified under a fresh source freeze and fresh native captures.

Exact-head CI, signed release and public API/browser acceptance remain separate
required gates. Earlier green checks and the R5 captures do not verify these new
source bytes; R6 protocol captures are not a production deployment receipt.
The source audit is AI-assisted evidence checking, not independent domain review,
a precision/recall benchmark or formal scientific curation. Candidate promotion
remains zero.
