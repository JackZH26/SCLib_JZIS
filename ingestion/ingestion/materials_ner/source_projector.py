"""One source-bound automatic graph draft with an explicitly selected contract.

No reference answers are inputs. A completed draft is not semantic acceptance.
The frozen prose reader remains a separate baseline; this stage never rewrites it.
"""
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator
import tiktoken

from . import finite_stage, paper_coverage, reviewed_reader as reader, reviewed_proposals
from . import projection_binding, projector_schema, evidence_policy, scoped_evidence, source_focus
from .contract import canonical, digest, parse_extraction
from .quantities_v2 import UNITS
from .quantities_v3 import UNITS as UNITS_V3
from . import quantities_v4
from .sources import sha
from .validation import check_consistency_version

WORKFLOW = 'source_projector_v1'
INPUT_SCHEMA = 'materials-source-projector-input/1'
NATIVE14_INPUT_SCHEMA = 'materials-source-projector-input/2'
FOCUSED_INPUT_SCHEMA = 'materials-source-projector-input/3'
NATIVE15_INPUT_SCHEMA = 'materials-source-projector-input/4'
EXECUTION_PROFILE_SCHEMA = 'materials-source-projector-execution/1'
EXPLICIT_MODEL_PROFILE_SCHEMA = 'materials-source-projector-execution/2'
ATTEMPT_SCHEMA = 'materials-source-projector-attempt/3'
INSTRUCTION = Path(__file__).with_name('projector_protocol') / 'instruction.txt'
NATIVE14_INSTRUCTION = INSTRUCTION.with_name('native14.txt')
NATIVE15_INSTRUCTION = INSTRUCTION.with_name('native15.txt')


def implementation():
    files = sorted(Path(__file__).parent.glob('*.py'))
    files += [Path(__file__).parents[1] / 'extract/scientific_values.py', INSTRUCTION, NATIVE14_INSTRUCTION, NATIVE15_INSTRUCTION]
    return [reader.reference(path) for path in files]


def request_contract(request):
    """Native upgrades require an explicit version and source-ID request."""
    keys = {'schema', 'scope', 'coverage'}
    focused = isinstance(request, dict) and request.get('schema') == FOCUSED_INPUT_SCHEMA
    native15 = isinstance(request, dict) and request.get('schema') == NATIVE15_INPUT_SCHEMA
    new = isinstance(request, dict) and request.get('schema') in [NATIVE14_INPUT_SCHEMA, FOCUSED_INPUT_SCHEMA, NATIVE15_INPUT_SCHEMA]
    selected_contract = 'materials-ner/15' if native15 else 'materials-ner/14'
    if new:
        keys |= {'graph_schema', 'evidence_transport'}
    if focused:
        keys |= {'source_focus', 'execution_profile'}
    if native15:
        keys.add('consistency_version')
    optional = {'require_context_quote', 'evidence_transport'} | ({'interface_version', 'consistency_version'} if focused or native15 else set())
    if native15:optional.add('source_catalog_version')
    if (not isinstance(request, dict) or not keys <= set(request)
            or set(request)-keys-optional
            or request['schema'] not in [INPUT_SCHEMA, NATIVE14_INPUT_SCHEMA, FOCUSED_INPUT_SCHEMA, NATIVE15_INPUT_SCHEMA]
            or type(request.get('require_context_quote',False)) is not bool
            or ('evidence_transport' in request and request['evidence_transport'] != 'source_catalog')
            or (new and (request['graph_schema'] != selected_contract or request.get('require_context_quote',False)))):
        raise ValueError('projector_input_shape')
    if native15 and 'source_catalog_version' in request and request['source_catalog_version'] not in (scoped_evidence.VERSION,scoped_evidence.LINE_VERSION):
        raise ValueError('projector_source_catalog_version')
    if focused:
        profile = request['execution_profile']
        if (not isinstance(profile, dict) or set(profile) != {'schema', 'model', 'reasoning'}
                or profile['schema'] not in [EXECUTION_PROFILE_SCHEMA, EXPLICIT_MODEL_PROFILE_SCHEMA]
                or profile['model'] not in (['gpt-6-luna'] if profile['schema'] == EXECUTION_PROFILE_SCHEMA
                                            else ['gpt-6-luna', 'gpt-6.1-sol'])
                or profile['reasoning'] not in ['medium', 'high']):
            raise ValueError('projector_execution_profile_invalid')
    if focused or native15:
        if 'interface_version' in request:
            projector_schema.interface_version(selected_contract, request['interface_version'])
            if request['interface_version'] is None:
                raise ValueError('projector_unsupported_interface')
        if 'consistency_version' in request:
            check_consistency_version(request['consistency_version'], selected_contract)
    return selected_contract if new else 'materials-ner/13'


