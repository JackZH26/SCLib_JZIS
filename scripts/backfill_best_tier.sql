-- Backfill best_credibility_tier from the records JSONB array.
-- T1 < T2 < T3 — min() on strings gives the "best" tier.
-- Run after migration 0033 and after score_paper_credibility.py has stamped tiers.

UPDATE materials m
SET best_credibility_tier = sub.best_tier
FROM (
    SELECT
        m2.id,
        MIN(r->>'credibility_tier') AS best_tier
    FROM materials m2,
         jsonb_array_elements(m2.records) AS r
    WHERE r->>'credibility_tier' IS NOT NULL
    GROUP BY m2.id
) sub
WHERE m.id = sub.id
  AND (m.best_credibility_tier IS DISTINCT FROM sub.best_tier);
