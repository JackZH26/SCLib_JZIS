# Discovery research-cycle identifier: exact secret-scan triage

The PR #146 Security run `37412848199`, job `112104907283`, reported one
`generic-api-key` finding with Gitleaks 8.24.3. A local redacted Gitleaks
8.30.1 scan independently reproduced the same finding over the identical
`--no-merges --first-parent cf3e7ed^..cf3e7ed` commit range.

The introducing commit is `cf3e7ed06ee09d908dcb254a1f2e8aaba4080597`.
Its `frontend/lib/discovery-research-cycle.ts:382` contains a 22-character
ordinary snake-case identifier for the LaH10 pressure-teacher recipe in
`RESEARCH_CYCLE_PILOTS`. The value is omitted here. Its consumer is
`frontend/components/DiscoveryResearchCycle.tsx:176`, where `p.key` supplies
the React article key for the starting research recipes. Source inspection
and an independent root review confirmed that this static display identifier
does not authenticate requests or grant access and is not a credential.
The scanner reported entropy `3.5160277`; the `key` property and identifier
shape triggered the generic heuristic.

Private logs and the redacted review remain outside the repository. The
review receipt SHA-256 is
`04aa76af8909b92a24fb519d549d9ffb58fad0b8b31eebbff3bab7e73d180344`.
The receipt records both scanner versions, exact source and consumer
locations, and hashes of the preserved evidence without the matched value.

Only this observed fingerprint is added to `.gitleaksignore` and the exact
acceptance set in `scripts/tests/test_security_workflows.py`:

```text
cf3e7ed06ee09d908dcb254a1f2e8aaba4080597:frontend/lib/discovery-research-cycle.ts:generic-api-key:382
```

No path, rule, directory, or commit-wide exception is introduced. The
scientific code, data, workflow, and previous exclusions are unchanged.
This review applies only to the immutable finding above; new revisions
must be scanned again. Exact-head CI, signed images, deployment, and public
acceptance remain separate checks.
