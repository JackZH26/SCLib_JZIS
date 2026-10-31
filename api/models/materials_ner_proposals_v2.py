"""Additive private proposal relations; the frozen v1 schema stays unchanged."""
import hashlib

from models.materials_ner_proposals_v1 import FINGERPRINT as BASE_FINGERPRINT
from models.materials_ner_proposals_v1 import TABLES as BASE_TABLES

VERSION = "materials-ner-proposals/2"
ADDED_TABLES = ("conditions", "sample_relations", "condition_supports")
TABLES = (*BASE_TABLES, *ADDED_TABLES)
DDL = [
    "CREATE UNIQUE INDEX ner_results_state_identity ON materials_ner_v1.results(run_id,local_id,state_id)",
    """CREATE TABLE materials_ner_v1.conditions(
        run_id text NOT NULL, state_id text NOT NULL, local_id text NOT NULL,
        payload jsonb NOT NULL, PRIMARY KEY(run_id,state_id,local_id),
        FOREIGN KEY(run_id,state_id) REFERENCES materials_ner_v1.states(run_id,local_id))""",
    """CREATE TABLE materials_ner_v1.sample_relations(
        run_id text NOT NULL, local_id text NOT NULL, from_sample_id text NOT NULL,
        to_sample_id text NOT NULL, relation text NOT NULL CHECK(relation='component_of'),
        review_status text NOT NULL CHECK(review_status IN ('pending_review','quarantined')),
        payload jsonb NOT NULL, PRIMARY KEY(run_id,local_id),
        UNIQUE(run_id,from_sample_id,to_sample_id,relation), CHECK(from_sample_id<>to_sample_id),
        FOREIGN KEY(run_id,from_sample_id) REFERENCES materials_ner_v1.samples(run_id,local_id),
        FOREIGN KEY(run_id,to_sample_id) REFERENCES materials_ner_v1.samples(run_id,local_id))""",
    """CREATE TABLE materials_ner_v1.condition_supports(
        run_id text NOT NULL, local_id text NOT NULL, result_id text NOT NULL,
        state_id text NOT NULL, condition_id text NOT NULL,
        relation text NOT NULL CHECK(relation='measures'),
        review_status text NOT NULL CHECK(review_status IN ('pending_review','quarantined')),
        payload jsonb NOT NULL, PRIMARY KEY(run_id,local_id),
        UNIQUE(run_id,result_id,state_id,condition_id),
        FOREIGN KEY(run_id,result_id,state_id) REFERENCES materials_ner_v1.results(run_id,local_id,state_id),
        FOREIGN KEY(run_id,state_id,condition_id) REFERENCES materials_ner_v1.conditions(run_id,state_id,local_id))""",
    "REVOKE ALL ON materials_ner_v1.conditions,materials_ner_v1.sample_relations,materials_ner_v1.condition_supports FROM PUBLIC",
]
FINGERPRINT = hashlib.sha256((BASE_FINGERPRINT + "\n" + "\n".join(DDL)).encode()).hexdigest()


def upgrade(connection):
    from sqlalchemy import text
    connection.execute(text("SELECT pg_advisory_xact_lock(924601)"))
    base = connection.execute(text("SELECT fingerprint FROM materials_ner_v1.schema_version "
        "WHERE version='materials-ner-proposals/1'")).scalar_one_or_none()
    if base != BASE_FINGERPRINT:
        raise RuntimeError("Materials proposal base fingerprint mismatch")
    observed = connection.execute(text("SELECT fingerprint FROM materials_ner_v1.schema_version "
        "WHERE version=:version"), {"version": VERSION}).scalar_one_or_none()
    if observed is not None:
        if observed != FINGERPRINT:
            raise RuntimeError("Materials proposal relation fingerprint mismatch")
        return
    for statement in DDL:
        connection.execute(text(statement))
    connection.execute(text("INSERT INTO materials_ner_v1.schema_version VALUES(:version,:fingerprint)"),
        {"version": VERSION, "fingerprint": FINGERPRINT})


def downgrade(connection):
    from sqlalchemy import text
    connection.execute(text("SELECT pg_advisory_xact_lock(924601)"))
    # Even a failed v2 run without entities is retained evidence of this contract.
    retained = connection.execute(text("SELECT EXISTS(SELECT 1 FROM materials_ner_v1.runs "
        "WHERE payload->>'schema'=:version)"), {"version": VERSION}).scalar_one()
    for name in ADDED_TABLES:
        retained |= connection.execute(text(f"SELECT EXISTS(SELECT 1 FROM materials_ner_v1.{name})")).scalar_one()
    if retained:
        raise RuntimeError("Refusing downgrade: retained Materials NER relation evidence")
    for name in reversed(ADDED_TABLES):
        connection.execute(text(f"DROP TABLE materials_ner_v1.{name}"))
    connection.execute(text("DROP INDEX materials_ner_v1.ner_results_state_identity"))
    connection.execute(text("DELETE FROM materials_ner_v1.schema_version WHERE version=:version"), {"version": VERSION})
