# Hydride Parameter NER Runbook

Last updated: 2026-06-25

## Why this is a separate NER flow

SCLib currently has two production NER paths:

1. **Material NER**: `ingestion.extract.material_ner`
   - arXiv path: parsed source -> chunks/embedding -> material NER -> `papers.materials_extracted`
   - APS path: transient BagIt full text -> material NER -> `papers.materials_extracted`
   - aggregation: `ingestion.extract.materials_aggregator` rolls records into `materials`

2. **Affiliation / geo NER**: `ingestion.extract.affiliation_ner`
   - writes author/institution geography into `papers.affiliations` and `papers.paper_geo`
   - does not affect material fields

Hydrides need a narrower extraction target than the generic material NER:
for each Tc condition, capture **pressure**, **lambda_eph**, **mu_star**,
and **omega_log_k**. The generic material schema did not store `mu_star`,
and its prompt explicitly avoided emitting it. Therefore the hydride pass
writes a new table, `hydride_tc_parameters`, rather than mutating
`papers.materials_extracted` or overloading the main `materials` aggregate.

## Data model

New table: `hydride_tc_parameters`

Key fields:

- `material_id`: FK to `materials.id`, nullable when a formula has not yet
  been aggregated into the public material catalogue.
- `paper_id`: FK to `papers.id`.
- `source`: `arxiv` or `aps`.
- `formula`, `formula_normalized`.
- `tc_kelvin`, `pressure_gpa`, `lambda_eph`, `mu_star`, `omega_log_k`.
- `omega_log_source_value`, `omega_log_source_unit`.
- `method`, `evidence_type`, `confidence`, `source_section`.
- `validation_flags`, `provenance`.
- `model`, `prompt_version`.

APS compliance rule: store only derived structured facts and short
provenance metadata. Do not store APS full-text snippets.

## Website exposure

API:

```text
GET /materials/{material_id}/hydride_parameters
```

Frontend:

- Hydride material detail pages call this endpoint.
- If rows exist, the page shows a compact table:
  `Formula`, `Tc`, `P`, `lambda`, `mu*`, `omega_log`, `Method`, `Year`,
  `Paper`.
- Non-hydride materials and hydrides without enrichment rows show no extra
  section.

## Runner

Entrypoint:

```bash
python -m ingestion.hydride_parameters
```

or installed console script:

```bash
sclib-hydride-ner
```

Useful calibration commands:

```bash
# 50-paper dry run, no DB writes
python -m ingestion.hydride_parameters \
  --source all \
  --limit 50 \
  --dry-run \
  --checkpoint /opt/sclib_aps_manifests/hydride_params_50_dry.jsonl

# 200-paper calibration with persistence
python -m ingestion.hydride_parameters \
  --source all \
  --limit 200 \
  --checkpoint /opt/sclib_aps_manifests/hydride_params_200.jsonl

# Resume, retrying only failed rows
python -m ingestion.hydride_parameters \
  --source all \
  --checkpoint /opt/sclib_aps_manifests/hydride_params_200.jsonl \
  --retry-failed
```

Candidate selection defaults to papers whose title/abstract or existing
NER output mentions hydride/superhydride/hydrogen-rich terms. A manifest
can also be supplied; lines may be `paper_id`, DOI, or JSONL objects with
`paper_id`, `id`, or `doi`.

## Validation gates

Fatal gates drop rows before persistence:

- Formula must contain H or D plus at least one other element.
- `tc_kelvin` must be `0.01 <= Tc <= 400`.
- `pressure_gpa`, when present, must be `0 <= P <= 500`.
- `lambda_eph`, when present, must be `0.01 <= lambda <= 10`.
- `mu_star`, when present, must be `0 <= mu* <= 0.5`.
- `omega_log_k`, when present, must be `1 <= omega_log <= 5000`.
- A row must include Tc and at least one condition parameter:
  pressure, lambda, mu*, or omega_log.

Non-fatal checks are kept in `validation_flags`; currently this includes
Allen-Dynes consistency checks when lambda/mu*/omega_log/Tc are all present.

## APS handling

For APS rows, the runner re-downloads BagIt full text on VPS2, extracts
to `TempBagit`, runs hydride NER while the temp dir is alive, then purges
and verifies deletion. Non-dry runs write another `tdm_audit_log` row.

Persistent outputs are limited to:

- `hydride_tc_parameters`
- `tdm_audit_log`

No APS body text is stored in `chunks`, Vertex Vector Search, GCS, or the
new hydride table.
