"""Hash-bound display projections; original scientific assertions never change."""
from functools import lru_cache
import json
from pathlib import Path

from services.materials_source_notation import sha256

VERSION = 'materials-source-display/1'


@lru_cache(maxsize=1)
def registry():
    return json.loads((Path(__file__).parent/'notation_data/materials_source_display_v1.json').read_text())


def display_projection(row, source_pins):
    annotation = registry()['records'].get(row['id'])
    if not annotation or annotation['paper_id'] != row['paper_id']:
        return {}
    if annotation['material_id'] != row['material_id'] or annotation['source_versions'] != row['source_versions']:
        return {}
    if set(source_pins) != {annotation['bundle_sha256']}:
        return {}
    result = {}
    for key, value in annotation['fields'].items():
        if key.startswith('composition:'):
            index = int(key.split(':')[1])
            compositions = row.get('compositions') or []
            raw = compositions[index]['formula'] if index < len(compositions) else None
        elif key == 'quantity_raw':
            raw = (row.get('quantity') or {}).get('raw')
        else:
            raw = row.get(key)
        if isinstance(raw,str) and sha256(raw) == value['raw_sha256']:
            result[key] = value['text']
    return result
