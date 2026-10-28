"""Sparse printed-label evidence, separate from immutable extracted PDF text.

OCR is a retained optical observation, not an independent scientific reader.
Only an explicitly authored region binding can support a result quantity.
"""
import base64
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from . import page_images, paper_coverage as coverage
from .contract import canonical, digest
from .sources import sha

VERSION = 'materials-visual-result-evidence/1'
NAMED_VERSION = 'materials-visual-result-evidence/2'
ASSET_VERSION = 'materials-optical-page/1'
REGION_ASSET_VERSION = 'materials-optical-page/2'
MAX_SUPPORT_BYTES = 4 * 1024 * 1024


def require(value, code):
    if not value: raise ValueError('visual_' + code)


def pin(value):
    require(isinstance(value, dict) and set(value) == {'path', 'sha256', 'bytes'}, 'pin_shape')
    require(isinstance(value['path'], str) and Path(value['path']).is_absolute()
            and type(value['bytes']) is int and value['bytes'] > 0
            and re.fullmatch('[0-9a-f]{64}', value['sha256']) is not None, 'pin_value')


def box(value):
    require(isinstance(value, list) and len(value) == 4
            and all(type(x) in {int, float} and math.isfinite(x) for x in value)
            and 0 <= value[0] < value[2] <= 1 and 0 <= value[1] < value[3] <= 1, 'region_bounds')


def contains(outer, inner):
    return outer[0] <= inner[0] and outer[1] <= inner[1] and inner[2] <= outer[2] and inner[3] <= outer[3]


def render_pdf(original, renderer, page, dpi):
    """Bounded local rendering; no shell, URL, crop, rescaling or generated image."""
    from .reviewed_reader import checked
    require(type(page) is int and page > 0 and type(dpi) is int and 72 <= dpi <= 240, 'render_bounds')
    source, executable = checked(original), checked(renderer)
    with tempfile.TemporaryDirectory(prefix='materials-page-') as directory:
        output = Path(directory) / 'page'
        completed = subprocess.run([str(executable), '-r', str(dpi), '-f', str(page), '-l', str(page),
            '-singlefile', '-png', str(source), str(output)], capture_output=True, timeout=60)
        require(completed.returncode == 0, 'render_failed')
        path = output.with_suffix('.png')
        require(path.is_file() and path.stat().st_size <= page_images.MAX_BYTES, 'render_size')
        raw = path.read_bytes(); page_images.png_size(raw)
        return raw


def capture_pdf(preflight_pin, *, page, dpi, renderer, ocr_executable, ocr_source, ocr_region=None):
    from .reviewed_reader import checked, reference, source_input
    preflight, bundle, _ = source_input(preflight_pin)
    renderer_pin = reference(renderer); executable_pin = reference(ocr_executable); source_pin = reference(ocr_source)
    raw = render_pdf(preflight['original'], renderer_pin, page, dpi)
    if ocr_region is not None: box(ocr_region)
    with tempfile.TemporaryDirectory(prefix='materials-optical-') as directory:
        image = Path(directory) / 'page.png'; image.write_bytes(raw)
        command = [str(checked(executable_pin)), str(image)]
        if ocr_region is not None: command.append(canonical(ocr_region))
        result = subprocess.run(command, capture_output=True, timeout=60)
        require(result.returncode == 0 and not result.stderr and len(result.stdout) <= 1024 * 1024, 'ocr_process_failed')
        if ocr_region is not None:
            require(json.loads(result.stdout).get('region_of_interest') == ocr_region, 'ocr_region_request_mismatch')
    capture = page_images.freeze(bundle, [dict(pdf_sha256=preflight['original']['sha256'], pdf_page=page,
        rendering=dict(tool='pdftoppm', executable=renderer_pin, source=preflight['original'], page=page, dpi=dpi), raw=raw)])
    body = dict(schema=REGION_ASSET_VERSION if ocr_region is not None else ASSET_VERSION,
        capture=capture, ocr_json=result.stdout.decode(),
        ocr_sha256=sha(result.stdout), ocr_executable=executable_pin, ocr_source=source_pin)
    asset = dict(body, asset_id=digest(body)); verify_asset(asset, bundle)
    return asset