def prepare(path):
    path = Path(path).resolve()
    request = json.loads(path.read_bytes())
    graph_schema = request_contract(request)
    scope = reader.prepare_scope(reader.checked(request['scope']))
    _, bundle, _ = reader.source_input(scope['source_scope']['preflight'])
    manifest = json.loads(reader.checked(request['coverage']).read_bytes())
    paper_coverage.verify(manifest, bundle)
    # Coverage/reference assertions are used only by the validator, never the prompt.
    source_prompt = scope['prompt'][len(reader.protocol()[0]):]
    catalog = scoped_evidence.build(bundle,scope['source_scope'],version=request.get('source_catalog_version',scoped_evidence.VERSION)) if request.get('evidence_transport')=='source_catalog' else None
    instruction,policy = INSTRUCTION.read_text(),evidence_policy.render()
    if graph_schema in {'materials-ner/14', 'materials-ner/15'}:
        instruction = instruction.replace('materials-ner/13', graph_schema, 1) + NATIVE14_INSTRUCTION.read_text()
    if graph_schema == 'materials-ner/15':
        instruction += NATIVE15_INSTRUCTION.read_text()
    if catalog is not None:
        start=instruction.index('Evidence fields are entity-relative');end=instruction.index('\n\nRepresent missing',start)
        instruction=instruction[:start]+'''Evidence fields are entity-relative JSON pointers. For each supported field, select witness_ids from the original source catalogue. Return no evidence quotes, block IDs or character offsets. Bind each applicable field explicitly; selecting a span does not establish its meaning. Bind a complete /quantity and, when its value and unit are separated, its /raw and /unit pointers separately. For raw/unit pointers the compiler uses the unchanged scientific field as a literal selector inside only the selected spans. It must occur once as a full token; repeated or absent occurrences are held, never guessed. Other fields retain their selected original spans. Use a raw unit expression actually present in the source. Do not create scientific strings by joining separated source fragments. Preserve ambiguous attributions in limitations.''' + instruction[end:]
        start=policy.index('A short quote may be disambiguated');end=policy.index('Shared quantity policy:',start)
        policy=policy[:start]+policy[end:]
        instruction=instruction.replace('It must occur once as a full token; repeated or absent occurrences are held, never guessed.',
            'Raw expressions must occur once as full tokens. Units may use the unique bound inline raw occurrence as described below; other repeated or absent occurrences are held, never guessed.')
        instruction += '\nFor an inline unit, bind the original /quantity/raw occurrence and /quantity/unit explicitly. The compiler may locate that unit inside the uniquely bound raw expression, provided both refer to the selected original source. It never selects a nearby number or another specimen. Catalogue exclusions identify unpublished TeX comments; they do not certify complete publication or figure coverage.\n'
    prompt = instruction + policy + '\nWork ID: ' + bundle.work_id
    prompt += '\nOriginal block index: ' + canonical([b.id for b in bundle.blocks])
    units = {'materials-ner/13': UNITS, 'materials-ner/14': UNITS_V3, 'materials-ner/15': quantities_v4.UNITS}[graph_schema]
    source_units = {k:list(v[1]) for k,v in units.items()}
    if graph_schema == 'materials-ner/15':
        source_units['reported_displacement_field'] = list(quantities_v4.DISPLACEMENT_UNITS)
    prompt += '\nRegistered source units (not observations): ' + canonical(source_units)
    prompt += '\n' + source_prompt
    if catalog is not None:prompt += '\nORIGINAL SOURCE CATALOGUE\n' + canonical(catalog)
    focus = None
    if request['schema'] == FOCUSED_INPUT_SCHEMA:
        focus = json.loads(reader.checked(request['source_focus']).read_bytes())
        source_focus.verify(focus, bundle, scope['source_scope'], manifest, catalog)
        prompt += source_focus.prompt(focus)
    schema = projector_schema.output_schema(require_context_quote=request.get('require_context_quote',False),
        source_catalog=catalog,graph_schema=graph_schema, selected_interface=request.get('interface_version'))
    tokens = len(tiktoken.get_encoding('cl100k_base').encode(prompt + canonical(schema), disallowed_special=()))
    if tokens > 60000:
        raise ValueError('projector_input_budget_exceeded')
    pins = [reader.reference(path), request['scope'], request['coverage'], *scope['input_pins']]
    if focus is not None:
        pins.append(request['source_focus'])
    return dict(work_id=bundle.work_id, bundle_sha256=digest(bundle.model_dump()), request=request,
        bundle=bundle, coverage=manifest, scope=scope['source_scope'], prompt=prompt, schema=schema,
        input_tokens_estimate=tokens, input_pins=list({p['path']:p for p in pins}.values()),source_catalog=catalog,
        graph_schema=graph_schema, source_focus=focus)


