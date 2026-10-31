"""Bind printed figure labels to existing state conditions for development review.

This source-preparation tool does not change the extraction validator, fill a
missing text quote, dispatch a model or admit a proposal. The same protocol can
use several discrete states without manufacturing additional result rows.
"""
from copy import deepcopy

from ingestion.materials_ner import paper_coverage, visual_regions
from ingestion.materials_ner.contract import canonical, digest, parse_extraction
from ingestion.materials_ner.field_quantity import field_quantity_issues
from ingestion.materials_ner.quantities_v4 import normalize
from types import SimpleNamespace

VERSION = 'materials-visual-condition-reference/1'


def require(value, code):
    if not value:
        raise ValueError('visual_condition_' + code)


def build(*, bundle, graph, scope, assets, panels, bindings, author, created_at):
    body = dict(schema=VERSION, work_id=bundle.work_id,
        bundle_sha256=digest(bundle.model_dump()), graph_sha256=digest(graph),
        scope_sha256=digest(scope), assets=assets, panels=panels, bindings=bindings,
        author=author, created_at=created_at, independent_review=False,
        scientific_acceptance=False, ml_training_eligible=False,
        transcription_basis='assistant_selected_ocr_of_printed_label')
    support = deepcopy(dict(body, support_sha256=digest(body)))
    resolve(support, bundle, graph, scope)
    return support