def verify_asset(asset, bundle):
    require(isinstance(asset, dict) and set(asset) == {'schema', 'capture', 'ocr_json', 'ocr_sha256',
            'ocr_executable', 'ocr_source', 'asset_id'} and asset['schema'] in {ASSET_VERSION, REGION_ASSET_VERSION}, 'asset_shape')
    require(digest({k: v for k, v in asset.items() if k != 'asset_id'}) == asset['asset_id'], 'asset_hash')
    for name in ['ocr_executable', 'ocr_source']: pin(asset[name])
    page_images.verify(asset['capture'], bundle)
    require(len(asset['capture']['pages']) == 1, 'one_page_per_asset')
    image = asset['capture']['pages'][0]; rendering = image['rendering']
    require(set(rendering) == {'tool', 'executable', 'source', 'page', 'dpi'}
            and rendering['tool'] == 'pdftoppm' and rendering['page'] == image['pdf_page']
            and type(rendering['dpi']) is int and 72 <= rendering['dpi'] <= 240, 'render_recipe')
    pin(rendering['executable']); pin(rendering['source'])
    require(rendering['source']['sha256'] == image['pdf_sha256'], 'render_source')
    require(isinstance(asset['ocr_json'], str) and len(asset['ocr_json'].encode()) <= 1024 * 1024
            and sha(asset['ocr_json'].encode()) == asset['ocr_sha256'], 'ocr_hash')
    observed = json.loads(asset['ocr_json'])
    regional = asset['schema'] == REGION_ASSET_VERSION
    if regional:
        box(observed.get('region_of_interest'))
        require(type(observed.get('minimum_text_height')) in {float, int}
            and math.isclose(observed['minimum_text_height'], .001, rel_tol=1e-6), 'ocr_minimum_text_height')
        require(observed.get('recognizer_coordinate_system') == 'normalized_roi_lower_left'
            and observed.get('coordinates_transformed_to_full_page') is True, 'ocr_coordinate_transform')
    require(observed['schema'] == ('materials-vision-text/2' if regional else 'materials-vision-text/1')
            and observed['recognizer'] == 'Apple Vision VNRecognizeTextRequest' and observed['revision'] == 3
            and observed['recognition_level'] == 'accurate' and observed['language_correction'] is False
            and observed['recognition_languages'] == ['en-US']
            and observed['coordinate_system'] == 'normalized_top_left_xyxy'
            and observed['coordinate_precision'] == 'approximate_word_boxes'
            and observed['scientific_acceptance'] is False, 'ocr_configuration')
    require(observed['image_sha256'] == image['sha256'] and observed['width'] == image['width']
            and observed['height'] == image['height']
            and observed['image_bytes'] == len(base64.b64decode(image['png_base64'], validate=True)), 'ocr_image_binding')
    require(isinstance(observed['observations'], list) and len(observed['observations']) <= 10000, 'ocr_count')
    seen = set()
    for line in observed['observations']:
        require(set(line) == {'id', 'text', 'box', 'confidence', 'words'} and line['id'] not in seen
                and isinstance(line['text'], str) and line['text'].strip()
                and type(line['confidence']) in {float, int} and 0 <= line['confidence'] <= 1, 'ocr_line')
        seen.add(line['id']); box(line['box']); end = 0
        for word in line['words']:
            require(set(word) == {'text', 'start_char', 'end_char', 'box'}, 'ocr_word')
            a, z = word['start_char'], word['end_char']
            require(type(a) is int and type(z) is int and end <= a < z <= len(line['text'])
                    and line['text'][a:z] == word['text'] and not any(c.isspace() for c in word['text']), 'ocr_word_selector')
            box(word['box']); end = z
    return image, observed


