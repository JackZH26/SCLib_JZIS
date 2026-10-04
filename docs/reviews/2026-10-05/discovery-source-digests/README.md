# AB₂H₂₄ source-token scan review

Security run [37226203328](https://github.com/JackZH26/SCLib_JZIS/actions/runs/37226203328)
reported 84 `generic-api-key` matches in the 21-row published prediction table.
Every match is the SHA-256 of a public chemical formula or printed numeric token.
These are content checksums, not credentials. The introducing commit, exact file,
rule and line for each finding are retained in `secret-triage.json`.

The CI SARIF (Gitleaks 8.24.3) and a local replay (8.30.1) have identical finding
sets. All 84 checksums were recomputed against the frozen paper text at their
declared Unicode offsets, then against the literal values in the public JSON.
The original JSON and frozen text hashes match the existing source pins. No
scientific data or historical source bytes were changed.

Only these exact fingerprints were added to `.gitleaksignore`. There is no
path, commit or rule exclusion. A new source revision or different introducing
commit does not inherit these exceptions. The workflow tests pin the original
JSON bytes and each exceptional line, and recompute all 84 token checksums.

Local verification: the full workflow contract suite passes (18 tests, one
existing optional-tool skip). Both the original introducing-commit scan and
its complete ancestor-history scan are repeated with the exceptions applied.
The current GitHub head still requires its own successful Security and Test
checks before an ordinary merge. This review makes no scientific acceptance,
model validation or production deployment claim.

## Downstream LaH₁₀/LaD₁₀ pressure table

Scanning the downstream commits found 56 further matches in the seven-row
pressure table introduced by `97c2d5f00c443f9a67f59d4ad15ec5c687d06406`.
`lah10-secret-triage.json` records their exact fingerprints. All 49 numeric
tokens and seven formula tokens were independently recomputed from the frozen
arXiv text at their retained offsets and from the public JSON. Only those exact
lines are excepted. The expanded workflow suite passes 19 tests with one
existing optional-tool skip. This is a local history-scan finding, not a claim
that the downstream PR has already passed CI.
