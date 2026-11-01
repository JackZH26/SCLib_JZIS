"""Populate source-scoped browsing families without changing scientific claims."""
import json

from alembic import op
import sqlalchemy as sa

from services.materials_family_v1 import classify_material_family

revision = '0105_materials_family'
down_revision = '0104_materials_device_context'
branch_labels = None
depends_on = None


def upgrade():
    db = op.get_bind()
    rows = db.execute(sa.text("SELECT id,formula,family FROM materials WHERE id LIKE 'source:%' ORDER BY id")).mappings().all()
    updates = []
    for row in rows:
        derived = classify_material_family(row['formula'])
        # Preserve the previous value for a bounded, non-destructive rollback.
        updates.append(dict(id=row['id'], family=derived['family'],
            patch=dict(family_classification=derived, family_before_v1=row['family'])))
    if updates:
        # One statement also advances the research integrity epoch only once.
        db.execute(sa.text("""UPDATE materials m SET family=u.item->>'family',
            material_semantics=COALESCE(m.material_semantics,'{}'::jsonb)||(u.item->'patch')
            FROM jsonb_array_elements(CAST(:updates AS jsonb)) AS u(item)
            WHERE m.id=u.item->>'id'"""), dict(updates=json.dumps(updates)))


def downgrade():
    # Statement-level integrity triggers advance even for zero updated rows.
    # An empty downgrade must be a genuine no-op.
    if not op.get_bind().execute(sa.text("""SELECT EXISTS(SELECT 1 FROM materials
        WHERE id LIKE 'source:%' AND material_semantics ? 'family_before_v1'
        AND material_semantics->'family_classification'->>'version'='materials-family/1')""")).scalar_one():
        return
    op.execute("""UPDATE materials SET family=material_semantics->>'family_before_v1',
        material_semantics=material_semantics-'family_classification'-'family_before_v1'
        WHERE id LIKE 'source:%' AND material_semantics ? 'family_before_v1'
        AND material_semantics->'family_classification'->>'version'='materials-family/1'""")
