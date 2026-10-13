# MgB₂ extraction failure investigation

The 20 calls were four development versions (3, 5, 7 and 5 calls), including block requests, bounded repairs and split children. They were not 20 complete full-paper extractions. There were 19 complete responses and one output truncation; five complete responses were empty, 14 failed validation, and no candidate row was accepted.

## Independently reproduced evidence

The coordinator received the private Mini forensic capsule and verified all three transport hashes. JSON: `9de08527e16c8bbf4adc4cf03a3a23308cd36b4a2855abdf90b3b8fff2db01d5`, 1,582,798 bytes. Each call was replayed using its original Git revision and validator. All 20 historical error sets/statuses were reproduced, including the incomplete JSON of the truncated response. Failed-call inputs are reconstructed from the frozen source, block plan and prompt implementation; complete prompts were not originally captured. Reconstruction is explicitly declared and does not alter the original receipts.

Of the 14 failed responses, nine had schema errors, five had locator errors and five had other evidence/science errors. These categories overlap. A counterfactual row-by-row replay does not rescue a fully valid MgB₂ row under the current evidence gate. It does rescue one entire row per response in the separate synthetic two-response test; that test still misses another Tc criterion and fails quality acceptance.

## Causes and targeted changes

| Layer | Observed problem | Change |
|---|---|---|
| Model semantics | Correct isotope Tc values coexist with invented pressure/criteria; isotope coefficient is mislabeled electron–phonon λ, and kink energy is mislabeled ωlog. A cited generic Tc is assigned to the current experiment; another numeric value disagrees with its raw text. | Preserve evidence gates, give explicit semantic distinctions, use source-only development checks; do not declare the 9B model competent from JSON validity. |
| Model output contract | The model must repeatedly copy evidence, positions, nested null slots and qualifier objects. There are omitted conditions, invalid roles and contradictory numeric representations. | Add compact `materials-ner-wire/1.0`; model selects deterministic source references. Code copies literal spans, supplies only optional null fields and expands source-number arrays. Storage schema 3.0 stays intact. |
| Prompt/repair | Generic feedback obscures the field to correct; repeated repairs reproduce errors and omit separate Tc criteria. | Prompt 4.0.0, synthetic multi-criterion example and literal source Tc cues, precise missing-field/method paths. Cues are not gold labels. |
| Validation aggregation | One invalid row discards every row in a response. Literal evidence checking does not by itself prove a scientific interpretation. | Quarantine the entire invalid row, retain only fully validated rows of the final response, keep the block failed and coverage incomplete. No dropping erroneous pressures/properties/methods. Require evidence for stated Tc criteria, ambient pressure and raw uncertainty. Cross-row unresolved relationships remain atomic. |
| Runtime | Hydride child exits with SIGXCPU (`-24`), while inherited CPU limits are 360/390 seconds and the paper/guardian wall budget is 900 seconds. Reading the absent final report then raises FileNotFoundError and prevents Cu/Fe/Ni starting. | Use coherent finite CPU/wall budgets, retain original exit/signal before report reads, emit a durable partial-stop receipt, and distinguish quality failure from resource failure. Runtime repair and its receipts are verified on Mini separately. |

The protocol now records exact input blocks/messages and their hashes in every completed or failed-call receipt, plus block input frames in the run report. This removes the need to reconstruct completed-call prompts in later investigations. An interrupted in-flight generation remains explicitly unfinished.

## Verification and limits

Coordinator verification: 122 ingestion tests, 22 API tests on newly created disposable PostgreSQL/Redis, Ruff and diff checks. The pinned tokenizer checks all 331 initial blocks from the prepared 50-paper corpus: 3,021–10,929 input tokens, zero context overflows with 4,096 reserved output tokens in a 16,384-token context. An initial verbose reference catalogue overflowed and was rejected before generation; the final prompt groups original text with deterministic markers.

Implementation hash: `d6c1fa989892ffd14e94b9aec39cb22b2cf56298129b2255524c038c99799162`. Tokenizer receipt hash: `50af227d49a794ca2d7350ae5c08291eb4d46fbe3b394b67de09d812a089d95b`.

The new five-family diagnostic batch must use one fixed implementation, fresh receipts and the same five development sources. Check isotope identity/Tc pairing and unknown criterion/pressure; calculation versus measurement pressure in hydrides; separate ambient/high-pressure cuprate points; pristine/doped iron samples; and nickelate preparation history. These are source-derived development checks, not independent human gold or a formal F1 evaluation. Figure/supplement and corpus rights/family audits remain incomplete. No production material snapshot, scientific approval, cloud comparison or all-50-paper completion is claimed by this repair.
