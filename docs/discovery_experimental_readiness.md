# Experimental source readiness for Discovery

`discovery-experimental-readiness/1.0.0` is a local, deterministic adapter for the
frozen NIMS MDR SuperCon 240322 captures already in the repository. It prepares a
source-review queue for experiment-driven Discovery research. It does not train,
query a database, contact providers, approve a label, grant source permissions,
create a scientific publication or assign candidate scores.

The two data captures are source references, not reviewed independent experiments:

| Source | Rows | Nonempty recommended Tc | Positive numeric Tc expressions | Positive Tc with explicit K | Positive K plus recognized source method code |
| --- | ---: | ---: | ---: | ---: | ---: |
| Oxide / metallic | 33,458 | 26,358 | 26,268 | 19,925 | 333 |
| Organic | 568 | 517 | 516 | 0 | 0 |

Organic has 39 nonempty recognized Tc-method codes but no Tc unit column. The
last two columns above describe available lexical context, **not ML eligibility**.
The two source tables contain 7,254 and 335 distinct reference codes respectively;
these codes are not reviewed Work identities or evidence of independence.

## Reproduce without fitting

From the repository root, with Python 3.9 or later and the standard library:

```bash
python3 scripts/discovery_experimental_readiness.py --check
python3 -m pytest scripts/tests/test_discovery_experimental_readiness.py
```

`--check` verifies the exact source pins, reconstructs the report and compares
bytes with `frontend/public/research-pilots/discovery-experimental-readiness-2026-10-06.json`.
It performs no writes. Without output arguments, the tool emits only a closed
receipt with counts, report SHA-256 and `training_executed:false`.

To create a new report and an optional local source-expression review queue:

```bash
python3 scripts/discovery_experimental_readiness.py \
  --output /private/review/new-readiness.json \
  --records-output /private/review/new-source-readings.jsonl
```

The directory must already exist. Both files use mode 0600 and exclusive creation:
an existing report or source is never overwritten. The records are source readings,
not a training matrix. Each retains its original value/unit/method code, source-table
and source-file hash, row hash, original physical-line locator, reference code,
source name/composition, sample identifier and isotope label. Every reading has
`label_value_kelvin:null`, `training_eligible:false`, unadjudicated origin, unknown
family and unknown independent experiment identity. The public JSON contains only
aggregate counts, reason codes, source pins, recorded licence and next actions.

## Sources and integrity

- `api/services/resources/supercon_mdr_240322_oxide_metadata.json.gz`:
  `d1fce28506d68732744858570f6e4ee2a8dfef94630c8b3b48d703b95443707c`.
  The separately pinned manifest binds 66 retained columns to the original
  191-column source and its SHA-256. The adapter verifies the decompressed hash;
  it does not claim to re-read the complete original oxide/metallic source file.
- `frontend/public/research-pilots/materials-mdr-organic-240322.json`:
  `5da57e0959d1ea0c081460dbf24a62b2eacfcb0d179ad1bfcbc272bdfd2ea3bd`.
  The original `240322_MDR_Organic.txt` is also checked against
  `d116848a90d01e48356ed6cf0bb69035fa863a3a559deac1ef188025bdb3b423`;
  every projected cell and source-row physical-line hash is replayed.

The recorded dataset licence is CC BY 4.0, attributed to NIMS MDR SuperCon,
[DOI 10.48505/nims.4487](https://doi.org/10.48505/nims.4487). That recorded licence
is preserved separately from the project's absent purpose-specific ML permission
receipt, primary-paper source review and publication-currentness checks. The report
also pins the adapter's exact source bytes. No path or hash is a human approval.

## Interpretation and leakage boundaries

The adapter has nine disjoint **source-field channels**. The underlying source-row
cohorts overlap and must never be summed as independent samples:

- Oxide/metallic: recommended `tc`, R=0 `t1`, midpoint `t2`, R=100% `t3`,
  susceptibility `tcsus`, and non-transition measurement limit `tcn`.
- Organic: `tc` at critical/atmospheric pressure, pressure maximum `tcmax`, and
  non-transition measurement limit `tcn`.

R=100% is not silently renamed onset. Susceptibility and recommended Tc do not
supply a unique criterion. A recognized measurement-method code does not bind
that method to each individual result or resolve its transition criterion.

The 4,641 oxide/metallic and 23 Organic `tcn` expressions are measurement lower
temperatures in non-transition-report context, not Tc observations or Tc=0 labels.
They remain outside the point-Tc channels. Zero, negative, interval, inequality,
uncertainty-formatted and unparsable expressions are retained without creating
negative examples. Numeric parsing is only lexical bookkeeping, not normalization.

Oxide/metallic `pmax` is the maximum pressure applied and is not assigned to Tc.
Organic `pcrit` supplies a header relationship and GPa, but no reviewed sample/state
association. Organic `pmax` is related to `tcmax` and has no supplied unit column;
it never borrows GPa from `pcrit`. Missing pressure and a numeric zero never establish
explicit ambient conditions. Unknown units remain unknown. No formula, family or
sample identity is inferred to make a record qualify.

## What is still required

The report leaves eligible-label count, independent-experiment count, model score,
uncertainty and resource budget unknown. All observations need primary-source
revision/locator review, sample/state/Work interpretation, origin and scientific
admission, permitted-use decisions, and field/measurement-window context. Record
counts do not demonstrate sufficient cross-family coverage.

Use these gaps to select the next source-review work for `high_bandwidth`,
`high_carrier_density` and `geometry_construction`; the adapter does not assign
families or infer those mechanisms from formula or Tc. Computed JARVIS/DFT values,
legacy scores, penetration depth and superconducting-response quantities are not
added as experimental labels or prospective bandwidth/carrier-density features.

Once actually admitted source packages exist, reuse the existing v4 dataset
compiler, identity audit, fixed grouped/chemical-system/family holdouts and
training-fold-only transformations. The current real-data baseline runner remains
closed. Training requires its existing source-use, scientific-pilot, independent
review, execution-environment and resource-admission contracts; a generated
readiness report or a single-account review cannot substitute for them.
