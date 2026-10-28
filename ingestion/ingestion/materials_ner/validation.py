"""Deterministic integrity checks, never automatic scientific acceptance."""
from __future__ import annotations

import re
from .contract import Extraction, digest
from .sources import Bundle, sha, verify_bundle
from .evidence_policy import required as policy_required, COMPONENT_KINDS
from .quantities import (REGISTRY_VERSION, lexical, normalize, quantity_source_issues,
                         unmapped_quantity_source_issues)

VALIDATOR_VERSION = "materials-ner-validation/1.21.0"
POSITIONED_VALIDATOR_VERSION = "materials-ner-validation/1.22.0"
ADOPTED_VALIDATOR_VERSION = "materials-ner-validation/1.23.0"
PRESSURE_VALIDATOR_VERSION = "materials-ner-validation/1.24.0"
EXTRAPOLATION_VALIDATOR_VERSION = "materials-ner-validation/1.26.0"
CONTEXT_CONSISTENCY_VERSION = 'materials-context-consistency/1'
CONTEXT_VALIDATOR_VERSION = 'materials-ner-validation/1.27.0'
NAMED_VISUAL_VALIDATOR_VERSION = 'materials-ner-validation/1.28.0'


def check_consistency_version(version, graph_schema):
    if (version != CONTEXT_CONSISTENCY_VERSION
            or graph_schema not in {'materials-ner/13', 'materials-ner/14', 'materials-ner/15'}):
        raise ValueError('unsupported_context_consistency_version')

# A conservative triage heuristic, not an assertion that every matched number
# is a material result. Empty outputs with unit-bearing target text need review;
# they cannot silently count as successful coverage. Bibliographic years alone
# do not match. Some uncommon notation remains outside this heuristic.
QUANTITATIVE_HINT = re.compile(
    r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?\s*"
    r"(?:%|(?:mK|K|μT|mT|T|kOe|Oe|GPa|MPa|kbar|meV|eV|nm|Å|mΩ|Ω|mJ|J)\b|\\frac\{m?J\})")


def resolve_quote(text: str, quote: str) -> tuple[int, int]:
    """Resolve exact text, allowing whitespace layout differences only."""
    def collapsed(value):
        pieces, starts, ends = [], [], []
        for match in re.finditer(r"\S+", value):
            if pieces:
                pieces.append(" ")
                starts.append(match.start())
                ends.append(match.start())
            pieces.extend(match.group())
            starts.extend(range(match.start(), match.end()))
            ends.extend(range(match.start() + 1, match.end() + 1))
        return "".join(pieces), starts, ends
    haystack, starts, ends = collapsed(text)
    needle = " ".join(quote.split())
    start = haystack.find(needle)
    if not needle or start < 0:
        raise ValueError("quote_not_in_locked_source")
    if haystack.find(needle, start + 1) >= 0:
        raise ValueError("ambiguous_quote_locator")
    return starts[start], ends[start + len(needle) - 1]


def resolve_evidence(text, binding):
    """Verify positioned evidence exactly; never relocate a bad selector.

    Quote-only bindings retain historical unique, whitespace-aware resolution.
    An explicit selector permits repeated text but requires the original bytes
    as Unicode characters, rather than a normalized or reconstructed quote.
    """
    if hasattr(binding, 'start_char') or hasattr(binding, 'end_char'):
        start, end = getattr(binding, 'start_char', None), getattr(binding, 'end_char', None)
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
            raise ValueError('evidence_position_out_of_bounds')
        if text[start:end] != binding.quote:
            raise ValueError('evidence_position_quote_mismatch')
        return start, end
    return resolve_quote(text, binding.quote)


def pointer_exists(value: dict, pointer: str) -> bool:
    try:
        for part in pointer.lstrip("/").split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            value = value[int(part)] if isinstance(value, list) else value[part]
        return value is not None
    except (ValueError, KeyError, IndexError, TypeError):
        return False


