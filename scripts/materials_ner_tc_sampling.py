"""Predeclared paper-stratified sampling for Production-90 result batches."""
from collections import defaultdict
from fractions import Fraction

from ingestion.materials_ner.contract import digest

KEY=('work_id','result_id','run_id','projection_sha256')
METHOD='paper_stratified_without_replacement'
RANDOM_METHOD='simple_random_without_replacement'
BATCH_ROUTE='qualified_batch'
RECORD_ROUTE='individual_source_check'


def random_draw(eligible,seed,limit=50):
    """Fixed-size record sampling; paper count does not inflate model calls."""
    if not eligible or limit < 1:raise ValueError('nonempty_sampling_population_and_positive_limit_required')
    if len({tuple(r[k] for k in KEY) for r in eligible})!=len(eligible):
        raise ValueError('duplicate_sampling_record')
    selected=sorted(eligible,key=lambda r:digest([seed,*[r[k] for k in KEY]]))[:limit]
    return dict(method=RANDOM_METHOD,sample_limit=limit,
        records=[{k:r[k] for k in KEY} for r in selected])


def draw(eligible,seed,limit=50):
    groups=defaultdict(list)
    for row in eligible:groups[row['work_id']].append(row)
    if not groups:raise ValueError('empty_sampling_population')
    if len({tuple(r[k] for k in KEY) for r in eligible})!=len(eligible):
        raise ValueError('duplicate_sampling_record')
    target=min(len(eligible),max(limit,len(groups)))
    allocated={work:1 for work in groups}
    while sum(allocated.values())<target:
        work=max((w for w in groups if allocated[w]<len(groups[w])),
            key=lambda w:(Fraction(len(groups[w]),allocated[w]+1),digest([seed,w])))
        allocated[work]+=1
    selected=[];strata=[]
    rank=lambda r:digest([seed,*[r[k] for k in KEY]])
    for work in sorted(groups):
        rows=sorted(groups[work],key=rank);n=allocated[work]
        selected.extend(rows[:n]);strata.append(dict(work_id=work,population_size=len(rows),sample_size=n))
    return dict(method=METHOD,sample_limit=limit,strata=strata,
        records=[{k:r[k] for k in KEY} for r in sorted(selected,key=rank)])


def verify(selection):
    eligible=[r for r in selection['population'] if r['status']=='eligible_for_source_audit']
    sampler=random_draw if selection.get('method')==RANDOM_METHOD else draw
    design=sampler(eligible,selection['seed'],selection['sample_limit'])
    if any(selection.get(k)!=v for k,v in design.items()):raise ValueError('stratified_sampling_plan_changed')
    return design


def weighted_precision(selection,records):
    design=verify(selection)
    weights={s['work_id']:Fraction(s['population_size'],s['sample_size']) for s in design['strata']}
    total=sum(s['population_size'] for s in design['strata'])
    correct=sum((weights[r['work_id']] for r in records if r['verdict']=='correct'),Fraction(0))
    return float(correct/total)


def retained(projection,selection,audit,*,admission_route=BATCH_ROUTE):
    """Known incorrect/indeterminate sampled rows are never admitted."""
    if admission_route not in {BATCH_ROUTE,RECORD_ROUTE}:raise ValueError('unknown_admission_route')
    population=selection.get('population')
    scope=None if population is None else {tuple(r[k] for k in KEY)
        for r in population if r['status']=='eligible_for_source_audit'}
    candidates=[r for r in projection['records'] if r['status']=='eligible_for_source_audit'
        and (scope is None or (r['work_id'],r['result_id'],r['run_id'],projection['projection_sha256']) in scope)]
    if admission_route==RECORD_ROUTE:
        verified={tuple(r[k] for k in KEY) for r in audit['records']
            if r['verdict']=='correct' and r.get('review_completed') is True}
        return [r for r in candidates
            if (r['work_id'],r['result_id'],r['run_id'],projection['projection_sha256']) in verified]
    verdicts={tuple(r[k] for k in KEY):r['verdict'] for r in audit['records']}
    sampled_batch=selection.get('method') in {METHOD,RANDOM_METHOD}
    return [r for r in candidates
        if (verdicts.get((r['work_id'],r['result_id'],r['run_id'],projection['projection_sha256']))=='correct'
            or sampled_batch and (r['work_id'],r['result_id'],r['run_id'],projection['projection_sha256']) not in verdicts)]
