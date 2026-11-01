"""Compile source-resolved family/search annotations after the full display audit."""
import argparse
import json
from collections import defaultdict
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'api'))
from services.materials_family_v1 import classify_material_family
from services.materials_source_notation import sha256

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['public-data','render-audit','display-registry','output']:
        p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();page=json.loads(a.public_data.read_text())
    audit=json.loads(a.render_audit.read_text());registry=json.loads(a.display_registry.read_text())
    if audit['summary']['visible_leaks'] or audit['summary']['unresolved_formulas']:
        raise ValueError('Resolve formula display failures before family annotation')
    grouped=defaultdict(list)
    for row in page['items']:
        if 'formula' in registry['records'].get(row['id'],{}).get('fields',{}):
            grouped[row['material_id']].append(row)
    updates=[]
    for material,rows in sorted(grouped.items()):
        formulas={audit['formulas'][r['id']] for r in rows}
        papers={r['paper_id'] for r in rows}
        pins={registry['records'][r['id']]['bundle_sha256'] for r in rows}
        raw={r['formula'] for r in rows}
        if len(formulas)!=1 or len(papers)!=1 or len(pins)!=1 or len(raw)!=1:
            raise ValueError('Ambiguous material annotation')
        formula=next(iter(formulas));raw=next(iter(raw));derived=classify_material_family(formula)
        derived.update(formula_sha256=sha256(raw),basis='source_resolved_reported_formula',
                       resolved_formula_sha256=sha256(formula))
        updates.append(dict(id=material,paper_id=next(iter(papers)),claims=sorted(r['id'] for r in rows),
            source_sha256=next(iter(pins)),formula_sha256=sha256(raw),
            family_classification=derived,source_notation=dict(
                version='materials-source-display/1',formula_sha256=sha256(raw),text=formula,
                source_bundle_sha256=next(iter(pins)))))
    a.output.write_text(json.dumps(dict(version='materials-source-display/1',materials=updates),ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(materials=len(updates),classified=sum(x['family_classification']['family']!='unclassified' for x in updates))))

if __name__=='__main__':main()