def validate_extraction(extraction: Extraction, bundle: Bundle, *, visual_quantities=(), consistency_version=None) -> dict:
    if consistency_version is not None:
        check_consistency_version(consistency_version, extraction.schema_version)
    verify_bundle(bundle)
    descriptor_native = extraction.schema_version == 'materials-ner/15'
    extrapolation_native = extraction.schema_version in {'materials-ner/14', 'materials-ner/15'}
    adopted_kinds = set()
    normalizer, source_checker, registry_version = normalize, quantity_source_issues, REGISTRY_VERSION
    if extraction.schema_version in {'materials-ner/12', 'materials-ner/13', 'materials-ner/14', 'materials-ner/15'}:
        from . import quantities_v2
        normalizer, source_checker, registry_version = quantities_v2.normalize, quantities_v2.quantity_source_issues, quantities_v2.REGISTRY_VERSION
        adopted_kinds.update(quantities_v2.ADDITIONS)
    if extrapolation_native:
        from . import quantities_v3
        normalizer, source_checker, registry_version = quantities_v3.normalize, quantities_v3.quantity_source_issues, quantities_v3.REGISTRY_VERSION
        adopted_kinds.update(quantities_v3.ADDITIONS)
    if descriptor_native:
        from . import quantities_v4
        normalizer, source_checker, registry_version = quantities_v4.normalize, quantities_v4.quantity_source_issues, quantities_v4.REGISTRY_VERSION
    native_definitions = extraction.schema_version in {"materials-ner/5","materials-ner/6","materials-ner/7","materials-ner/8","materials-ner/9","materials-ner/10","materials-ner/11","materials-ner/12","materials-ner/13","materials-ner/14","materials-ner/15"}
    issues, resolved_evidence, normalized = [], [], {}
    blocks = {block.id: block for block in bundle.blocks}
    # Only the reviewed visual adapter supplies these already resolved bindings.
    # They remain separate from original-text Evidence and never alter Bundle.
    visual_by_path = {e['path']: e for e in visual_quantities}
    if len(visual_by_path) != len(visual_quantities) or any(
            e.get('kind') != 'visual_region' or not re.fullmatch(r'/results/\d+/quantity', path)
            for path, e in visual_by_path.items()):
        raise ValueError('visual_quantity_binding_shape')
    emitted_visuals = set()
    named_visual_policy = any(e.get('support_schema') == 'materials-visual-result-evidence/2'
                             for e in visual_quantities)
    processed, unread = extraction.processed_block_ids, extraction.unread_block_ids
    if (len(set(processed)) != len(processed) or len(set(unread)) != len(unread)
            or set(processed) & set(unread) or set(processed) | set(unread) != set(blocks)):
        issues.append({"code": "coverage_inventory_mismatch", "path": "/"})
    if extraction.work_id != bundle.work_id:
        issues.append({"code": "work_binding_mismatch", "path": "/work_id"})
    if unread or extraction.outcome == "incomplete":
        issues.append({"code": "incomplete_extraction", "path": "/"})
    source_hints = []
    if extraction.outcome == "empty":
        window = any(note.startswith("SOURCE_WINDOW ") for note in bundle.acquisition_notes)
        for block in bundle.blocks:
            if window and not block.locator.startswith("target:"):
                continue
            hints = list(QUANTITATIVE_HINT.finditer(lexical(block.text)))
            if hints:
                source_hints.append({"block_id": block.id, "unit_bearing_numeric_hints": len(hints)})
        if source_hints:
            issues.append({"code": "empty_quantitative_target_requires_review", "path": "/"})

    def issue(code, path):
        issues.append({"code": code, "path": path})

    def quantity_field(evidence, parent):
        from .field_quantity import enabled
        nested = parent + "/quantity"
        return nested if extraction.schema_version in {"materials-ner/11","materials-ner/12","materials-ner/13","materials-ner/14","materials-ner/15"} and enabled(evidence, nested) else parent

    def evidence_for(item, path, required):
        covered = set()
        body = item.model_dump()
        for binding in item.evidence:
            if not pointer_exists(body, binding.field):
                issue("evidence_field_not_present", path + binding.field)
                continue
            block = blocks.get(binding.block_id)
            if block is None or binding.block_id not in processed:
                issue("evidence_block_not_processed", path + binding.field)
                continue
            try:
                start, end = resolve_evidence(block.text, binding)
            except ValueError as error:
                issue(str(error), path + binding.field)
                continue
            covered.add(binding.field)
            resolved_evidence.append({
                "path": path + binding.field, "document_id": block.document_id,
                "block_id": block.id, "block_sha256": block.sha256,
                "start_char": start, "end_char": end, "locator": block.locator,
                "quote_sha256": sha(block.text[start:end].encode()),
            })
        for field in required:
            visual = visual_by_path.get(path + field)
            if visual is not None and pointer_exists(body, field):
                covered.add(field)
                if path + field not in emitted_visuals:
                    resolved_evidence.append(visual); emitted_visuals.add(path + field)
            if field not in covered:
                issue("field_evidence_missing", path + field)

    if native_definitions:
        used_states = {r.state_id for r in extraction.results} | {
            u.state_id for p in extraction.protocols for u in p.context_uses}
        used_samples = {s.sample_id for s in extraction.states if s.id in used_states}
        if extraction.schema_version in {"materials-ner/6", "materials-ner/7","materials-ner/8","materials-ner/9","materials-ner/10","materials-ner/11","materials-ner/12","materials-ner/13","materials-ner/14","materials-ner/15"}:
            from .validation_v6 import connected_samples
            used_samples = connected_samples(extraction, used_samples)
        for number, sample in enumerate(extraction.samples):
            if sample.id not in used_samples:
                issue("unassigned_sample_scope_requires_review", f"/samples/{number}")
        for number, state in enumerate(extraction.states):
            if state.id not in used_states:
                issue("unassigned_state_scope_requires_review", f"/states/{number}")

    for number, sample in enumerate(extraction.samples):
        from .formula_identity import has_identity_token
        if not has_identity_token(sample.formula_raw):
            issue("formula_no_identity_token", f"/samples/{number}/formula_raw")
        for index, assertion in enumerate(getattr(sample, "additional_formula_assertions", [])):
            if not has_identity_token(assertion.formula_raw):
                issue("formula_no_identity_token", f"/samples/{number}/additional_formula_assertions/{index}/formula_raw")
        required = ["/formula_raw"] if sample.formula_raw is not None else []
        if sample.composition_basis != "unresolved":
            required.append("/composition_basis")
        required.extend(f"/isotopes/{i}" for i in range(len(sample.isotopes)))
        required.extend(f"/variables/{i}" for i in range(len(sample.variables)))
        required.extend(f"/additional_formula_assertions/{i}" for i in range(len(getattr(sample,"additional_formula_assertions",[]))))
        if extraction.schema_version in {"materials-ner/2","materials-ner/3","materials-ner/4","materials-ner/5","materials-ner/6","materials-ner/7","materials-ner/8","materials-ner/9","materials-ner/10","materials-ner/11","materials-ner/12","materials-ner/13","materials-ner/14","materials-ner/15"} and sample.identity_resolution=="conflicted":
            required.append("/identity_resolution")
        if extraction.schema_version in {"materials-ner/6", "materials-ner/7","materials-ner/8","materials-ner/9","materials-ner/10","materials-ner/11","materials-ner/12","materials-ner/13","materials-ner/14","materials-ner/15"}:
            # An unresolved category records a limit of this extraction, not a
            # positive source assertion about the physical specimen. Requiring
            # a supporting quote would reward an invented classification.
            if sample.target_kind != "unresolved": required.append("/target_kind")
            required += ["/"+name for name in ("label","form_raw","substrate_raw") if getattr(sample,name)]
        if extraction.schema_version in {'materials-ner/13', 'materials-ner/14', 'materials-ner/15'}:
            required = policy_required('sample', sample)
        evidence_for(sample, f"/samples/{number}", required)
        # Composition numbers need the same literal fidelity as results. Do not
        # evaluate a symbolic oxygen deficiency, choose a range mean, or infer
        # an isotope abundance. Check source shape without assigning a chemical
        # basis or normalizing units whose composition meaning is unresolved.
        for collection, member in (("variables", "amount"), ("isotopes", "fraction")):
            for index, entry in enumerate(getattr(sample, collection)):
                field = f"/{collection}/{index}"
                quantity = getattr(entry, member)
                for code in unmapped_quantity_source_issues(quantity, sample.evidence, field):
                    issue(code, f"/samples/{number}" + field + f"/{member}")
    for number, state in enumerate(extraction.states):
        path = f"/states/{number}"
        evidence_for(state, path, policy_required('state', state) if extraction.schema_version in {'materials-ner/13', 'materials-ner/14', 'materials-ner/15'} else ["/sample_id"] + [
            f"/conditions/{i}" for i, condition in enumerate(state.conditions)
            if condition.quantity.status == "reported"])
        if extraction.schema_version in {'materials-ner/13', 'materials-ner/14', 'materials-ner/15'}:
            declaration = state.pressure
            required = policy_required('pressure', state)
            # Evidence is resolved once above; check the newly added declaration
            # against those exact source bindings without fabricating a number.
            covered = {e['path'] for e in resolved_evidence}
            for field in required:
                if path + field not in covered:
                    issue('field_evidence_missing', path + field)
            if declaration.basis_raw is not None and not any(
                    e.field == '/pressure/basis_raw' and declaration.basis_raw in e.quote
                    for e in state.evidence):
                issue('pressure_basis_not_literal_source', path + '/pressure/basis_raw')
        for i, condition in enumerate(state.conditions):
            if descriptor_native and condition.kind in {'twist_angle', 'reported_displacement_field'}:
                evidence_for(state, path, [f'/conditions/{i}/{k}' for k in ('kind','role','basis_raw')])
            if extrapolation_native and condition.role == 'extrapolation_target':
                evidence_for(state, path, [f'/conditions/{i}/role', f'/conditions/{i}/basis_raw'])
            if extraction.schema_version in {"materials-ner/3","materials-ner/4","materials-ner/5","materials-ner/6","materials-ner/7","materials-ner/8","materials-ner/9","materials-ner/10","materials-ner/11","materials-ner/12","materials-ner/13","materials-ner/14","materials-ner/15"}:
                position=condition.window_position
                if condition.role=="detection_window":
                    if position is None:issue("detection_window_position_missing",path+f"/conditions/{i}")
                    if condition.quantity.relation=="interval" and position!="interval":
                        issue("detection_window_shape_mismatch",path+f"/conditions/{i}")
                    if position=="interval" and condition.quantity.relation!="interval":
                        issue("detection_window_shape_mismatch",path+f"/conditions/{i}")
                    if ((position=="lower_limit" and condition.quantity.relation in {"lt","le"}) or
                        (position=="upper_limit" and condition.quantity.relation in {"gt","ge"})):
                        issue("detection_window_bound_direction_conflict",path+f"/conditions/{i}")
                elif position is not None:
                    issue("window_position_outside_detection_context",path+f"/conditions/{i}")
            try:
                normalized[path + f"/conditions/{i}/quantity"] = normalizer(condition.kind, condition.quantity)
                for code in source_checker(condition.kind, condition.quantity, state.evidence, quantity_field(state.evidence, f"/conditions/{i}")):
                    issue(code, path + f"/conditions/{i}/quantity")
            except ValueError as error:
                issue(str(error), path + f"/conditions/{i}/quantity")
    for number, protocol in enumerate(extraction.protocols):
        path=f"/protocols/{number}"
        if protocol.method is not None and not any(character.isalpha() for character in protocol.method):
            issue("method_no_identity_token",path+"/method")
        required = (["/method"] if protocol.method else []) + (
            ["/criterion"] if not native_definitions and protocol.criterion not in {"unspecified", "not_applicable"} else [])
        if getattr(protocol,"method_class","unspecified")!="unspecified":required.append("/method_class")
        parameters=getattr(protocol,"parameters",[])
        if not native_definitions and protocol.criterion=="resistance_fraction" and not any(p.kind=="resistance_fraction" for p in parameters):
            issue("resistance_fraction_criterion_parameter_missing",path+"/criterion")
        required.extend(f"/parameters/{i}" for i in range(len(parameters)))
        if native_definitions:
            required.extend(f"/context_uses/{i}" for i in range(len(protocol.context_uses)))
            if not protocol.context_uses and not any(r.protocol_id == protocol.id for r in extraction.results):
                issue("unassigned_procedure_scope_requires_review", path + "/context_uses")
        if extraction.schema_version in {'materials-ner/13', 'materials-ner/14', 'materials-ner/15'}:
            required = policy_required('protocol', protocol)
        evidence_for(protocol,path,required)
        for i,parameter in enumerate(parameters):
            try:
                normalized[path+f"/parameters/{i}/quantity"]=normalizer(parameter.kind,parameter.quantity)
                for code in source_checker(parameter.kind,parameter.quantity,protocol.evidence, quantity_field(protocol.evidence, f"/parameters/{i}")):
                    issue(code,path+f"/parameters/{i}/quantity")
            except ValueError as error:
                issue(str(error),path+f"/parameters/{i}/quantity")
    states = {item.id: item for item in extraction.states}
    protocols = {item.id: item for item in extraction.protocols}
    for number, result in enumerate(extraction.results):
        path = f"/results/{number}"
        if adopted_kinds:
            if result.quantity_kind in adopted_kinds:
                evidence_for(result, path, policy_required('adopted', result))
                if not any(e.field == '/quantity_name_raw' and ' '.join(result.quantity_name_raw.split()) in ' '.join(e.quote.split()) for e in result.evidence):
                    issue('adopted_quantity_source_name_not_literal', path + '/quantity_name_raw')
        if extrapolation_native and any(c.role == 'extrapolation_target' for c in states[result.state_id].conditions):
            if result.origin == 'observed':
                issue('extrapolation_target_observed_result_conflict', path + '/origin')
            elif result.origin == 'unknown':
                issue('extrapolation_target_origin_requires_review', path + '/origin')
        if native_definitions:
            definition = result.definition
            required = (["/definition/criterion"] if definition.criterion not in {"unspecified", "not_applicable"} else [])
            if definition.criterion_raw is not None:
                required.append("/definition/criterion_raw")
            required.extend(f"/definition/parameters/{i}" for i in range(len(definition.parameters)))
            if extraction.schema_version in {'materials-ner/13', 'materials-ner/14', 'materials-ner/15'}:
                required = policy_required('definition', result)
            evidence_for(result, path, required)
            if definition.criterion == "resistance_fraction" and not any(
                    p.kind == "resistance_fraction" for p in definition.parameters):
                issue("resistance_fraction_criterion_parameter_missing", path + "/definition/criterion")
            if definition.criterion_raw and not any(e.field == "/definition/criterion_raw"
                    and " ".join(definition.criterion_raw.split()) in " ".join(e.quote.split()) for e in result.evidence):
                issue("criterion_raw_not_in_field_evidence", path + "/definition/criterion_raw")
            for i, parameter in enumerate(definition.parameters):
                field = f"/definition/parameters/{i}"
                try:
                    normalized[path + field + "/quantity"] = normalizer(parameter.kind, parameter.quantity)
                    for code in source_checker(parameter.kind, parameter.quantity, result.evidence, quantity_field(result.evidence, field)):
                        issue(code, path + field + "/quantity")
                except ValueError as error:
                    issue(str(error), path + field + "/quantity")
        qualifiers=getattr(result,"qualifiers",[])
        kinds=[q.kind for q in qualifiers]
        if len(kinds)!=len(set(kinds)):issue("duplicate_result_qualifier",path+"/qualifiers")
        if qualifiers:
            required=[f"/qualifiers/{i}" for i in range(len(qualifiers))]
            required.extend(f"/qualifiers/{i}/tc_bound" for i,q in enumerate(qualifiers)
                if q.kind=="conditional_existence" and getattr(q,"tc_bound",None) is not None
                and q.tc_bound.status=="reported")
            if extraction.schema_version in {'materials-ner/13', 'materials-ner/14', 'materials-ner/15'}:
                required = policy_required('qualifiers', result)
            evidence_for(result,path,required)
        for i,qualifier in enumerate(qualifiers):
            if not any(e.field==f"/qualifiers/{i}" and " ".join(qualifier.raw.split()) in " ".join(e.quote.split()) for e in result.evidence):
                issue("qualifier_raw_not_in_field_evidence",path+f"/qualifiers/{i}")
        if extraction.schema_version in {"materials-ner/2","materials-ner/3","materials-ner/4","materials-ner/5","materials-ner/6","materials-ner/7","materials-ner/8","materials-ner/9","materials-ner/10","materials-ner/11","materials-ner/12","materials-ner/13","materials-ner/14","materials-ner/15"}:
            if result.quantity_kind=="non_detection" and "non_detection" not in kinds:
                issue("non_detection_target_missing",path)
            if result.quantity_kind!="non_detection" and "non_detection" in kinds:
                issue("non_detection_qualifier_kind_mismatch",path)
            if "conditional_existence" in kinds and result.quantity_kind=="tc":
                issue("conditional_tc_requires_non_detection_review",path)
            for q in qualifiers:
                if q.kind=="temperature_role" and q.role=="component_model_parameter" and result.quantity_kind=="tc":
                    issue("component_temperature_not_system_tc",path)
        for i,q in enumerate(qualifiers):
            bound=getattr(q,"tc_bound",None)
            if bound is None:continue
            bound_path=f"/qualifiers/{i}/tc_bound"
            if bound.status=="reported" and bound.relation not in {"lt","le","interval"}:
                issue("conditional_tc_requires_bound_not_point",path+bound_path)
            try:
                normalized[path+bound_path]=normalizer("tc",bound)
                for code in source_checker("tc",bound,result.evidence,bound_path):
                    issue(code,path+bound_path)
            except ValueError as error:
                issue(str(error),path+bound_path)
        if any(note.startswith("SOURCE_WINDOW ") for note in bundle.acquisition_notes):
            target_field = "/quantity_kind" if result.quantity_kind == "non_detection" else "/quantity"
            if result.quantity.status == "reported" or result.quantity_kind == "non_detection":
                if not any(e.field == target_field and e.block_id in blocks
                           and blocks[e.block_id].locator.startswith("target:") for e in result.evidence):
                    issue("observation_only_in_window_context", path)
        evidence_for(result, path, policy_required('result', result) if extraction.schema_version in {'materials-ner/13', 'materials-ner/14', 'materials-ner/15'} else ["/quantity_kind", "/sample_id", "/state_id", "/protocol_id",
                                   "/origin", "/source_role"] + (
                                       ["/quantity"] if result.quantity.status == "reported" else []))
        if result.source_role == "cited" and not result.cited_source_raw:
            # An unresolved bibliographic link invalidates this observation,
            # not every independent observation in the same source window.
            issue("cited_source_unresolved", path + "/cited_source_raw")
        elif result.cited_source_raw:
            evidence_for(result, path, policy_required('citation', result))
            marker = " ".join(result.cited_source_raw.split())
            if not any(e.field == "/cited_source_raw" and marker in " ".join(e.quote.split())
                       for e in result.evidence):
                issue("citation_marker_not_in_field_evidence", path + "/cited_source_raw")
        if result.quantity_kind == "tc" and result.quantity.status == "reported" and result.quantity.value == 0:
            issue("zero_tc_requires_non_detection_review", path)
        if result.quantity_kind in COMPONENT_KINDS:
            if not result.component_raw:
                issue("quantity_component_definition_missing", path + "/component_raw")
            else:
                evidence_for(result, path, policy_required('component', result))
        if result.quantity_kind == "unmapped":
            evidence_for(result, path, policy_required('unmapped', result))
            issue("unregistered_quantity_requires_domain_review", path)
            quantity_evidence = list(result.evidence)
            visual = visual_by_path.get(path + '/quantity')
            if visual is not None and visual.get('support_schema') == 'materials-visual-result-evidence/2':
                from types import SimpleNamespace
                quantity_evidence.append(SimpleNamespace(field='/quantity', quote=visual['transcription']))
            for code in unmapped_quantity_source_issues(result.quantity, quantity_evidence, "/quantity"):
                issue(code, path + "/quantity")
        elif result.quantity_kind == "non_detection":
            if result.quantity.status == "reported":
                issue("non_detection_is_not_point_tc", path)
            has_window=any(c.kind == "temperature" and c.role == "detection_window"
                       and c.quantity.status == "reported" for c in states[result.state_id].conditions)
            if extraction.schema_version in {"materials-ner/8","materials-ner/9","materials-ner/10","materials-ner/11","materials-ner/12","materials-ner/13","materials-ner/14","materials-ner/15"}:
                from .validation_v8 import validate_non_detection
                validate_non_detection(result, states[result.state_id], protocols[result.protocol_id], path, evidence_for, issue, normalized)
            elif extraction.schema_version in {"materials-ner/4","materials-ner/5","materials-ner/6","materials-ner/7"}:
                negative=next((q for q in qualifiers if q.kind=="non_detection"),None)
                if negative and negative.window_status=="reported" and not has_window:
                    issue("reported_detection_window_missing",path)
                if negative and negative.window_status!="reported" and has_window:
                    issue("unreported_window_contains_reported_extent",path)
                # A conditional Tc threshold can be copied into a measurement
                # floor while satisfying numeric/schema checks. When the same
                # conditional passage is the only supplied floor evidence,
                # require source adjudication. This conservative signal does
                # not assert that a genuine experiment could not share that
                # endpoint, and never removes or replaces either assertion.
                conditional=next((q for q in qualifiers if q.kind=="conditional_existence"
                                  and getattr(q,"tc_bound",None) is not None),None)
                if negative and negative.window_status=="reported" and conditional:
                    bound=conditional.tc_bound
                    state=states[result.state_id]
                    if bound.status=="reported" and bound.relation in {"lt","le"}:
                        for index,condition in enumerate(state.conditions):
                            q=condition.quantity
                            if (condition.kind!="temperature" or condition.role!="detection_window"
                                    or getattr(condition,"window_position",None)!="lower_limit"
                                    or q.status!="reported" or q.relation!="exact"):
                                continue
                            try:
                                endpoint=normalizer("temperature",q)["normalized"]["value"]
                                threshold=normalizer("tc",bound)["normalized"]["upper"]
                            except (ValueError,KeyError):
                                continue  # Existing numeric checks retain their own failure.
                            if abs(endpoint-threshold)>1e-12*max(1,abs(threshold)):
                                continue
                            wording=" ".join(conditional.raw.split())
                            expression=" ".join(bound.raw.split())
                            floor_quotes=[" ".join(e.quote.split()) for e in state.evidence
                                if e.field==f"/conditions/{index}"]
                            if floor_quotes and all(wording in quote and expression in quote
                                                    for quote in floor_quotes):
                                issue("conditional_bound_window_requires_source_review",path)
            elif not has_window:issue("non_detection_window_missing", path)
        else:
            try:
                normalized[path + "/quantity"] = normalizer(result.quantity_kind, result.quantity)
                quantity_evidence = list(result.evidence)
                if path + '/quantity' in visual_by_path:
                    from types import SimpleNamespace
                    quantity_evidence.append(SimpleNamespace(field='/quantity',
                        quote=visual_by_path[path + '/quantity']['transcription']))
                for code in source_checker(result.quantity_kind, result.quantity, quantity_evidence, "/quantity"):
                    issue(code, path + "/quantity")
            except ValueError as error:
                issue(str(error), path + "/quantity")
        if result.quantity_kind == "tc" and (
                (result.definition.criterion if native_definitions else protocols[result.protocol_id].criterion) == "fit_parameter"
                or result.component_raw and re.search(r"\b(band|pi|sigma)\b|[πσ]", result.component_raw, re.I)):
            # The v2 source-bound role can distinguish fitting a system Tc
            # from a component model parameter. It does not grant scientific acceptance.
            system_role=any(q.kind=="temperature_role" and q.role=="system_transition" for q in qualifiers)
            if not (system_role and result.origin in {"computed","model_derived"}):
                issue("band_or_fit_temperature_requires_model_scale_review", path)
    if extraction.schema_version in {"materials-ner/6", "materials-ner/7","materials-ner/8","materials-ner/9","materials-ner/10","materials-ner/11","materials-ner/12","materials-ner/13","materials-ner/14","materials-ner/15"}:
        from .validation_v6 import validate_relations, validate_raw_literals
        validate_relations(extraction,evidence_for,issue)
        validate_raw_literals(extraction,issue)
    if consistency_version is not None:
        from .validation_v6 import validate_pressure_consistency
        validate_pressure_consistency(extraction, issue)
    # Historical reports remain byte-replayable. New validation explicitly
    # selects a version without adding scientific fields or changing prompts.
    base_version = ('materials-ner-validation/1.29.0' if descriptor_native else EXTRAPOLATION_VALIDATOR_VERSION if extrapolation_native else 'materials-ner-validation/1.25.0' if visual_quantities else PRESSURE_VALIDATOR_VERSION if extraction.schema_version in {"materials-ner/13", "materials-ner/14","materials-ner/15"} else ADOPTED_VALIDATOR_VERSION if extraction.schema_version == "materials-ner/12" else POSITIONED_VALIDATOR_VERSION if extraction.schema_version in {"materials-ner/11","materials-ner/12","materials-ner/13","materials-ner/14","materials-ner/15"} else VALIDATOR_VERSION)
    # Technical checks do not establish the source's scientific meaning.
    return {"validator_version": base_version if descriptor_native else NAMED_VISUAL_VALIDATOR_VERSION if named_visual_policy else CONTEXT_VALIDATOR_VERSION if consistency_version is not None else base_version,
            **({'visual_evidence_policy': 'materials-visual-result-evidence/2'} if named_visual_policy else {}),
            **({'context_consistency_version': consistency_version, 'base_validator_version': base_version}
               if consistency_version is not None else {}), "registry_version": registry_version,
            "valid": not issues, "issues": issues, "normalized": normalized,
            "empty_output_source_hints": source_hints,
            "resolved_evidence": resolved_evidence, "review_status": "pending",
            "scientific_acceptance": False, "ml_training_eligible": False,
            "extraction_sha256": digest(extraction.model_dump()),
            "bundle_sha256": digest(bundle.model_dump())}