def configuration(prepared):
    config = dict(workflow=WORKFLOW, provider='codex', model='gpt-6-luna', reasoning='medium',
        timeout_seconds=900, max_input_tokens=60000, automatic_attempts=1,
        request=prepared['input_pins'][0], input_pins=prepared['input_pins'],
        prompt_sha256=sha(prepared['prompt'].encode()), schema_sha256=digest(prepared['schema']),
        implementation=implementation(), output_kind='unaudited_compiled_native_graph',
        interface_version=projector_schema.interface_version(prepared['graph_schema'], prepared['request'].get('interface_version')), binding_version=projection_binding.VERSION,
        evidence_policy_version=evidence_policy.VERSION,
        require_context_quote=prepared['request'].get('require_context_quote',False),
        graph_schema=prepared['graph_schema'], scientific_acceptance=False)
    if prepared.get('source_catalog') is not None:
        config.update(evidence_transport='source_catalog',source_catalog_sha256=digest(prepared['source_catalog']))
    if prepared.get('source_focus') is not None:
        config.update(execution_profile=prepared['request']['execution_profile'],
            model=prepared['request']['execution_profile']['model'],
            reasoning=prepared['request']['execution_profile']['reasoning'],
            source_focus_version=source_focus.VERSION, source_focus_sha256=digest(prepared['source_focus']))
    if 'consistency_version' in prepared['request']:
        config['consistency_version'] = prepared['request']['consistency_version']
    return config


def enqueue(store, path):
    store._require_dispatch_enabled()
    p = prepare(path)
    return store.enqueue(work_id=p['work_id'], bundle_hash=p['bundle_sha256'], config=configuration(p), max_attempts=1)


ATTEMPTS_DIRECTORY = 'projector-attempts'
ERROR_PREFIX = 'projector'
INVALID_OUTCOME = 'graph_not_validated'
PROVENANCE = dict(graph_authorship='gpt-6-luna')
RESULT_PINS = ['graph','validation','model_graph','native_input_graph','interface_validation','model_validation','binding','source_catalog',
    'source_focus_inventory','source_focus_mapping']


def provenance(config):
    result = dict(graph_authorship=config['model'])
    if config.get('execution_profile', {}).get('schema') == EXPLICIT_MODEL_PROFILE_SCHEMA:
        # CodexProvider.model is the requested CLI alias, not a server attestation.
        # CLI completion and a thread ID do not establish an immutable model version.
        result['provider_model_identity'] = dict(schema='materials-codex-model-identity/1',
            requested_model=config['model'], served_model=None, immutable_model_version=None,
            verification='requested_only', source='codex_cli_model_argument')
    return result


def decode_output(text):
    def pairs(items):
        if len(dict(items)) != len(items):
            raise ValueError('projector_duplicate_json_key')
        return dict(items)
    return json.loads(text, object_pairs_hook=pairs)


def parse_output(text, *, graph_schema='materials-ner/13'):
    projector_schema.interface_version(graph_schema)
    graph = decode_output(text)
    parsed = parse_extraction(graph)
    if parsed.schema_version != graph_schema:
        raise ValueError('projector_native_contract_required')
    return parsed


