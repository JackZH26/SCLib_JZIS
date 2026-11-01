"""Indexable UUID references with the same membership as id::text equality.

Context is retained JSON, so malformed or noncanonical UUID strings must not
raise cast errors or start matching rows that the original reader excluded.
"""

UUID_PATTERN = '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
PROTOCOL_TEXT = "ev.context->'materials_context'->>'protocol_id'"
PROTOCOL_ID = f'CASE WHEN {PROTOCOL_TEXT} ~ \'{UUID_PATTERN}\' THEN ({PROTOCOL_TEXT})::uuid END'
COMPOSITION_IDS = f"""ARRAY(
    SELECT CASE WHEN cid ~ '{UUID_PATTERN}' THEN cid::uuid END
    FROM jsonb_array_elements_text(ev.context->'materials_context'->'composition_ids') AS ids(cid))"""
