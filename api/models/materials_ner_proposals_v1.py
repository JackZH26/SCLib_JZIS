"""Frozen additive Materials NER proposal schema, independent of canonical claims.

This schema may be initialized by the bounded Mac importer before the site is
released. Migration 0092 adopts the identical fingerprint without changing
public claims, materials, search indexes, or the current Alembic revision.
"""
from __future__ import annotations

import hashlib

SCHEMA = "materials_ner_v1"
TABLES = ("bundles", "runs", "samples", "states", "protocols", "results", "evidence", "dependencies")
DDL = [
    """CREATE TABLE materials_ner_v1.bundles(
        id text PRIMARY KEY CHECK(id ~ '^[0-9a-f]{64}$'), work_id text NOT NULL CHECK(work_id LIKE 'arxiv:%'),
        payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now())""",
    """CREATE TABLE materials_ner_v1.runs(
        id text PRIMARY KEY CHECK(id ~ '^[0-9a-f]{64}$'), job_id text NOT NULL, work_id text NOT NULL,
        bundle_id text NOT NULL REFERENCES materials_ner_v1.bundles(id), packet_hash text NOT NULL,
        model text NOT NULL, worker_state text NOT NULL, payload jsonb NOT NULL,
        scientific_acceptance boolean NOT NULL DEFAULT false CHECK(NOT scientific_acceptance),
        ml_training_eligible boolean NOT NULL DEFAULT false CHECK(NOT ml_training_eligible),
        created_at timestamptz NOT NULL DEFAULT now())""",
    """CREATE TABLE materials_ner_v1.samples(
        run_id text NOT NULL REFERENCES materials_ner_v1.runs(id), local_id text NOT NULL,
        review_status text NOT NULL CHECK(review_status IN ('pending_review','quarantined')),
        payload jsonb NOT NULL, PRIMARY KEY(run_id,local_id))""",
    """CREATE TABLE materials_ner_v1.states(
        run_id text NOT NULL, local_id text NOT NULL, sample_id text NOT NULL,
        review_status text NOT NULL CHECK(review_status IN ('pending_review','quarantined')),
        payload jsonb NOT NULL, PRIMARY KEY(run_id,local_id), UNIQUE(run_id,local_id,sample_id),
        FOREIGN KEY(run_id,sample_id) REFERENCES materials_ner_v1.samples(run_id,local_id))""",
    """CREATE TABLE materials_ner_v1.protocols(
        run_id text NOT NULL REFERENCES materials_ner_v1.runs(id), local_id text NOT NULL,
        review_status text NOT NULL CHECK(review_status IN ('pending_review','quarantined')),
        payload jsonb NOT NULL, PRIMARY KEY(run_id,local_id))""",
    """CREATE TABLE materials_ner_v1.results(
        run_id text NOT NULL, local_id text NOT NULL, sample_id text NOT NULL,
        state_id text NOT NULL, protocol_id text NOT NULL, quantity_kind text NOT NULL,
        review_status text NOT NULL CHECK(review_status IN ('pending_review','quarantined')),
        payload jsonb NOT NULL, PRIMARY KEY(run_id,local_id),
        FOREIGN KEY(run_id,sample_id) REFERENCES materials_ner_v1.samples(run_id,local_id),
        FOREIGN KEY(run_id,state_id,sample_id) REFERENCES materials_ner_v1.states(run_id,local_id,sample_id),
        FOREIGN KEY(run_id,protocol_id) REFERENCES materials_ner_v1.protocols(run_id,local_id))""",
    """CREATE TABLE materials_ner_v1.evidence(
        run_id text NOT NULL REFERENCES materials_ner_v1.runs(id), ordinal integer NOT NULL,
        path text NOT NULL, block_id text NOT NULL, payload jsonb NOT NULL,
        PRIMARY KEY(run_id,ordinal))""",
    """CREATE TABLE materials_ner_v1.dependencies(
        run_id text NOT NULL, result_id text NOT NULL, target_id text NOT NULL,
        relation text NOT NULL CHECK(relation IN ('derived_from','same_measurement','compares_with')),
        PRIMARY KEY(run_id,result_id,target_id,relation),
        FOREIGN KEY(run_id,result_id) REFERENCES materials_ner_v1.results(run_id,local_id),
        FOREIGN KEY(run_id,target_id) REFERENCES materials_ner_v1.results(run_id,local_id))""",
    "CREATE INDEX ner_runs_work ON materials_ner_v1.runs(work_id)",
    "CREATE INDEX ner_results_review ON materials_ner_v1.results(review_status,quantity_kind)",
]
FINGERPRINT = hashlib.sha256("\n".join(DDL).encode()).hexdigest()


def initialize_statements():
    return [
        "CREATE SCHEMA materials_ner_v1",
        "REVOKE ALL ON SCHEMA materials_ner_v1 FROM PUBLIC",
        "CREATE TABLE materials_ner_v1.schema_version (version text PRIMARY KEY, fingerprint text NOT NULL)",
        *DDL,
        "REVOKE ALL ON ALL TABLES IN SCHEMA materials_ner_v1 FROM PUBLIC",
        f"INSERT INTO materials_ner_v1.schema_version VALUES('materials-ner-proposals/1','{FINGERPRINT}')",
    ]
