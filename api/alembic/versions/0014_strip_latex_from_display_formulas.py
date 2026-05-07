"""Strip LaTeX math-mode markup from materials.formula + .id + .formula_normalized.

Revision ID: 0014_strip_latex_formulas
Down revision: 0013_add_mp_id_columns

The pre-2026-04-28 ``normalize_formula`` did not drop the LaTeX
``$`` math-mode delimiter, so a paper writing ``H$_{3}$S`` produced
the row ``mat:h$3$s`` while a sibling paper writing ``H_3S``
produced ``mat:h3s``. Same compound, two rows. ~680 materials are
affected and the user-visible symptom is tooltips / badges showing
raw LaTeX (``CeCo(In$_{1-x}$Cd$_x$)$_5$``).

Sibling commit fixes ``normalize_formula`` (drops ``$``) and adds
``_clean_display`` to the aggregator so newly-imported papers
produce clean display strings. This migration retrofits the
historical rows in three steps:

1. **Clean ``materials.records[]`` formula fields in place.** The
   per-record JSONB blobs carry the raw NER formula; the aggregator
   could re-introduce ugly variants on its next sweep if we leave
   them. Strip ``$`` and ``_{...}`` patterns inside the JSON so the
   display-form selector picks the clean version.

2. **Drop LaTeX-only duplicate rows.** When ``mat:h$3$s`` and
   ``mat:h3s`` both exist, the dollar-laden one is the duplicate —
   delete it. Its records are already merged onto the clean twin
   via the aggregator's normalization step (next sweep). Bookmarks
   pointing at the deleted id become dangling but the GET handler
   404s for missing materials, so the UX is "saved item disappeared"
   rather than a hard error.

3. **Rename remaining LaTeX-only rows.** For rows with no clean
   twin in the DB, just strip ``$`` and ``_{...}`` from id, formula
   and formula_normalized in place. Postgres allows UPDATE on the
   primary key; we depend on step 2 having cleared every conflict.

Down migration is a no-op: the original LaTeX strings are not worth
restoring and ``revoke``-style rollback would have to invent the
``$`` markers we just stripped.
"""
import re

from alembic import op
from sqlalchemy import text


revision = "0014_strip_latex_formulas"
down_revision = "0013_add_mp_id_columns"
branch_labels = None
depends_on = None


# Same patterns the aggregator's _clean_display uses. Kept inline so
# the migration is self-contained (api image doesn't import ingestion).
_LATEX_SUB = re.compile(r"\$?_\{([^}]+)\}\$?")
_LATEX_DOLLAR = re.compile(r"\$([^$]*)\$")


def _clean(raw: str) -> str:
    if not raw:
        return raw
    s = _LATEX_SUB.sub(r"\1", raw)
    s = _LATEX_DOLLAR.sub(r"\1", s)
    return s.replace("_", "").replace("{", "").replace("}", "").strip()


def upgrade() -> None:
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # Step 1: clean the formula field inside each materials.records[]
    # entry so the aggregator can't re-emit dirty display strings.
    # ------------------------------------------------------------------
    rows = bind.execute(text("""
        SELECT id, records
        FROM materials
        WHERE records::text ~ '\\$|_\\{'
    """)).fetchall()
    cleaned_records = 0
    for row in rows:
        new_records = []
        changed = False
        for r in row.records or []:
            if isinstance(r, dict) and "formula" in r:
                old = r.get("formula")
                new = _clean(old) if isinstance(old, str) else old
                if new and new != old:
                    r = dict(r)
                    r["formula"] = new
                    changed = True
            new_records.append(r)
        if changed:
            bind.execute(
                text("UPDATE materials SET records = CAST(:r AS jsonb) WHERE id = :id"),
                {"r": __import__("json").dumps(new_records), "id": row.id},
            )
            cleaned_records += 1
    print(f"0014: cleaned records[] in {cleaned_records} materials")

    # ------------------------------------------------------------------
    # Step 2: dedupe + rename in one pass. The earlier two-step version
    # had a race: when N dirty ids all cleaned to the same target, step 2
    # saw "no twin in DB" for each (the target was indeed missing at
    # snapshot time) and step 3 then crashed on the second UPDATE
    # because the first one had just claimed the target id.
    #
    # Combined loop: track every clean-id we've claimed in this run,
    # and do a fresh "does this id already exist?" query right before
    # each UPDATE. If either says yes, delete the row instead.
    # ------------------------------------------------------------------
    dirty = bind.execute(text(r"""
        SELECT id FROM materials WHERE id ~ '\$|_\{'
    """)).fetchall()
    deleted = 0
    renamed = 0
    claimed: set[str] = set()
    for row in dirty:
        new_id = _clean(row.id)
        if new_id == row.id:
            continue
        twin_exists = bind.execute(
            text("SELECT 1 FROM materials WHERE id = :nid"),
            {"nid": new_id},
        ).first() is not None
        if twin_exists or new_id in claimed:
            bind.execute(
                text("DELETE FROM materials WHERE id = :id"),
                {"id": row.id},
            )
            deleted += 1
            continue
        r = bind.execute(
            text("SELECT formula, formula_normalized FROM materials WHERE id = :id"),
            {"id": row.id},
        ).first()
        if r is None:
            continue
        bind.execute(
            text("""
                UPDATE materials
                SET id = :nid,
                    formula = :nfm,
                    formula_normalized = :nnorm
                WHERE id = :oid
            """),
            {
                "nid": new_id,
                "nfm": _clean(r.formula) if r.formula else r.formula,
                "nnorm": _clean(r.formula_normalized) if r.formula_normalized
                         else r.formula_normalized,
                "oid": row.id,
            },
        )
        claimed.add(new_id)
        renamed += 1
    print(f"0014: deleted {deleted} duplicates, renamed {renamed} in place")


def downgrade() -> None:
    # No reverse: the original ``$_{...}$`` strings carry no signal
    # the cleaned forms don't, and reintroducing them would just
    # bring back the duplicate-row bug.
    pass