def resolve(support, bundle, graph, scope):
    """Portable replay of pixels, selectors, numeric shape and context FKs.

Panel ownership is an attributed development annotation, not an independent
scientific judgment. Original text and original extraction remain unchanged.
    """
    require(isinstance(support, dict) and set(support) == {
        'schema', 'work_id', 'bundle_sha256', 'graph_sha256', 'scope_sha256',
        'assets', 'panels', 'bindings', 'author', 'created_at', 'independent_review',
        'scientific_acceptance', 'ml_training_eligible', 'transcription_basis',
        'support_sha256'}, 'support_shape')
    require(len(canonical(support).encode()) <= visual_regions.MAX_SUPPORT_BYTES,
            'support_size')
    paper_coverage.authorship(support['author'], support['created_at'])
    require(support['schema'] == VERSION and support['work_id'] == bundle.work_id
        and support['bundle_sha256'] == digest(bundle.model_dump())
        and support['graph_sha256'] == digest(graph)
        and support['scope_sha256'] == digest(scope)
        and support['support_sha256'] == digest({k: v for k, v in support.items()
            if k != 'support_sha256'}), 'source_identity')
    require(all(support[k] is False for k in ['independent_review',
        'scientific_acceptance', 'ml_training_eligible']) and
        support['transcription_basis'] == 'assistant_selected_ocr_of_printed_label',
        'authority')
    extraction = parse_extraction(graph)
    require(extraction.work_id == bundle.work_id, 'work_identity')
    require(0 < len(support['assets']) <= 4 and 0 < len(support['panels']) <= 20
        and 0 < len(support['bindings']) <= 100, 'counts')
    assets = {a['asset_id']: visual_regions.verify_asset(a, bundle)
              for a in support['assets']}
    require(len(assets) == len(support['assets']), 'duplicate_asset')
    protocols = {p.id: p for p in extraction.protocols}
    results = {r.id: r for r in extraction.results}
    states = {s.id: (i, s) for i, s in enumerate(extraction.states)}
    targets = [p for p in scope['passages'] if p['role'] == 'target']
    panels = {}; used_assets = set()
    for panel in support['panels']:
        require(set(panel) == {'id', 'asset_id', 'region', 'caption', 'basis',
            'protocol_id', 'result_ids', 'interpretation_note'}, 'panel_shape')
        require(isinstance(panel['id'], str) and bool(panel['id'].strip())
            and panel['id'] not in panels and panel['asset_id'] in assets
            and panel['protocol_id'] in protocols and panel['result_ids']
            and len(set(panel['result_ids'])) == len(panel['result_ids'])
            and isinstance(panel['interpretation_note'], str)
            and bool(panel['interpretation_note'].strip()), 'panel_identity')
        visual_regions.box(panel['region'])
        image, _ = assets[panel['asset_id']]
        require(0 < len(panel['basis']) <= 10, 'panel_basis')
        for anchor in [panel['caption'], *panel['basis']]:
            block = paper_coverage.anchor(anchor, bundle)
            require(block.id in image['original_block_ids']
                and block.id in extraction.processed_block_ids, 'panel_page')
            whole = dict(block_id=block.id, start_char=0, end_char=len(block.text))
            require(paper_coverage.inside(whole, targets), 'full_target_page')
        for identifier in panel['result_ids']:
            require(identifier in results and results[identifier].protocol_id ==
                panel['protocol_id'], 'result_protocol')
        panels[panel['id']] = panel; used_assets.add(panel['asset_id'])
    require(used_assets == set(assets), 'unused_asset')
    resolved = []; used_targets = set(); used_selectors = set(); used_panels = set()
    for binding in support['bindings']:
        require(set(binding) == {'panel_id', 'state_id', 'condition_id',
            'selector', 'transcription', 'interpretation_note'}, 'binding_shape')
        require(binding['panel_id'] in panels and binding['state_id'] in states
            and isinstance(binding['interpretation_note'], str)
            and bool(binding['interpretation_note'].strip()), 'binding_identity')
        panel = panels[binding['panel_id']]
        state_number, state = states[binding['state_id']]
        selected = [(i, c) for i, c in enumerate(state.conditions)
                    if c.id == binding['condition_id']]
        require(len(selected) == 1, 'condition_identity')
        condition_number, condition = selected[0]
        identity = (state.id, condition.id)
        require(identity not in used_targets, 'duplicate_target')
        used_targets.add(identity); used_panels.add(panel['id'])
        protocol = protocols[panel['protocol_id']]
        require(identity in {(u.state_id, u.condition_id) for u in protocol.context_uses},
                'condition_not_used_by_protocol')
        require(all(results[r].sample_id == state.sample_id for r in panel['result_ids']),
                'cross_sample')
        require(condition.role == 'measurement' and condition.quantity.status == 'reported',
                'reported_measurement_required')
        field = f'/conditions/{condition_number}/quantity'
        # A parent caption may explain a condition, but cannot substitute for a
        # printed numeric label. Keep any contradictory textual witness visible.
        require(not any(e.field == field or e.field.startswith(field + '/')
            for e in state.evidence), 'competing_quantity_witness')
        image, observed = assets[panel['asset_id']]
        selector = binding['selector']
        require(set(selector) == {'line_id', 'start_char', 'end_char'}, 'selector_shape')
        line = next((o for o in observed['observations'] if o['id'] == selector['line_id']), None)
        require(line is not None, 'selector_line')
        a, z = selector['start_char'], selector['end_char']
        require(type(a) is int and type(z) is int and 0 <= a < z <= len(line['text'])
            and line['text'][a:z] == binding['transcription'], 'transcription')
        words = [v for v in line['words'] if a <= v['start_char'] and v['end_char'] <= z]
        require(words and words[0]['start_char'] == a and words[-1]['end_char'] == z
            and all(visual_regions.contains(panel['region'], v['box']) for v in words),
            'selector_outside_panel')
        if observed['schema'] == 'materials-vision-text/2':
            require(all(visual_regions.contains(observed['region_of_interest'], v['box'])
                for v in words), 'selector_outside_ocr_region')
        optical_identity = (image['sha256'], selector['line_id'], a, z)
        require(optical_identity not in used_selectors, 'printed_label_reused')
        used_selectors.add(optical_identity)
        require(condition.quantity.raw == binding['transcription'], 'raw_not_exact_transcription')
        witness = [SimpleNamespace(field=field + '/raw', quote=binding['transcription'])]
        issues = field_quantity_issues(condition.quantity, witness, field)
        require(not issues, 'quantity_' + '_'.join(issues))
        normalized = normalize(condition.kind, condition.quantity)
        resolved.append(dict(kind='visual_region', support_schema=VERSION,
            path=f'/states/{state_number}{field}', state_id=state.id,
            condition_id=condition.id, protocol_id=panel['protocol_id'],
            result_ids=panel['result_ids'], asset_id=panel['asset_id'], panel_id=panel['id'],
            panel_region=panel['region'], selector=selector, transcription=binding['transcription'],
            source_sha256=image['pdf_sha256'], page=image['pdf_page'],
            image_sha256=image['sha256'], caption=panel['caption'], basis=panel['basis'],
            normalized=normalized, support_sha256=support['support_sha256'],
            independent_review=False, scientific_acceptance=False, ml_training_eligible=False))
    require(used_panels == set(panels), 'unused_panel')
    return resolved


def assess(support, bundle, graph, scope):
    """Account for supported fields without overriding production validation.

Only the missing numeric text witness is addressed by the verified optical
binding. Missing scientific meaning, relations and incomplete coverage remain.
    """
    from ingestion.materials_ner.validation import validate_extraction
    resolved = resolve(support, bundle, graph, scope)
    native = validate_extraction(parse_extraction(graph), bundle)
    paths = {item['path'] for item in resolved}
    addressed = [issue for issue in native['issues'] if issue['path'] in paths
        and issue['code'] == 'quantity_raw_not_in_field_evidence']
    remaining = [issue for issue in native['issues'] if issue not in addressed]
    return dict(native_validation=native, resolved_visual_conditions=resolved,
        numeric_text_holds_addressed_by_visual=addressed, remaining_native_issues=remaining,
        independent_review=False, scientific_acceptance=False, ml_training_eligible=False,
        production_validator_overridden=False, proposal_import_permitted=False)
