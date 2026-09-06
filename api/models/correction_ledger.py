"""PostgreSQL append-only guard shared by metadata and migrations."""

CREATE_GUARD = """
CREATE OR REPLACE FUNCTION sclib_guard_scientific_correction()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Scientific correction proposals are append-only; create a superseding revision';
END;
$$;
"""

CREATE_TRIGGER = """
CREATE TRIGGER scientific_correction_append_only
BEFORE UPDATE OR DELETE ON scientific_correction_proposals
FOR EACH ROW EXECUTE FUNCTION sclib_guard_scientific_correction();
"""
