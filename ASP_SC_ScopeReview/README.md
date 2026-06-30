# ASP_SC_ScopeReview

APS superconductivity scoping-review workspace.

This directory is intentionally named `ASP_SC_ScopeReview` to match the
requested project name, but the corpus and manuscript use `APS`
throughout: American Physical Society peer-reviewed journal articles.

## Purpose

Prepare a frozen, auditable APS-only superconductivity corpus for a
1986--2026 scoping review that mirrors the completed arXiv SCLib paper.
The APS study should be framed as a peer-reviewed-corpus replication and
contrast, not as a replacement for the arXiv preprint study.

## Starting Evidence

- Prior arXiv manuscript read: `/Users/jackzhou/Documents/Superconductivity/Superconductivity_Scoping_Review/latex/Zhou_LLM-Extracted-Bibliometric-Scaffold-Superconductivity_2026.tex`
- APS design docs read:
  - `docs/APS_INGESTION_PLAN.md`
  - `docs/APS_OPENCLAW_FULLTEXT_INGEST_RUNBOOK.md`
  - `docs/APS_VALIDATION_FOR_OPENCLAW.md`
- APS authorized candidate manifest:
  - `audit/aps_manifest_20260616T065908Z_authorized_19860101_20261231/aps_superconductivity_manifest.jsonl`
  - `audit/aps_manifest_20260616T065908Z_authorized_19860101_20261231/aps_superconductivity_dois.txt`

## Files

- `MANIFEST_AUDIT_SUMMARY_2026_06_29.md` records what is already known
  from the local APS manifest and documentation.
- `DATA_FREEZE_PROTOCOL_2026_06_29.md` is the proposed freeze protocol.
- `APS_SCOPING_REVIEW_RESEARCH_PLAN_2026.md` is the full research and
  paper plan.
- `FREEZE_EXPORT_RUNBOOK_2026_06_29.md` is the VPS2 export runbook.
- `scripts/preflight_aps_scope_freeze.sh` is a read-only preflight script.
- `scripts/export_aps_scope_freeze.sh` is a VPS2-oriented export
  script for the freeze.

## Status

As of 2026-06-29, this local machine does not have `docker` available, so
the current production PostgreSQL APS row counts cannot be verified here.
The final freeze must be executed on VPS2 or another environment with
direct database access.
