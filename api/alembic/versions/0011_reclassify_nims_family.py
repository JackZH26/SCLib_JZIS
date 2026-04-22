"""Re-run the family classifier on every NIMS-imported material.

Revision ID: 0011_reclassify_nims_family
Down revision: 0010_data_cleanup_audit

The ~40 000 NIMS SuperCon rows were imported long before the family
classifier was hardened (fix commit 9758d9a, 2026-04-15). Two
historical bugs combined to mis-tag 164 materials as 'hydride':

1. The pre-9758d9a hydride rule ran ``re.search(r"h\\s*[0-9]", fl)``
   on a lowercased formula. That matched the "h" in "Rh" (rhodium)
   whenever followed by a digit, so BaRh₂P₂, R₅Rh₆Sn₁₈, YbRh₂Si₂
   etc. all got tagged as hydrides.

2. The NIMS importer called ``classify_family(normalized)`` where
   ``normalized`` is lowercased. Every subsequent classify_family
   rule that relies on uppercase-element tokenisation (current
   hydride/fulleride/nickelate paths) was silently dead for NIMS
   rows — they would never reach the correct family even after the
   code was fixed.

Sibling commit fixes the importer to pass the raw (original-case)
formula going forward. This migration re-applies the *current*
classify_family to every NIMS material's original-case formula and
UPDATEs ``family`` in place. Exactly the same function the ingest
path uses, so there's no drift between fresh imports and back-
filled rows.

The classifier is duplicated inline rather than imported from
``ingestion.nims`` because the api Docker image does not install
the ingestion package (they're separate services). Keep this copy
in sync with ``ingestion/ingestion/nims.py::classify_family`` if
either is edited; the cost of duplication here is bounded by the
one-shot nature of the migration.
"""
import re

from alembic import op
from sqlalchemy import text


revision = "0011_reclassify_nims_family"
down_revision = "0010_data_cleanup_audit"
branch_labels = None
depends_on = None


# --- Embedded copy of ingestion/ingestion/nims.py::classify_family ---------
# Kept byte-for-byte consistent with the source at 2026-04-22. See the
# docstring above for why this lives here instead of being imported.

def _classify_family(formula: str) -> str | None:
    f = formula.strip()
    fl = f.lower()

    if re.fullmatch(r"mgb2", fl):
        return "mgb2"

    elements = re.findall(r"[A-Z][a-z]?", f)
    high_h = bool(re.search(r"H(?:[2-9]|1[0-9])(?![0-9])", f))
    if high_h and "O" not in elements and "C" not in elements:
        partners = {"S", "Se", "La", "Y", "Ca", "Mg", "Sr", "Ba",
                    "Th", "Sc", "Yb", "Ce", "Pr", "Nd"}
        if any(e in partners for e in elements):
            return "hydride"

    for el, cnt in re.findall(r"([A-Z][a-z]?)[_\s]*(\d+)?", f):
        if el == "C" and cnt in ("60", "70", "76", "84"):
            return "fulleride"

    if "fe" in fl and re.search(r"(as|se|te|p)", fl):
        return "iron_based"

    # Cuprate shorthand (BSCCO / YBCO / Bi-2212 / etc.)
    if re.search(r"bscco|ybco|lsco|tbcco", fl):
        return "cuprate"
    if re.search(r"\b(pb|bi|tl|hg)[\s\-()a-z]*[12][12][0-9]{2}\b", fl):
        return "cuprate"
    if re.search(r"\by[\s\-]*12[3-8]\b", fl):
        return "cuprate"

    # Nickelates (Ni + O, no Cu/Fe)
    if (
        "Ni" in elements
        and "O" in elements
        and "Cu" not in elements
        and "Fe" not in elements
    ):
        return "nickelate"

    if "cu" in fl and "o" in fl and re.search(
            r"(la|y|ba|sr|ca|bi|hg|tl|nd|sm|gd)", fl):
        return "cuprate"

    if re.search(r"(ube|cein|ceco|cecu|ypb|yrh|uru)", fl):
        return "heavy_fermion"

    if re.search(r"(nb3sn|nb3ge|v3si|nbti|pb\b|hg\b|\bsn\b)", fl):
        return "conventional"

    return None


def upgrade() -> None:
    bind = op.get_bind()
    # Scope to NIMS-imported rows only. arXiv-aggregator rows already
    # go through the current classifier on every aggregator run; we
    # don't want to accidentally overwrite a family a human admin
    # adjusted for a non-NIMS material.
    rows = bind.execute(text(
        "SELECT id, formula FROM materials WHERE id LIKE 'nims:%%'"
    )).fetchall()

    moved = 0
    for row in rows:
        new_family = _classify_family(row.formula)
        bind.execute(
            text("UPDATE materials SET family = :f WHERE id = :id"),
            {"f": new_family, "id": row.id},
        )
        moved += 1

    print(f"0011: reclassified {moved} NIMS materials via classify_family")


def downgrade() -> None:
    # Downgrade is a no-op. The historical family values were
    # produced by a buggy classifier; restoring them would undo a
    # real correctness improvement. A human who wants to revert a
    # specific row can UPDATE materials SET family = '...'
    # individually.
    pass