def evaluate(p, text, directory, result):
    graph_schema = p['graph_schema']
    if p.get('source_focus') is not None:
        reader.put(directory / 'source-focus-inventory.json', source_focus.inventory(p['source_focus']))
        result['source_focus_inventory'] = reader.reference(directory / 'source-focus-inventory.json')
    raw_graph = decode_output(text)
    reader.put(directory / 'model-graph.json', raw_graph)
    result['model_graph'] = reader.reference(directory / 'model-graph.json')
    # No compiler repairs native scientific facts or a malformed graph.
    native_raw = projection_binding.native_graph(raw_graph)
    reader.put(directory / 'native-input-graph.json', native_raw)
    result['native_input_graph'] = reader.reference(directory / 'native-input-graph.json')
    parse_output(canonical(native_raw), graph_schema=graph_schema)
    result['raw_native_contract_valid'] = True
    interface_errors = [dict(location=list(e.absolute_path), validator=e.validator)
        for e in Draft202012Validator(p['schema']).iter_errors(raw_graph)]
    reader.put(directory / 'interface-validation.json', dict(valid=not interface_errors, issues=interface_errors))
    result['interface_validation'] = reader.reference(directory / 'interface-validation.json')
    capture = json.loads(reader.checked(p['scope']['image_capture']).read_bytes()) if p['scope']['image_capture'] else None
    _, raw_validation = reviewed_proposals.validate_graph(native_raw, p['bundle'], p['scope'], p['coverage'],
        image_capture=capture, allowed_contracts=(graph_schema,), consistency_version=p['request'].get('consistency_version'))
    if p.get('source_catalog') is not None:
        raw_validation['validation_scope']='native_scientific_payload_before_source_id_compilation'
    reader.put(directory / 'model-validation.json', raw_validation)
    result['model_validation'] = reader.reference(directory / 'model-validation.json')
    if p.get('source_catalog') is not None:
        reader.put(directory / 'source-catalog.json',p['source_catalog'])
        result['source_catalog']=reader.reference(directory / 'source-catalog.json')
        binding = projection_binding.compile_catalog_bindings(raw_graph,p['bundle'],p['scope'],p['coverage'],p['source_catalog'])
        result['evidence_transport']='source_catalog'
    else:
        binding = projection_binding.compile_bindings(raw_graph, p['bundle'], p['scope'], p['coverage'])
    reader.put(directory / 'binding.json', binding)
    result['binding'] = reader.reference(directory / 'binding.json')
    graph = parse_extraction(binding['graph'])
    reader.put(directory / 'graph.json', graph.model_dump())
    result['graph'] = reader.reference(directory / 'graph.json')
    if p.get('source_focus') is not None:
        reader.put(directory / 'source-focus-mapping.json', source_focus.mapping(p['source_focus'], graph.model_dump()))
        result['source_focus_mapping'] = reader.reference(directory / 'source-focus-mapping.json')
    _, validation = reviewed_proposals.validate_graph(graph.model_dump(), p['bundle'], p['scope'], p['coverage'],
        image_capture=capture, allowed_contracts=(graph_schema,), consistency_version=p['request'].get('consistency_version'))
    reader.put(directory / 'validation.json', validation)
    valid = validation['valid'] and not binding['holds'] and not interface_errors
    result.update(validation=reader.reference(directory / 'validation.json'),
        state='succeeded' if valid else 'quarantined',
        outcome='graph_drafted_pending_semantic_review',
        evidence_metadata_edits=len(binding['edits'])+len(binding.get('selections',[])), unresolved_binding_holds=len(binding['holds']),
        scientific_payload_unchanged=binding['scientific_payload_unchanged'],
        graph_transformation='deterministic_evidence_metadata_only',
        provider_only_locator_fields=['witness_ids'] if p.get('source_catalog') is not None else ['context_quote'],
        result_count=len(graph.results), deterministic_validation_valid=valid)
    return result


def row(store, identifier):
    return finite_stage.row(store, identifier, sys.modules[__name__])


def validate_job(job):
    return finite_stage.validate_job(job, sys.modules[__name__])


def terminal(job, directory, **kwargs):
    return finite_stage.terminal(job, directory, sys.modules[__name__], **kwargs)


def existing(job):
    return finite_stage.existing(job, sys.modules[__name__])


def recover(store, identifier):
    return finite_stage.recover(store, identifier, sys.modules[__name__])


def run(store, identifier, *, provider_override=None):
    return finite_stage.run(store, identifier, sys.modules[__name__], provider_override=provider_override)
