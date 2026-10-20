# Five-family NER baseline, 2026-10-13

This is a completed finite development diagnostic under commit 3591929 / prompt 4.0.0 / wire 1.0. It is distinct from the follow-up repaired model run. The coordinator independently verified each transferred report, the original source/block/input/message bindings and every completed call against the frozen original validator. Original reports and failures are preserved.

| Family | Paper | Calls | Output limits | Pipeline seconds | Retained rows | Text blocks processed completely |
|---|---|---:|---:|---:|---:|---|
| mgb2 | arxiv:1602.03211 | 5 | 0 | 191.5 | 0 | False |
| hydride | arxiv:2309.13919 | 5 | 0 | 257.6 | 0 | False |
| cuprate | arxiv:1502.02227 | 10 | 1 | 337.1 | 0 | True |
| iron | arxiv:2408.02511 | 11 | 0 | 581.2 | 0 | False |
| nickelate | arxiv:2411.04896 | 12 | 1 | 568.7 | 0 | False |

There were 43 recorded calls and two output limits. Pipeline time excludes model construction and supervision overhead. Mini reports resource/cleanup checks passed for all five cases; the raw resource receipts remain private on the node. Source/response replay is independently verified on the coordinator, whereas resource-check statements here retain their node-reported scope.

All five families have zero retained rows in the original baseline and in the separately recorded null-slot-only replay. This is a failed quality baseline. The cuprate has complete processed-text coverage but missed known source Tc claims; processed coverage is not claim recall. All five sources also retain figure or PDF-review gaps, so none has end-to-end source acceptance. Empty outputs cannot establish absence of superconductivity.

Follow-up repairs supply unused null slots, give explicit schema choices and unexpected fields, and reject Tc reused as a measurement setting without separate setting proof. A new fixed prompt-4.0.2 five-family batch uses the same sources, model and finite budgets. Its results must be recorded separately. No formal F1, independent-human-gold result, 50-paper completion, production scientific import or Materials snapshot activation is asserted.