def training_exclusions(extraction: Extraction, bundle: Bundle, validation: dict) -> dict:
    """Legacy T1 holds plus four task-specific proposal audits; no authorization."""
    global_reasons = ["human_scientific_review_pending", "independent_gold_evaluation_pending"]
    if not validation["valid"]:
        global_reasons.append("technical_validation_failed")
    if bundle.source_status != "current":
        global_reasons.append("source_currentness_unverified")
    if any(d.version_status != "verified" for d in bundle.documents):
        global_reasons.append("publication_version_unverified")
    if any(d.coverage != "complete_document" for d in bundle.documents):
        global_reasons.append("incomplete_source_coverage")
    if bundle.supplement_status not in {"included", "not_applicable"}:
        global_reasons.append("supplement_coverage_unresolved")
    samples = {item.id: item for item in extraction.samples}
    states = {item.id: item for item in extraction.states}
    protocols = {item.id: item for item in extraction.protocols}
    rows = []
    for result in extraction.results:
        reasons = list(global_reasons)
        if result.quantity_kind != "tc" or result.origin != "observed" or result.source_role != "primary":
            reasons.append("not_primary_observed_tc")
        if result.quantity.relation != "exact" or result.quantity.status != "reported":
            reasons.append("not_point_label")
        if result.quantity.approximate:
            reasons.append("approximation_requires_task_policy")
        if samples[result.sample_id].identity_resolution != "source_scoped":
            reasons.append("sample_identity_unresolved")
        if sample_formula := getattr(samples[result.sample_id], "formula_unavailability", None):
            reasons.append("formula_unavailable_" + sample_formula.status)
        # Exact formula AST/feature policy is a separate gate; never guess one here.
        reasons.append("composition_features_not_adjudicated")
        criterion = (result.definition.criterion if extraction.schema_version in {"materials-ner/5","materials-ner/6","materials-ner/7","materials-ner/8","materials-ner/9","materials-ner/10","materials-ner/11","materials-ner/12","materials-ner/13","materials-ner/14","materials-ner/15"}
                     else protocols[result.protocol_id].criterion)
        if extraction.schema_version in {"materials-ner/6", "materials-ner/7","materials-ner/8","materials-ner/9","materials-ner/10","materials-ner/11","materials-ner/12","materials-ner/13","materials-ner/14","materials-ner/15"}:
            if any(result.sample_id in {edge.from_sample_id,edge.to_sample_id} for edge in extraction.sample_relations):
                reasons.append("component_membership_and_composition_scope_review_required")
            if any(edge.state_id==result.state_id for edge in extraction.condition_supports):
                reasons.append("condition_support_feature_provenance_review_required")
        if criterion not in {
                "zero_resistance", "onset", "midpoint", "offset", "diamagnetic_onset", "heat_capacity_anomaly"}:
            reasons.append("transition_criterion_unresolved_or_incompatible")
        qualitative_ambient = (extraction.schema_version in {'materials-ner/13', 'materials-ner/14', 'materials-ner/15'}
            and states[result.state_id].pressure.availability == 'reported'
            and states[result.state_id].pressure.regime == 'explicit_ambient')
        if not qualitative_ambient and not any(c.kind == "pressure" and c.role == "measurement" and c.quantity.status == "reported"
                   for c in states[result.state_id].conditions):
            reasons.append("measurement_pressure_unknown")
        if result.dependencies:
            reasons.append("dependency_and_feature_leakage_review_required")
        if any(q.kind=="conditional_existence" for q in getattr(result,"qualifiers",[])):
            reasons.append("conditional_superconducting_existence")
        if any(q.kind=="non_detection" and getattr(q,"window_status","reported")!="reported"
               for q in getattr(result,"qualifiers",[])):
            reasons.append("non_detection_measurement_window_unavailable")
        if extraction.schema_version in {"materials-ner/8","materials-ner/9","materials-ner/10","materials-ner/11","materials-ner/12","materials-ner/13","materials-ner/14","materials-ner/15"} and result.quantity_kind == "non_detection":
            reasons.append("non_detection_is_not_point_tc")
            if any(q.kind=="non_detection" and q.target!="superconductivity" for q in result.qualifiers):
                reasons.append("device_non_detection_is_not_superconductivity_negative_label")
        rows.append({"result_id": result.id, "eligible": False, "reason_codes": sorted(set(reasons))})
    from .task_features import assess_tasks
    return {"task": "T1-observed-tc-proposal/1", "results": rows, "scientific_acceptance": False,
            "task_feature_assessment": assess_tasks(extraction,bundle,validation)}
