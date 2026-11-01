"""A compact 2D read of current NER admissions, never legacy JSON or invented years."""
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
import hashlib
from math import isfinite
import re
from uuid import UUID

from sqlalchemy import text

from models.materials_timeline import MaterialsTimeline, MaterialsTimelinePoint
from models.ml_foundation import ProductionAdmissionResponse
from services.materials_display import display_projection
from services.materials_family import current_family
from services.materials_vnext_read import BASE_WHERE, FROM


def report_date(submitted: date | None, paper_id: str):
    if submitted is not None:
        return submitted.isoformat(), 'paper_submission', 'day'
    match = re.fullmatch(r'arxiv:(?:[A-Za-z][A-Za-z.\-]*/(\d{2})(\d{2})\d{3}|(\d{2})(\d{2})\.\d{4,5})', paper_id)
    if match is None:
        return None
    yy, mm = int(match[1] or match[3]), int(match[2] or match[4])
    year = 1900 + yy if yy >= 91 else 2000 + yy
    if not 1991 <= year <= datetime.now(UTC).year + 1 or not 1 <= mm <= 12:
        return None
    return f'{year:04d}-{mm:02d}', 'arxiv_identifier_month', 'month'


def valid_quantity(row):
    finite = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and isfinite(v) and v >= 0
    rel = row['value_relation']
    lo, hi = row['value_lower_kelvin'], row['value_upper_kelvin']
    if rel == 'exact':
        return finite(row['value_kelvin'])
    if rel == 'interval':
        return finite(lo) and finite(hi) and lo <= hi
    return (rel in ('gt', 'ge') and finite(lo)) or (rel in ('lt', 'le') and finite(hi))


def display_sample(rows, budget):
    """Preserve every family's bounds and chronology; sample only for rendering."""
    if len(rows) <= budget:
        return sorted(rows, key=lambda r:(r['date'],r['id']))
    groups = defaultdict(list)
    for row in rows:
        groups[row['family']].append(row)
    chosen = {}
    value = lambda r: r['value_kelvin'] if r['value_kelvin'] is not None else (r['value_lower_kelvin'] or r['value_upper_kelvin'])
    for members in groups.values():
        protected = members if len(members) <= 10 else [min(members, key=lambda r:(value(r),r['id'])), max(members, key=lambda r:(value(r),r['id'])), min(members, key=lambda r:(r['date'],r['id'])), max(members, key=lambda r:(r['date'],r['id']))]
        chosen.update((r['id'], r) for r in protected)
    strata = defaultdict(list)
    for row in rows:
        strata[(row['family'], row['date'][:7], row['value_relation'])].append(row)
    queues = [sorted(group, key=lambda r:hashlib.sha256(r['id'].encode()).hexdigest()) for _, group in sorted(strata.items(), key=lambda pair:(len(pair[1]),pair[0]))]
    for depth in range(max(map(len, queues))):
        for group in queues:
            if len(chosen) >= budget:
                return sorted(chosen.values(), key=lambda r:(r['date'],r['id']))
            if depth < len(group):
                chosen[group[depth]['id']] = group[depth]
    return sorted(chosen.values(), key=lambda r:(r['date'],r['id']))


async def materials_timeline(db, *, max_points=20000):
    rows = (await db.execute(text('''SELECT c.id::text,c.material_id,c.paper_id,c.event_id::text,
        c.value_kelvin,c.value_lower_kelvin,c.value_upper_kelvin,c.value_relation,c.tc_definition,
        c.pressure_gpa,c.extraction_metadata->'production_admission' AS production_admission,
        c.extraction_metadata->'materials_outcome'->'quantity'->'approximate' AS approximate,
        s.conditions->'pressure'->>'regime' AS pressure_regime,
        m.formula,m.family,m.material_semantics,p.date_submitted
        ''' + FROM + ' WHERE ' + BASE_WHERE + ' ORDER BY c.paper_id,c.id LIMIT 100001'))).mappings().all()
    if len(rows) > 100000:
        raise ValueError('Timeline read capacity exceeded')
    families = Counter()
    dated = []
    missing_date = invalid_quantity = 0
    for original in rows:
        row = dict(original)
        if ProductionAdmissionResponse.from_extraction_metadata({'production_admission':row['production_admission']}) is None:
            raise ValueError('Invalid canonical admission provenance')
        row['family'] = current_family(row['formula'],row['family'],row['material_semantics'])
        families[row['family']] += 1
        if not valid_quantity(row):
            invalid_quantity += 1
            continue
        when = report_date(row['date_submitted'],row['paper_id'])
        if when is None:
            missing_date += 1
            continue
        row.update(date=when[0],date_basis=when[1],date_precision=when[2])
        dated.append(row)
    selected = display_sample(dated,max_points)
    versions = defaultdict(set)
    pins = defaultdict(set)
    if selected:
        ids = [UUID(r['id']) for r in selected]
        for claim, revision in (await db.execute(text('''SELECT o.claim_id::text,r.provider_revision
            FROM claim_source_occurrences o JOIN source_revisions r ON r.id=o.source_revision_id
            WHERE o.claim_id=ANY(:ids)'''),dict(ids=ids))).all():
            if revision:
                versions[claim].add(revision)
        for event, pin in (await db.execute(text('''SELECT event_id::text,locator->'representation_input'->>'sha256'
            FROM event_evidence WHERE event_id=ANY(:ids) AND link_type='source' '''),
            dict(ids=list({UUID(r['event_id']) for r in selected})))).all():
            if pin:
                pins[event].add(pin)
    points = []
    for row in selected:
        display = display_projection({**row,'source_versions':sorted(versions[row['id']])}, pins[row['event_id']])
        points.append(MaterialsTimelinePoint(
            **{k:row[k] for k in ('id','material_id','paper_id','family','date','date_basis','date_precision',
                'value_kelvin','value_lower_kelvin','value_upper_kelvin','value_relation','pressure_gpa')},
            formula=display.get('formula',row['formula']),criterion=row['tc_definition'],
            approximate=row['approximate'] is True,
            pressure_regime=row['pressure_regime'] if row['pressure_regime'] in ('explicit_ambient','nonambient') else 'unknown'))
    return MaterialsTimeline(points=points,total_results=len(rows),total_materials=len({r['material_id'] for r in rows}),
        total_papers=len({r['paper_id'] for r in rows}),plotted_results=len(dated),
        omitted_without_date=missing_date,omitted_invalid_quantity=invalid_quantity,sampled=len(selected)<len(dated),
        families=dict(sorted(families.items())),date_min=min((r['date'] for r in dated),default=None),
        date_max=max((r['date'] for r in dated),default=None))
