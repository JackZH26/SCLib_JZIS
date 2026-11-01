"""Bind source-resolved display/families without rewriting scientific assertions."""
import json
from pathlib import Path
from alembic import op
import sqlalchemy as sa

revision = '0106_materials_source_notation'
down_revision = '0105_materials_family'
branch_labels = None
depends_on = None


def annotations():
    return json.loads((Path(__file__).parents[2]/'services/notation_data/materials_source_families_v1.json').read_text())['materials']


def upgrade():
    db=op.get_bind();updates=[]
    for annotation in annotations():
        row=db.execute(sa.text("""SELECT formula,family,material_semantics FROM materials
            WHERE id=:id AND encode(sha256(convert_to(formula,'UTF8')),'hex')=:sha"""),
            dict(id=annotation['id'],sha=annotation['formula_sha256'])).mappings().first()
        if not row or (row['material_semantics'] or {}).get('source_notation',{}).get('version')=='materials-source-display/1':
            continue
        # Every compiled assertion must still cite precisely this retained
        # paper source. Missing/stale records are skipped, including empty DBs.
        matches=db.execute(sa.text("""SELECT count(DISTINCT c.id) FROM material_claims c
            JOIN event_evidence e ON e.event_id=c.event_id AND e.link_type='source'
            WHERE c.id::text=ANY(:claims) AND c.material_id=:material AND c.paper_id=:paper
              AND e.locator->'representation_input'->>'sha256'=:source"""),
            dict(claims=annotation['claims'],material=annotation['id'],
                 paper=annotation['paper_id'],source=annotation['source_sha256'])).scalar_one()
        if not annotation['claims'] or matches!=len(annotation['claims']):
            continue
        semantics=row['material_semantics'] or {}
        before=dict(family=row['family'],keys={k:semantics[k] for k in
                    ('family_classification','source_notation') if k in semantics})
        family=row['family'];patch=dict(source_notation=annotation['source_notation'],
                                        before_source_notation_v1=before)
        if family in (None,'unclassified') and annotation['family_classification']['family']!='unclassified':
            patch['family_classification']=annotation['family_classification']
            family=annotation['family_classification']['family']
        updates.append(dict(id=annotation['id'],family=family,patch=patch))
    if updates:
        db.execute(sa.text("""UPDATE materials m SET family=u.item->>'family',
            material_semantics=COALESCE(m.material_semantics,'{}'::jsonb)||(u.item->'patch')
            FROM jsonb_array_elements(CAST(:updates AS jsonb)) AS u(item)
            WHERE m.id=u.item->>'id'"""),dict(updates=json.dumps(updates)))


def downgrade():
    db=op.get_bind()
    guard="""material_semantics ? 'before_source_notation_v1'
        AND material_semantics->'source_notation'->>'version'='materials-source-display/1'"""
    if not db.execute(sa.text('SELECT EXISTS(SELECT 1 FROM materials WHERE '+guard+ ')')).scalar_one():
        return
    db.execute(sa.text("""UPDATE materials SET
        family=material_semantics->'before_source_notation_v1'->>'family',
        material_semantics=(material_semantics-'family_classification'-'source_notation'-'before_source_notation_v1')
            ||(material_semantics->'before_source_notation_v1'->'keys')
        WHERE """+guard))
