"""Shared current-result scope for Materials reads and ML exports.

The SQL uses the fixed claim/paper/work aliases c, p, w. Admission history is
retained even when a later correction makes a result unavailable for use.
Unknown publication status is not an assertion that a paper is unretracted.
"""

SCOPE_VERSION = 'production90-current-results/2'
ADMISSION_POLICY_WHERE = "c.extraction_metadata->'production_admission'->>'policy'='production90/1'"

EXCLUSION_REASON_SQL = """CASE
    WHEN c.extraction_metadata->'production_admission'->>'policy' IS DISTINCT FROM 'production90/1'
        THEN 'not_production90_admission'
    WHEN (
        c.extraction_metadata->'production_admission'->>'batch_qualified' = 'true'
        OR (
            c.extraction_metadata->'production_admission'->>'admission_route' = 'individual_source_check'
            AND c.extraction_metadata->'production_admission'->>'per_record_checked' = 'true'
            AND c.extraction_metadata->'production_admission'->>'quality_status' = 'model_source_checked'
            AND c.extraction_metadata->'production_admission'->>'reviewer_kind' = 'model'
        )
    ) IS NOT TRUE
        THEN 'batch_not_qualified'
    WHEN c.property_type IS DISTINCT FROM 'tc' OR c.result_status IS DISTINCT FROM 'observed'
        THEN 'not_observed_tc'
    WHEN c.validity_status IS NULL OR c.validity_status NOT IN ('pending','accepted')
        THEN 'claim_not_currently_usable'
    WHEN p.status IN ('retracted','withdrawn','refuted') THEN 'paper_' || p.status
    WHEN w.publication_status IN ('retracted','withdrawn','refuted') THEN 'work_' || w.publication_status
    ELSE NULL
END"""

CURRENT_ADMISSION_WHERE = f'({EXCLUSION_REASON_SQL}) IS NULL'