def verify_local_assets(support, bundle):
    """The ingestion boundary also checks the actual PDF-to-PNG relationship."""
    from .reviewed_reader import checked, reference
    # Never execute a command selected by a received evidence packet. The
    # operator's local configuration selects the executable; a pin only checks it.
    renderer = reference(configured_renderer())
    for asset in support['assets']:
        image, _ = verify_asset(asset, bundle); recipe = image['rendering']
        require(all(renderer[k] == recipe['executable'][k] for k in ['sha256', 'bytes']), 'renderer_not_configured')
        checked(asset['ocr_executable']); checked(asset['ocr_source'])
        raw = render_pdf(recipe['source'], renderer, recipe['page'], recipe['dpi'])
        require(sha(raw) == image['sha256'], 'local_render_mismatch')


def configured_renderer():
    configured = os.environ.get('MATERIALS_NER_PDF_RENDERER')
    if configured: return Path(configured)
    bundled = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/override/pdftoppm'
    if bundled.is_file(): return bundled
    executable = shutil.which('pdftoppm')
    require(executable is not None, 'configured_renderer_unavailable')
    return Path(executable)


def build(*, bundle, manifest, scope, extraction, assets, bindings, author, created_at, version=VERSION):
    body = dict(schema=version, work_id=bundle.work_id, bundle_sha256=digest(bundle.model_dump()),
        coverage_hash=manifest['coverage_hash'], assets=assets, bindings=bindings, author=author, created_at=created_at,
        transcription_basis='assistant_selected_ocr_of_printed_label', independent_review=False,
        scientific_acceptance=False, ml_training_eligible=False)
    support = deepcopy(dict(body, support_sha256=digest(body)))
    resolve(support, bundle, manifest, scope, extraction)
    return support


