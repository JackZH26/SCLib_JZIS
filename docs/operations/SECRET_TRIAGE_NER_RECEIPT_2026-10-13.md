# NER preflight digest scan triage

The generic-api-key rule matched line 27 of the MgB₂ investigation document in commit `35919294b89b3b229a2f0704958ec82190966292`. A private local scan reproduced the single finding. Its extracted value exactly equals `receipt_sha256` in `docs/pilot/materials-ner-qwen3.5-9b-tokenizer.preflight.v7.json`.

The receipt digest is the SHA-256 of the canonical public preflight object before adding its digest field. Recomputing it matches. The object contains model/revision identifiers, source manifest and implementation bindings, block IDs and measured input lengths; it contains no account credential or source full text. The value authenticates this immutable engineering receipt and cannot authenticate to a provider.

The ignore entry is restricted to the exact original commit, file, rule and line fingerprint. No rule, directory or entropy threshold is disabled. Actual Mini inference remains tied to the original fixed implementation; this triage changes documentation/scanner metadata only.
