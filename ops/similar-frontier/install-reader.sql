-- Offline scratch instance only. The operator has already installed and read back every private
-- segment against its captured digest, and supplies the corresponding trusted scope and byte count.
-- psql -v scope_json=... -v graph_bytes=... -f install-reader.sql
\set ON_ERROR_STOP on
BEGIN;
DO $$
BEGIN
    IF current_setting('listen_addresses') <> ''
       OR current_setting('server_version_num')::integer <> 160013
       OR (SELECT extversion FROM pg_extension WHERE extname='vector') IS DISTINCT FROM '0.8.7'
       OR NOT EXISTS (
           SELECT FROM pg_index i
           JOIN pg_class g ON g.oid=i.indexrelid
           JOIN pg_am am ON am.oid=g.relam
           JOIN pg_opclass op ON op.oid=i.indclass[0] AND op.opcmethod=am.oid
           WHERE g.oid='sclib_private_carrier.sealed_hnsw'::regclass
             AND i.indrelid='sclib_private_carrier.carrier'::regclass
             AND i.indnkeyatts=1 AND i.indisvalid AND i.indisready
             AND am.amname='hnsw' AND op.opcname='vector_cosine_ops'
             AND op.opcnamespace='public'::regnamespace AND op.opcintype='public.vector'::regtype
             AND g.reloptions @> ARRAY['m=32','ef_construction=200']
       )
       OR EXISTS (SELECT FROM sclib_private_carrier.carrier LIMIT 1) THEN
        RAISE EXCEPTION 'Expected a Unix socket only empty scratch carrier';
    END IF;
END $$;
CREATE FUNCTION sclib_private_carrier.stream(public.vector) RETURNS SETOF tid
AS '$libdir/sclib_frontier_reader','sclib_frontier_graph_stream' LANGUAGE C STRICT VOLATILE PARALLEL UNSAFE;
REVOKE ALL ON SCHEMA sclib_private_carrier FROM PUBLIC;
REVOKE ALL ON FUNCTION sclib_private_carrier.stream(public.vector) FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE ROLE sclib_frontier_scan LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
GRANT USAGE ON SCHEMA sclib_private_carrier TO sclib_frontier_scan;
GRANT EXECUTE ON FUNCTION sclib_private_carrier.stream(public.vector) TO sclib_frontier_scan;
ALTER ROLE sclib_frontier_scan SET default_transaction_read_only=on;
ALTER ROLE sclib_frontier_scan SET statement_timeout='2000ms';
ALTER ROLE sclib_frontier_scan SET idle_in_transaction_session_timeout='3s';

REVOKE TEMPORARY ON DATABASE postgres FROM PUBLIC;
CREATE TABLE sclib_private_carrier.binding (
    singleton boolean PRIMARY KEY CHECK (singleton),
    scope jsonb NOT NULL,
    relation oid NOT NULL,
    filenode oid NOT NULL,
    bytes bigint NOT NULL CHECK (bytes > 0)
);
INSERT INTO sclib_private_carrier.binding
SELECT true, :'scope_json'::jsonb, c.oid, pg_relation_filenode(c.oid), :'graph_bytes'::bigint
FROM pg_class c WHERE c.oid='sclib_private_carrier.sealed_hnsw'::regclass;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT FROM sclib_private_carrier.binding WHERE bytes=pg_relation_size(relation)
    ) THEN RAISE EXCEPTION 'Carrier byte extent differs from the verified capture'; END IF;
END $$;
GRANT SELECT ON sclib_private_carrier.binding TO sclib_frontier_scan;
COMMIT;