def resolve(support, bundle, manifest, scope, extraction):
    """Replay original-image, optical-selector, target scope and result bindings."""
    require(isinstance(support, dict) and set(support) == {'schema', 'work_id', 'bundle_sha256', 'coverage_hash',
        'assets', 'bindings', 'author', 'created_at', 'transcription_basis', 'independent_review',
        'scientific_acceptance', 'ml_training_eligible', 'support_sha256'}, 'support_shape')
    require(len(canonical(support).encode()) <= MAX_SUPPORT_BYTES, 'support_size')
    coverage.authorship(support['author'], support['created_at']); coverage.verify(manifest, bundle)
    require(support['schema'] in {VERSION, NAMED_VERSION} and support['work_id'] == bundle.work_id
            and support['bundle_sha256'] == digest(bundle.model_dump()) and support['coverage_hash'] == manifest['coverage_hash']
            and digest({k: v for k, v in support.items() if k != 'support_sha256'}) == support['support_sha256'], 'support_identity')
    require(support['transcription_basis'] == 'assistant_selected_ocr_of_printed_label'
            and all(support[k] is False for k in ['independent_review', 'scientific_acceptance', 'ml_training_eligible']), 'authority')
    require(0 < len(support['assets']) <= 4 and 0 < len(support['bindings']) <= 100, 'support_count')
    if support['schema'] == VERSION:
        require(all(a['schema'] == ASSET_VERSION for a in support['assets']), 'legacy_asset_policy')
    assets = {a['asset_id']: verify_asset(a, bundle) for a in support['assets']}
    require(len(assets) == len(support['assets']), 'duplicate_asset')
    assertions = {a['id']: a for a in manifest['assertions']}; blocks = {b.id: b for b in bundle.blocks}
    results = {r.id: (i, r) for i, r in enumerate(extraction.results)}
    resolved = []; selected = set(); assertion_ids = set(); used_assets = set(); used_selectors = set()
    targets = [p for p in scope['passages'] if p['role'] == 'target']
    for binding in support['bindings']:
        require(set(binding) == {'result_id', 'field', 'asset_id', 'assertion_id', 'selector', 'transcription', 'interpretation_note'}
                and binding['field'] == '/quantity' and isinstance(binding['interpretation_note'], str)
                and binding['interpretation_note'].strip(), 'binding_shape')
        require(binding['result_id'] in results and binding['result_id'] not in selected
                and binding['assertion_id'] in assertions and binding['assertion_id'] not in assertion_ids
                and binding['asset_id'] in assets, 'binding_identity')
        selected.add(binding['result_id']); assertion_ids.add(binding['assertion_id']); used_assets.add(binding['asset_id'])
        number, result = results[binding['result_id']]; assertion = assertions[binding['assertion_id']]
        # V2 preserves named, unregistered quantities for domain review. It does
        # not register their meaning, convert their units or qualify a label.
        # V1 retains its historical rejection, including during portable replay.
        allowed_unmapped = (support['schema'] == NAMED_VERSION and result.quantity_kind == 'unmapped'
            and isinstance(result.quantity_name_raw, str) and bool(result.quantity_name_raw.strip()))
        require(result.quantity.status == 'reported' and result.quantity_kind != 'non_detection'
                and (result.quantity_kind != 'unmapped' or allowed_unmapped)
                and not any(e.field == '/quantity' or e.field.startswith('/quantity/') for e in result.evidence), 'quantity_source_conflict')
        image, observed = assets[binding['asset_id']]
        require(assertion['kind'] == 'figure_label' and assertion['visual']['unit_id'] == f"page:{image['pdf_page']}"
                and assertion['visual']['image']['sha256'] == image['sha256']
                and assertion['visual']['image']['bytes'] == observed['image_bytes']
                and image['pdf_sha256'] == manifest['source']['original']['sha256']
                and image['rendering']['source'] == manifest['source']['original'], 'assertion_image_binding')
        caption = assertion['anchor']; block = coverage.anchor(caption, bundle)
        require(block.id in image['original_block_ids'] and block.id in extraction.processed_block_ids, 'caption_page_binding')
        whole_page = dict(block_id=block.id, start_char=0, end_char=len(block.text))
        require(coverage.inside(whole_page, targets) and coverage.published(whole_page, manifest, bundle), 'full_target_page_required')
        selector = binding['selector']
        require(set(selector) == {'line_id', 'start_char', 'end_char'}, 'selector_shape')
        line = next((x for x in observed['observations'] if x['id'] == selector['line_id']), None)
        require(line is not None, 'ocr_line_missing')
        a, z = selector['start_char'], selector['end_char']
        require(type(a) is int and type(z) is int and 0 <= a < z <= len(line['text'])
                and line['text'][a:z] == binding['transcription'], 'transcription_selector')
        words = [w for w in line['words'] if a <= w['start_char'] and w['end_char'] <= z]
        require(words and words[0]['start_char'] == a and words[-1]['end_char'] == z
                and all(contains(assertion['visual']['region'], w['box']) for w in words), 'selected_words_outside_region')
        if observed['schema'] == 'materials-vision-text/2':
            require(all(contains(observed['region_of_interest'], w['box']) for w in words), 'selected_words_outside_ocr_region')
        source_identity = (image['sha256'], selector['line_id'], a, z)
        require(source_identity not in used_selectors, 'printed_label_reused_requires_review')
        used_selectors.add(source_identity)
        require(coverage.literal_value_in_quote(result.quantity.raw, binding['transcription']), 'quantity_not_transcribed')
        # Assertion labels are assistant annotations; compare lexical numeric
        # content, never use them as substitutes for pixels or OCR observations.
        require(coverage.literal_value_in_quote(re.sub(r'\s+', '', result.quantity.raw),
            re.sub(r'\s+', '', assertion['visual']['label'])), 'assertion_label_disagrees')
        resolved.append(dict(kind='visual_region', path=f'/results/{number}/quantity', result_id=result.id,
            document_id=block.document_id, block_id=block.id, block_sha256=block.sha256, locator=block.locator,
            asset_id=binding['asset_id'], assertion_id=assertion['id'], source_sha256=image['pdf_sha256'],
            publication_version=manifest['source']['publication_version'], page=image['pdf_page'], image_sha256=image['sha256'],
            region=assertion['visual']['region'], coordinate_system='normalized_top_left_xyxy',
            coordinate_precision='approximate_word_boxes', selector=selector, caption=caption,
            transcription=binding['transcription'], transcription_sha256=sha(binding['transcription'].encode()),
            transcription_author=support['author'], support_sha256=support['support_sha256'],
            **({'support_schema': NAMED_VERSION} if support['schema'] == NAMED_VERSION else {})))
    require(used_assets == set(assets), 'unused_asset')
    return resolved
