"""Read projections of imported visual receipts; never a scientific approval."""
import base64
import hashlib
import json
from copy import deepcopy

from services.materials_proposal_storage import digest


def passage(packet, ordinal, evidence):
    from services.materials_proposal_review import require
    support = packet['receipt'].get('visual_support')
    require(isinstance(support, dict) and support.get('schema') in {
        'materials-visual-result-evidence/1', 'materials-visual-result-evidence/2'}, 'visual_support_missing')
    if support['schema'] == 'materials-visual-result-evidence/2':
        require(evidence.get('support_schema') == support['schema'], 'visual_policy_mismatch')
    require(digest({k: v for k, v in support.items() if k != 'support_sha256'})
            == support['support_sha256'] == evidence['support_sha256'], 'visual_support_hash')
    require(evidence in packet['receipt']['validation']['resolved_evidence'], 'visual_binding_not_retained')
    require(not any(k in evidence for k in ['start_char', 'end_char', 'quote_sha256', 'quote']), 'visual_is_not_original_text')
    asset = next((a for a in support['assets'] if a['asset_id'] == evidence['asset_id']), None)
    require(asset is not None and digest({k: v for k, v in asset.items() if k != 'asset_id'}) == asset['asset_id'], 'visual_asset_hash')
    capture = asset['capture']
    require(digest({k: v for k, v in capture.items() if k != 'capture_sha256'}) == capture['capture_sha256']
            and capture['bundle_sha256'] == packet['bundle_hash'] and len(capture['pages']) == 1, 'visual_capture_binding')
    page = capture['pages'][0]
    require(page['sha256'] == evidence['image_sha256'] and page['pdf_page'] == evidence['page']
            and page['pdf_sha256'] == evidence['source_sha256'] and evidence['block_id'] in page['original_block_ids'], 'visual_page_binding')
    observed = json.loads(asset['ocr_json'])
    require(hashlib.sha256(asset['ocr_json'].encode()).hexdigest() == asset['ocr_sha256']
            and observed['image_sha256'] == page['sha256'], 'visual_ocr_binding')
    selected = evidence['selector']; line = next((x for x in observed['observations'] if x['id'] == selected['line_id']), None)
    require(line is not None, 'visual_line_missing')
    start, end = selected['start_char'], selected['end_char']
    require(type(start) is int and type(end) is int and 0 <= start < end <= len(line['text'])
            and line['text'][start:end] == evidence['transcription']
            and hashlib.sha256(evidence['transcription'].encode()).hexdigest() == evidence['transcription_sha256'], 'visual_transcription_mismatch')
    # Ordinals and original page identifiers stay compatible with the existing
    # evidence store; optical offsets describe only the retained OCR string.
    return dict(deepcopy(evidence), ordinal=ordinal, original_text_quote=False,
                asset_path='source-images/' + page['sha256'] + '.png',
                provenance_path='visual-evidence.json')


def export_files(packet):
    from services.materials_proposal_review import require
    from services.materials_proposal_storage import canonical
    support = packet['receipt'].get('visual_support')
    if support is None: return {}
    files = {'visual-evidence.json': (canonical(support) + '\n').encode()}
    for ordinal, evidence in enumerate(packet['evidence']):
        if evidence.get('kind') != 'visual_region': continue
        item = passage(packet, ordinal, evidence)
        asset = next(a for a in support['assets'] if a['asset_id'] == evidence['asset_id'])
        page = asset['capture']['pages'][0]
        require(len(page['png_base64']) <= 16_000_004, 'visual_image_limit')
        raw = base64.b64decode(page['png_base64'], validate=True)
        require(hashlib.sha256(raw).hexdigest() == page['sha256'], 'visual_image_hash')
        files[item['asset_path']] = raw
    return files
