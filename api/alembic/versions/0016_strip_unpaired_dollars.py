"""Strip unpaired ``$`` characters from materials.formula.

Revision ID: 0016_strip_unpaired_dollars
Down revision: 0015_strip_bare_underscores

Migrations 0014 / 0015 used the regex ``\\$([^$]*)\\$`` to match LaTeX
math-mode pairs and strip the contents inline. That misses
unpaired dollars — leading (``$Nb/Cu40Ni60``), trailing
(``FeSe1\\text--xTex$``) or embedded (``Na0.31CoO2\\cdot$1.3H2O``).
A post-cleanup audit found 4 such rows.

This migration just nukes any remaining ``$`` from formula. Sibling
commit also updates the live aggregator's ``_clean_display`` to do
the same unconditionally so new ingests can't regenerate the
problem.
"""
from alembic import op
from sqlalchemy import text


revision = "0016_strip_unpaired_dollars"
down_revision = "0015_strip_bare_underscores"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        UPDATE materials
        SET formula = REPLACE(formula, '$', '')
        WHERE formula LIKE '%$%';
    """))


def downgrade() -> None:
    pass
