# Manifest Inputs

This directory records the APS manifest inputs used to prepare the
freeze. The large source files are not duplicated here by default; they
are referenced from the SCLib audit tree and pinned by SHA-256 checksums.

Canonical local sources:

- `audit/aps_manifest_20260616T065908Z_authorized_19860101_20261231/aps_superconductivity_dois.txt`
- `audit/aps_manifest_20260616T065908Z_authorized_19860101_20261231/aps_superconductivity_manifest.jsonl`
- `audit/aps_manifest_20260616T065908Z_authorized_19860101_20261231/aps_superconductivity_manifest.csv`
- `audit/aps_manifest_20260616T065908Z_authorized_19860101_20261231/APS_SUPERCONDUCTIVITY_COVERAGE.md`

Checksum file:

- `../checksums/manifest_inputs_2026_06_29.sha256`

For the final data freeze, copy or compress these manifest inputs into
the snapshot directory together with the production database exports.
