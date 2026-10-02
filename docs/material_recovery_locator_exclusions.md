# Recovery of fragments with unusable source locators

The bounded material recovery endpoint previously failed the entire response when a retained fragment had an invalid locator. A request for `mat:nbb1.94` returned `source_locator_invalid`. A subsequent read-only snapshot of its 18 locator descriptors found five section strings with internal control characters; the other 13 descriptors satisfied the locator checks. This snapshot corroborates the error condition without identifying the exact historical failing fragment.

Recovery now validates each fragment in the existing parsing worker before compiling the report. Only these existing locator errors exclude a fragment:

- `source_locator_required`
- `source_locator_invalid`
- `source_locator_span_invalid`

An excluded fragment remains counted as inspected and consumes the original shared chunk and character budgets. The response decrements `chunks_supplied`, increments `excluded_chunks_total`, and records the exact reason and its count. It does not fetch replacement fragments. Valid remaining fragments can produce pending candidates with their original locators and content hashes.

The strict source validator and retained records are unchanged. Locators are not stripped, truncated, reconstructed, or rewritten. Independent integrity errors, including `source_content_changed`, still fail validation. Existing source visibility, withdrawal, and currentness checks still run before recovery. A response with no usable fragments reports unresolved source coverage rather than a finding that a property is absent. Full-paper review, supplement review, scientific acceptance, and database promotion remain false.

Validation on the final implementation passed 50 native recovery tests and 39 focused recovery, handoff, and seed tests. These exercise the internal-control-character condition, mixed and entirely invalid locators, shared read budgets, held sources, unchanged retained data, and propagation of content-integrity errors. The pre-fix synthetic failure was preserved separately. These local checks do not establish that the change has been deployed or that all materials have been assessed.
