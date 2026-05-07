"""Broader formula cleanup — handle bare ``_x`` underscores too.

Revision ID: 0015_strip_bare_underscores
Down revision: 0014_strip_latex_formulas

Migration 0014 cleaned ``$_{...}$`` and ``_{...}`` patterns but its
WHERE clause filtered for ``\\$|_\\{``, so formulas that used the
brace-less ``_0.8`` style (``Y_0.8Pr_0.2Ba_2Cu_3O_7-δ``,
``(Ca_0.1La_0.9)(Ba_1.65La_0.35)Cu_3O_y``, …) were left untouched.
Audit found 3302 arXiv-derived materials still in this state.

This migration runs the full ``_clean`` pass (the same logic the
aggregator now uses for ``_clean_display``) over every material,
regardless of which markup variant it carries. Idempotent: rows
already cleaned by 0014 just no-op.

Same three-step structure as 0014:

  1. Clean ``records[].formula`` JSONB blobs in place.
  2. Drop duplicates whose clean-id twin already exists.
  3. Rename remaining dirty rows in place.

The pre-fix corpus had two flavours of dirty formulas — LaTeX
math-mode (``$_{}$``) and bare-underscore (``_x``) — produced by
NER on different paper styles. Both feed into the same canonical
form via the cleaner, so 0014 + 0015 together should leave zero
formulas containing ``$``, ``_``, ``{`` or ``}``.
"""
import json
import re

from alembic import op
from sqlalchemy import text


revision = "0015_strip_bare_underscores"
down_revision = "0014_strip_latex_formulas"
branch_labels = None
depends_on = None


_LATEX_SUB = re.compile(r"\$?_\{([^}]+)\}\$?")
_LATEX_DOLLAR = re.compile(r"\$([^$]*)\$")


def _clean(raw):
    if not raw or not isinstance(raw, str):
        return raw
    s = _LATEX_SUB.sub(r"\1", raw)
    s = _LATEX_DOLLAR.sub(r"\1", s)
    s = s.replace("_", "").replace("{", "").replace("}", "")
    s = s.strip()
    return s


def upgrade() -> None:
    bind = op.get_bind()

    # Step 1: clean records[].formula on every material whose blob
    # contains any of the dirty markers ($ or _ or { or }).
    rows = bind.execute(text(r"""
        SELECT id, records FROM materials
        WHERE records::text ~ '[\$_{}]'
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
                    r = dict(r); r["formula"] = new; changed = True
            new_records.append(r)
        if changed:
            bind.execute(
                text("UPDATE materials SET records = CAST(:r AS jsonb) WHERE id = :id"),
                {"r": json.dumps(new_records), "id": row.id},
            )
            cleaned_records += 1
    print(f"0015: cleaned records[] in {cleaned_records} materials")

    # Step 2 + 3 combined: dedupe + rename in a single pass with a
    # ``claimed`` set, mirroring the fix in 0014. Two-phase races
    # otherwise crash the migration when N dirty rows all clean to
    # the same target id (common with NER variants that only differ
    # in markup).
    dirty = bind.execute(text(r"""
        SELECT id FROM materials
        WHERE id ~ '[\$_{}]'
           OR formula ~ '[\$_{}]'
           OR formula_normalized ~ '[\$_{}]'
    """)).fetchall()
    deleted = 0
    renamed = 0
    claimed: set[str] = set()
    for row in dirty:
        new_id = _clean(row.id)
        r = bind.execute(
            text("SELECT formula, formula_normalized FROM materials WHERE id = :id"),
            {"id": row.id},
        ).first()
        if r is None:
            continue
        if new_id == row.id:
            # id already clean — just update the formula columns.
            bind.execute(
                text("""
                    UPDATE materials
                    SET formula = :nfm,
                        formula_normalized = :nnorm
                    WHERE id = :oid
                """),
                {
                    "nfm": _clean(r.formula),
                    "nnorm": _clean(r.formula_normalized),
                    "oid": row.id,
                },
            )
            renamed += 1
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
                "nfm": _clean(r.formula),
                "nnorm": _clean(r.formula_normalized),
                "oid": row.id,
            },
        )
        claimed.add(new_id)
        renamed += 1
    print(f"0015: deleted {deleted} duplicates, renamed {renamed} in place")


def downgrade() -> None:
    pass
