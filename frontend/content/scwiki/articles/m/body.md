## Scope

Reliable superconductivity research connects a question to a traceable dataset, a suitable method and an observation that could disprove the proposed answer. This handbook follows six parts of that process: finding data, predicting transitions, screening with calculations, checking claims, reviewing interpretations and reading papers closely. The aim is a reproducible chain of evidence, with the limits of each step visible. [R3](#ref-source-219632ed94597bf3) [R4](#ref-source-158dac7a4c8f8fb7) [R7](#ref-source-d4daeb7c4b4ef52a)

## Mathematical assumptions

For a binary classifier, TP and TN count correct positive and negative predictions; FP and FN count the corresponding errors. With a fixed positive-class definition and test set,

$$
\mathrm{accuracy}=\frac{TP+TN}{TP+TN+FP+FN},\qquad
\mathrm{precision}=\frac{TP}{TP+FP},\qquad
\mathrm{recall}=\frac{TP}{TP+FN}.
$$

These are dimensionless fractions, not transition temperatures or discovery rates. Precision is undefined if no positive prediction exists; recall is undefined if the test set contains no positives. An original teaching example with 34 positive and 966 negative labels gives 96.6% accuracy and zero positive recall when every label is predicted negative. Its precision is undefined. This arithmetic illustrates class imbalance; it is not a fitted superconductivity model. [R10](#ref-source-05f057efe73a6cda)

## M1 — Databases, structures and provenance

NIMS is the institution that publishes SuperCon; the two names should not be counted as independent confirmations. The MDR SuperCon datasheet provides a versioned release with a DOI and a stated reuse license. Record the release identifier and original literature reference when extracting a value. A database row is a route to evidence, not a substitute for checking how the reported transition was measured. The checked Ver.220808 release is an explicit snapshot, not a claim to be today's latest dataset. [R1](#ref-source-4a9ab24336f6fcc3)

ICSD serves a different purpose: inorganic crystal structures support structural identification and calculation inputs, but a structure match does not establish superconductivity. Its access and reuse terms differ from an openly licensed SuperCon release. Check the applicable license before redistributing records. In SCLib, use the [data guide](/docs/data) and [reading guide](/scwiki/using-sclib) to follow retrieved results back to their publications. Preserve the query, returned identifier and retrieval date so another researcher can repeat the search. [R1](#ref-source-4a9ab24336f6fcc3) [R2](#ref-source-7b0fd1ede1525615)

Keep composition, phase, sample treatment, pressure, magnetic field and transition criterion together. Separate records can share a formula while describing different experiments. Conversely, copies of the same measurement across databases are not independent evidence. For model evaluation, related compositions may need to share a train/test group even though their experimental records remain separate; this prevents data organization from silently becoming a claim of independent validation. [R3](#ref-source-219632ed94597bf3) [R4](#ref-source-158dac7a4c8f8fb7)

## M2 — Machine learning for transition temperatures

Composition descriptors and neural representations can help prioritize experiments, but the target and validation design determine what a score means. Stanev and colleagues used random forests for classification and regression; their methods explicitly discuss inconsistent records and missing pressure information. Their proposed materials remain candidates. Predicting a threshold class is a different task from predicting a numerical Tc, and neither guarantees successful synthesis. [R3](#ref-source-219632ed94597bf3)

Pogue and colleagues tested a neural-network approach with both uniform and leave-one-cluster-out validation. The latter exposed much poorer generalization. Their experimental loop combined model suggestions with expert filtering and new measurements. The reported counts are five successes among 190 suggestions and five among 65 after filtering. The printed second percentage is 7.5%; arithmetic from its stated count gives approximately 7.69%. These overlapping selections are not independent randomized trial arms, and the result should not be attributed to the model alone. [R4](#ref-source-158dac7a4c8f8fb7)

In the recommended evaluation workflow, declare the candidate space, grouping rule, held-out data, selection threshold and error metric before inspecting the test results. Report unsuccessful synthesis separately from a successfully prepared sample with no transition in the measured range. Compare against a simple baseline, and retain uncertainty and known family limits when ranking new candidates. The majority-class counterexample above shows why accuracy alone can hide complete failure to identify the desired class. [R10](#ref-source-05f057efe73a6cda)

## M3 — High-throughput first-principles screening

A phonon-mediated screening workflow first specifies composition, crystal structure and pressure, then checks electronic structure, phonons and electron–phonon coupling under stated approximations. A calculated Eliashberg spectral function can inform an estimated transition temperature within that model. It is not a universal treatment of every unconventional pairing mechanism, nor a measurement of a synthesized material. [R5](#ref-source-f080f572de65a123)

Gibson and colleagues report 818 retained calculated spectra after screening and numerical quality checks. Their methods specify commensurate electronic and phonon meshes, smearing, pseudopotentials and numerical cutoffs. They also discuss imaginary modes caused by numerical issues or a mismatch between ideal stoichiometry and experimental composition. Thus, a calculation that converges is not automatically physically valid, while an imaginary mode requires diagnosis before drawing a materials conclusion. Their high-pressure extrapolation remains unvalidated. [R5](#ref-source-f080f572de65a123)

For a new candidate, save the input structure, code and pseudopotential versions, convergence evidence and failed calculations as well as successful outputs. Recheck finalists with tighter settings and the relevant stability assumptions. Report a predicted Tc with its model parameters and pressure rather than adding it to a table of experimental transitions. These workflow recommendations extend the documented calculation controls; they do not certify a new calculation or reproduce the published training run. [R5](#ref-source-f080f572de65a123)

## M4 — Preventing unsupported claims

A DOI helps identify a research object. It does not prove that the linked paper contains the proposed claim, that the claim concerns the right material, or that later work confirmed it. Check the title and authors, then locate the relevant passage, equation, figure or dataset. Crossmark can expose registered corrections and retractions; the service itself states that its presence is not a guarantee. Missing update metadata should not be treated as a certificate of validity. [R6](#ref-source-dedff231d5c3d3cd)

For each factual statement, retain the source version, location, sample identity, observable, conditions and review scope. Distinguish a publisher abstract from selected full text and a complete supplementary-data review. If a source has no DOI, preserve its official URL, title, version or date and, where appropriate, a local file checksum; inventing a DOI would weaken traceability. Versioned data and institutional documentation illustrate why the identifier must fit the source type. [R1](#ref-source-4a9ab24336f6fcc3) [R6](#ref-source-dedff231d5c3d3cd)

Resolve contradictions at the level of the underlying evidence. For example, onset and zero resistance should not be averaged into one transition, and a calculated field limit must not be relabelled as the highest applied field. Mark an unresolved difference explicitly, revise downstream summaries when evidence changes, and keep a correction history. This is an editorial verification workflow, not a guarantee that every indexed claim has already passed it. [R6](#ref-source-dedff231d5c3d3cd) [R7](#ref-source-d4daeb7c4b4ef52a)

## M5 — Peer review and assisted critique

Scientific criticism should test a specific inference. Ask which alternative explanation fits the same measurement, whether a numerical result changes under a reasonable control, and whether the cited source actually supports the wording. A useful review records the disputed claim, supporting evidence and a concrete way to resolve it. COPE guidance emphasizes relevant expertise, declared conflicts, clear scope and constructive feedback rather than personal accusations. [R7](#ref-source-d4daeb7c4b4ef52a)

Model-generated critiques can suggest missing checks, but agreement among several models is not independent peer review or experimental replication. They may repeat the same source error or overlook the same missing condition. Treat each objection as a hypothesis to inspect against primary evidence, and document who performed the substantive verification. A journal's peer-review decision and a wiki's editorial check are distinct events and should be labelled separately. [R7](#ref-source-d4daeb7c4b4ef52a) [R8](#ref-source-e45bc5804b6aaa96)

Follow the actual publisher's confidentiality and AI-use policy when reviewing a submitted manuscript. Nature Portfolio's checked policy retains human scholarly accountability and distinguishes assistance from delegating evaluative judgment. These publisher-specific rules do not establish a universal policy for every venue. For public scientific discussion, preserve the same practical discipline: make the critique inspectable, state its limitations and change the conclusion when a counterexample survives checking. [R8](#ref-source-e45bc5804b6aaa96)

## M6 — Close reading and PDF extraction

Begin with the question the paper claims to answer, its publication version and any linked correction. Read the methods needed to interpret the central observable before summarizing the headline. Build a small evidence record containing the sample label, control conditions, definition of each reported quantity, figure location and remaining uncertainty. Compare the conclusion with the actual result rather than assuming that a familiar title supplies the necessary details. COPE's review guidance also distinguishes reading the manuscript and ancillary material from a specifically commissioned raw-data audit. [R7](#ref-source-d4daeb7c4b4ef52a)

OpenDataLoader PDF is one tool for converting a paper into structured text with reading order and element coordinates. Its documentation describes extraction capabilities; that description does not validate any particular extracted equation or table. Inspect the original page when columns interleave, symbols disappear, subscripts move or a legend changes the interpretation. Keep the original file and extraction version, and link a quoted or summarized finding to its page or bounding box. A parser output is a navigation aid, not the final authority on the paper. [R9](#ref-source-7d4fe3e5598a78a4)

Record unavailable supplements and unresolved version differences as specific missing evidence. A practical reading note separates the author's conclusion, the observation supporting it and the reader's remaining objection. Keep the public summary within the material actually reviewed; if a figure has not been inspected, do not describe its contents from a citation title alone. [R7](#ref-source-d4daeb7c4b4ef52a)

## Experimental criteria

A null observation is bounded by the prepared sample, measurement range and sensitivity. A failed synthesis is not the same result as no superconducting transition in a well-characterized specimen. Complementary transport, magnetic and thermodynamic probes address different possibilities; retain their separate conditions and uncertainty. These distinctions matter both when curating training labels and when deciding whether a model suggestion became an experimental discovery. [R3](#ref-source-219632ed94597bf3) [R4](#ref-source-158dac7a4c8f8fb7)

## Limits and disputes

Selected original methods, figures and official documentation were checked for this handbook. The independent arithmetic examples test definitions and denominators only. Complete scientific acceptance remains open: the published machine-learning models, full supplemental datasets, first-principles convergence and laboratory results were not independently reproduced. Policies and software documentation can change, so their checked date and source must remain visible. [R3](#ref-source-219632ed94597bf3) [R5](#ref-source-f080f572de65a123) [R8](#ref-source-e45bc5804b6aaa96) [R9](#ref-source-7d4fe3e5598a78a4)

## Discovery implications

A productive research loop records both useful predictions and informative failures, then updates the next experiment without erasing provenance. Separate the question “does the method rank this test set well?” from “does it identify a new, reproducible superconducting phase?” The answer to the second question requires evidence about the material itself. [R3](#ref-source-219632ed94597bf3) [R4](#ref-source-158dac7a4c8f8fb7)

## Related topics

Continue with [experimental methods](/scwiki/experimental-methods), [theoretical tools](/scwiki/theoretical-tools), [historical milestones](/scwiki/history), [material search](/materials), and [SCWiki source and interface guidance](/scwiki/using-sclib).
