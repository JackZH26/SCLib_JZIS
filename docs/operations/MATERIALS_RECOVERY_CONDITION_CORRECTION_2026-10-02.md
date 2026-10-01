# Materials condition correction, 2026-10-02

This record supersedes the current classification seed described by the frozen
[R3 local acceptance](MATERIALS_RECOVERY_ACCEPTANCE_2026-10-02.md). Its historical
counts, hashes and native captures are retained. Publication still requires
the ordinary tests, security, signed image release and deployment checks for
the corrected source, followed by public revision verification.

The actual primary abstract contains `40~K` and `58 K` for different transitions.
Extractor 1.0.0 missed the TeX number/unit separator and admitted a CDW statement
with incomplete temperature context. Extractor 1.0.1 recognizes whole signed,
decimal, exponent, interval and uncertainty tokens and TeX spacing before
applying multiple-temperature, pressure and magnetic-field review guards. The
ambiguous abstract statement moves to review. The resource was rebuilt from
the same primary capture; the two remaining statements are one CDW report and
one single-nodeless gap report for the same material, with pending alias/state
association and no scientific acceptance or property promotion.

Unicode-sign tests additionally exposed a direct-helper boundary and raw-token
normalization issue. The prior full extraction path normalized minus signs
before that helper; candidate sign corruption was not demonstrated. Conditions
now retain their original flattened tokens before formula normalization. Nine
actual statement-path scalar, exponent and interval cases preserve Unicode
signs and correct signed values across temperature, pressure and field. Whole
parenthetical uncertainty tokens remain unresolved when unsupported by the
existing quantity parser.

Local validation for the frozen correction:

- 288 focused Python tests and seven subtests passed; Ruff passed.
- Ten native PostgreSQL/Redis API tests passed in 2.34 seconds, including actual
  formatted dual-temperature chunks, source withdrawal, changed-record guards
  and fair multi-paper inspection. Owned service cleanup completed.
- All 2,032 frontend tests in 64 suites and 46 source contract checks passed.
  The production build generated 44 routes and TypeScript passed. The 16 focused
  enrichment display tests include both supported extractor versions.
- The installed wheel checked all 361 packaged Python files and five resources
  against repository bytes, with imports restricted to its installed target.
  The wheel SHA-256 is
  `472a4f5b0574bed3b994a4d34dc035d7357ad7da83b6c222310d52f58f26b83f`
  (4,195,759 bytes). It contains 41 unchanged numeric seed candidates and two
  classification statements. Offline MDR lookups return Nb 19 and NbN 15 rows.
- The same 321-source historical replay still returns 65 numeric candidates,
  zero classification candidates and 122 deduplicated review findings. The
  numeric candidate-list hash remains
  `5dcf69800e72c71aa3f7a96b258c08b685f3e8e14e807e63d805f4826c3ded78`.
- A separate stable AI-assisted source-scope check verifies two genuine
  candidates, two genuine dual-temperature findings, nine signed/range cases
  and unchanged/changed/missing retained-reference guards (2/0/0). It is not
  formal human review or a scientific validity judgment.
- The actual components render the current two-statement report at widths
  320, 390, 640 and 1280 pixels. Document width equals each viewport width;
  expanded identity hashes wrap within the mobile panel. The temporary route
  is labelled as a local component preview and removed before the production
  build. These screenshots do not establish production publication.

The current classification resource file hash is
`d7bf29439311fb7c210fa34f339c47a4e3720775c735e7cfd6218648bcdb5b34`;
its internal seed hash is
`6aa56ccc9b4f1cfbf110dfa692cb4f6474539a674399414040346943db671787`.
The original numeric seed file hash remains
`daa4c0186083e32c2fe601c047c4c9c8acff3b8bc358dcb318e911f44a1e2111`.
Correction receipts live privately under
`/tmp/sclib-classification-conditions-r5-20261002` and
`/tmp/sclib-classification-review-r5-20261002`; the installed-wheel proof hash is
`3946e8de909617ac2e21eba8b274873eb870305f2a99f5858c5ef767170e5751`.

The independent 40-finding audit remains pinned to extractor 1.0.0 and commit
`4f548a57288a27c1c3fc0656848fee1b671fc569`. Its 25 justified holds, 12 association
opportunities and three missing-context cases all remain unresolved. The 12
opportunities include duplicate evidence and cannot be counted as new facts or
independent experiments. No canonical records, source permissions, formal
sample/phase reviews, new scientific calculations or ML approvals changed.

The seven genuine [R5 protocol captures](SCLIB_NATIVE_CAPTURES_2026-10-02_R5.md)
bind the corrected source. An earlier local R4 run remains private debugging
output and is not substituted for these final captures.
Independent verification checked all 4,123 current source-pin entries and the
seven original output/archive byte pairs. All 363 prior wire fixtures, including
296 native archives, remain identical to commit `4f548a5`. All 125 previous
component literal hash occurrences remain; six new assertions bring that count
to 131. These packaging, protocol, browser and unit-test inventories overlap
and must not be added as an independent scientific sample size.
