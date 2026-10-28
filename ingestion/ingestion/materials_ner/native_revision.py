"""One source-backed model revision, retaining a failed native draft verbatim.

A revision is a new proposal attempt, never an overwrite, evidence-only patch,
human second read or scientific approval. Entity changes require source-bound
notes. Deleting previous declarations is forbidden in this bounded workflow.
"""
from collections import Counter
import json
import time
from typing import Literal

from pydantic import Field, ValidationError
import tiktoken

from .contract import StrictModel, canonical, digest
from .evidence import selected_quotes, source_catalog
from .inventory import Inventory
from .inventory_links import verify_inventory_projection
from .providers import CodexProvider, ProviderFailure
from .sources import check_admission, private_write, sha
from .validation import validate_extraction, training_exclusions
from .wire_v7 import (NativeExtraction, output_schema as native_schema, validate_coverage,
                     render as native_render, PROMPT_HASH as NATIVE_PROMPT_HASH)

VERSION = "materials-native-revision/1"
PROMPT_VERSION = "materials-native-revision-prompt/1.0.0"
GROUPS = {"sample": ("samples", "id"), "state": ("states", "id"),
          "procedure": ("protocols", "id"), "result": ("observations", "id"),
          "context": ("context_dispositions", "context_id"),
          "additional_item": ("additional_items", "id"), "unextracted_item": ("unextracted_items", "item_id")}
DECLARATIONS = {"sample", "state", "procedure", "result", "additional_item", "context"}


class RevisionNote(StrictModel):
    entity: Literal["sample", "state", "procedure", "result", "context", "additional_item", "unextracted_item", "document"]
    entity_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    span_ids: list[str] = Field(min_length=1)


class NativeRevision(StrictModel):
    schema_version: Literal["materials-native-revision/1"]
    work_id: str
    base_raw_output_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    revised_graph: NativeExtraction
    notes: list[RevisionNote]


INSTRUCTIONS = """Perform one source-backed revision of the supplied failed extraction.
The prior graph and first-read inventory are fallible model drafts, not truth.
Read the original source again. Retain all old sample, state, procedure, result,
context and additional-item IDs; do not hide a failure by deleting or renaming
an entity. Correct their fields only when the source supports the correction.
Add omitted source-supported results with new IDs and full owner/evidence links.
Do not add nonexistent results merely to satisfy a dangling reference. Determine
whether the source actually reports that result and distinguish a fitted result
from physical sample geometry. Reconcile every inventory item's disposition.
The supplied registry includes fitted superconducting-layer thickness.

Recheck literal formulas, including inconsistent spellings. Preserve distinct
source assertions rather than repeating the normalized formula in every slot.
Check sample attribution, state thickness, transition stage, criterion, fitting
origin and each threshold's own evidence. Source raw fields must be literal;
put explanations in reason/details fields, not in a rewritten quotation.

Return one complete revised_graph and exactly one source-backed note for every
changed or added entity (including evidence-only changes). A note identifies its
entity kind and existing/new ID, explains the change in English and cites source
span IDs. Removal of an unextracted_item after emitting its result needs a note.
For changed completion, limitations or processed/unread blocks, use entity=document
and entity_id=the work ID. Unchanged entities need no note. No scientific/human
approval or training eligibility can be assigned. If an assertion remains
unresolved, preserve that uncertainty rather than inventing a fact.
"""
PROMPT_HASH = digest({"version": PROMPT_VERSION, "instructions": INSTRUCTIONS,
                      "native_prompt_hash": NATIVE_PROMPT_HASH})


def output_schema(bundle=None, inventory=None):
    schema = NativeRevision.model_json_schema()
    native = native_schema(bundle, inventory)
    schema["$defs"].update(native["$defs"])
    schema["$defs"]["NativeExtraction"] = {k: v for k, v in native.items() if k != "$defs"}
    if bundle is not None:
        schema["properties"]["work_id"]["enum"] = [bundle.work_id]
        schema["$defs"]["RevisionNote"]["properties"]["span_ids"]["items"]["enum"] = list(source_catalog(bundle)["spans"])
    return schema


def grouped(raw):
    out = {}
    for kind, (name, key) in GROUPS.items():
        rows = raw.get(name)
        if not isinstance(rows, list): raise ValueError("revision_parent_shape_invalid")
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError("revision_parent_identifier_invalid")
            identity = (kind, row[key])
            if identity in out: raise ValueError("revision_parent_duplicate_identifier")
            out[identity] = row
    out["document", raw["work_id"]] = {k: v for k, v in raw.items() if k not in {v[0] for v in GROUPS.values()}}
    return out


def graph_diagnostics(raw):
    """Locate dangling references even when the strict graph cannot be parsed."""
    entities = grouped(raw)
    issues = []
    kind_map = {"protocol": "procedure", "definition": "result"}
    for context in raw["context_dispositions"]:
        for index, binding in enumerate(context.get("bindings", [])):
            target = (kind_map.get(binding["entity"], binding["entity"]), binding["entity_id"])
            if target not in entities:
                issues.append({"code": "context_target_missing", "context_id": context["context_id"],
                    "binding_index": index, "target_entity": target[0], "target_id": target[1]})
    for sample in raw["samples"]:
        formulas = [sample["formula_raw"]] + [a["formula_raw"] for a in sample.get("additional_formula_assertions", [])]
        if len(formulas) > len(set(formulas)):
            issues.append({"code": "repeated_literal_formula_assertion_requires_source_review", "sample_id": sample["id"]})
    return issues


def audit_revision(base_raw, revision, bundle):
    if sha(base_raw.encode()) != revision.base_raw_output_sha256 or revision.work_id != bundle.work_id:
        raise ValueError("revision_parent_or_work_mismatch")
    before_raw = json.loads(base_raw); after_raw = revision.revised_graph.model_dump()
    if before_raw["work_id"] != bundle.work_id or after_raw["work_id"] != bundle.work_id:
        raise ValueError("revision_graph_work_mismatch")
    before, after = grouped(before_raw), grouped(after_raw)
    changes, issues = [], []
    notes = {(n.entity, n.entity_id): n for n in revision.notes}
    if len(notes) != len(revision.notes): issues.append({"code": "revision_duplicate_note", "path": "/"})
    changed = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
    if set(notes) != changed: issues.append({"code": "revision_note_coverage_mismatch", "path": "/"})
    catalog = source_catalog(bundle)
    for key in sorted(changed):
        old, new = before.get(key), after.get(key)
        if new is None and key[0] in DECLARATIONS:
            issues.append({"code": "revision_declaration_removed", "path": "/"})
        note = notes.get(key); quotes = []
        if note:
            try: quotes = selected_quotes(catalog, note.span_ids)
            except ValueError: issues.append({"code": "revision_note_source_invalid", "path": "/"})
        changes.append({"entity": key[0], "entity_id": key[1],
            "operation": "added" if old is None else "removed" if new is None else "revised",
            "before": old, "after": new, "before_sha256": digest(old), "after_sha256": digest(new),
            "reason": note.reason if note else None, "source_quotes": quotes})
    return {"schema": "materials-native-revision-audit/1", "base_raw_output_sha256": revision.base_raw_output_sha256,
        "revised_graph_sha256": digest(after_raw), "changes": changes, "issues": issues,
        "valid": not issues, "reviewer_kind": "model", "independent_review": False,
        "scientific_acceptance": False, "ml_training_eligible": False}


def verify_parent(parent, bundle):
    receipt, raw = parent["receipt"], parent["raw_output"]
    if digest(receipt) != parent["run_id"] or receipt.get("raw_output_sha256") != sha(raw.encode()):
        raise ValueError("revision_parent_receipt_hash_mismatch")
    if (receipt["work_id"] != bundle.work_id or receipt["bundle_sha256"] != digest(bundle.model_dump())
            or receipt["config"].get("output_format") != "materials-ner-shared/3"
            or receipt["state"] in {"queued", "running"}):
        raise ValueError("revision_requires_terminal_native_parent")
    verify_inventory_projection(receipt, bundle)
    inventory = Inventory.model_validate(receipt["inventory"])
    grouped(json.loads(raw))  # A broken relation is allowed; ambiguous declarations are not.
    return inventory


def configuration(parent, *, mode="full", review_request=None, **kwargs):
    if mode == "staged_fields":
        from .staged_revision import configuration as staged_configuration
        return staged_configuration(parent, review_request=review_request, **kwargs)
    if mode in {"scoped_review", "scoped_fields", "condition_review", "coverage_review", "focused_fields"}:
        from . import scoped_review, source_field_scoped, condition_review, coverage_revision, source_field_focus
        contract = {"scoped_review": scoped_review, "scoped_fields": source_field_scoped, "condition_review": condition_review, "coverage_review": coverage_revision, "focused_fields": source_field_focus}[mode]
        return contract.configuration(parent, review_request=review_request, **kwargs)
    if mode == "source_fields_local":
        from .source_field_local import configuration as local_config
        return local_config(parent, review_request=review_request, **kwargs)
    if mode == "source_fields":
        from .source_field_revision import configuration as field_config
        return field_config(parent, review_request=review_request, **kwargs)
    if mode == "relational_review":
        from .relational_review import configuration as review_config
        return review_config(parent, review_request=review_request, **kwargs)
    from .relational_review import pending_review_issues
    if pending_review_issues(parent):
        raise ValueError("unresolved_review_requires_accounted_revision")
    if review_request is not None:
        raise ValueError("review_request_requires_relational_review_mode")
    if mode == "relational_edits":
        from .relational_revision import configuration as relational_config
        return relational_config(parent, **kwargs)
    from .worker import configuration as worker_config
    config = worker_config(workflow="inventory_v7", **kwargs)
    if config["provider"] != "codex": raise ValueError("revision_provider_not_evaluated")
    config.update(workflow="native_revision_v1", output_format=VERSION,
        inventory_link_projection_version=None, max_inventory_repairs=0, max_extraction_repairs=0,
        max_evidence_patches=0, max_source_revisions=1, parent_run_id=parent["run_id"],
        schema_sha256=digest(output_schema()), prompt_version=PROMPT_VERSION, prompt_sha256=PROMPT_HASH)
    if mode == "edits":
        from . import native_revision_edits as edits
        config.update(workflow="native_revision_edits_v1", output_format=edits.VERSION,
            schema_sha256=digest(edits.output_schema()), prompt_version=edits.PROMPT_VERSION, prompt_sha256=edits.PROMPT_HASH)
    elif mode != "full": raise ValueError("unknown_revision_mode")
    return config


def render(bundle, inventory, parent):
    return "\n".join([native_render(bundle, inventory), INSTRUCTIONS,
        "BASE_RAW_OUTPUT_SHA256: " + sha(parent["raw_output"].encode()),
        "BASE_GRAPH: " + parent["raw_output"],
        "DETERMINISTIC_GRAPH_DIAGNOSTICS: " + canonical(graph_diagnostics(json.loads(parent["raw_output"]))),
        "Return the revision wrapper, preserving prior IDs and all source-supported assertions."])


def verify_receipt(receipt, bundle, raw_output):
    parent = receipt["revision_parent"]
    inventory = verify_parent(parent, bundle)
    if (receipt["config"]["parent_run_id"] != parent["run_id"]
            or receipt.get("inventory") != inventory.model_dump()):
        raise ValueError("revision_parent_inventory_mismatch")
    if "extraction" not in receipt: return
    revision = NativeRevision.model_validate_json(raw_output)
    proof = audit_revision(parent["raw_output"], revision, bundle)
    if proof != receipt.get("revision_audit"):
        raise ValueError("revision_audit_reconstruction_mismatch")
    if revision.revised_graph.expand(bundle).model_dump() != receipt["extraction"]:
        raise ValueError("revision_extraction_reconstruction_mismatch")
    required = {(i["code"], i["path"]) for i in proof["issues"]}
    actual = {(i["code"], i["path"]) for i in receipt["validation"]["issues"]}
    if not required <= actual: raise ValueError("revision_audit_issues_omitted")


def run_one(store, job_id, parent, bundle, *, provider_override=None, mode="full"):
    """One fresh queue attempt and at most one model call; no silent retry."""
    from .worker import implementation_sources
    relational = mode in {"relational_edits", "relational_review", "source_fields", "source_fields_local", "scoped_review", "scoped_fields", "condition_review", "coverage_review", "focused_fields", "staged_fields"}
    if relational:
        if mode == "staged_fields":
            from . import staged_revision as edit_contract
        elif mode == "focused_fields":
            from . import source_field_focus as edit_contract
        elif mode == "coverage_review":
            from . import coverage_revision as edit_contract
        elif mode == "condition_review":
            from . import condition_review as edit_contract
        elif mode == "scoped_review":
            from . import scoped_review as edit_contract
        elif mode == "scoped_fields":
            from . import source_field_scoped as edit_contract
        elif mode == "source_fields_local":
            from . import source_field_local as edit_contract
        elif mode == "source_fields":
            from . import source_field_revision as edit_contract
        elif mode == "relational_review":
            from . import relational_review as edit_contract
        else:
            from . import relational_revision as edit_contract
        inventory = edit_contract.verify_parent(parent, bundle)
    else:
        inventory = verify_parent(parent, bundle)
    job = store.claim(lease_seconds=3900, job_id=job_id)
    if job is None: return None
    directory = store.root / "attempts" / job["id"] / job["lease_token"]
    started = time.monotonic(); usage = Counter(); state = "failed"; error_code = None
    config = job["config"]
    receipt = {"schema": "materials-ner-attempt/1", "job_id": job["id"], "attempt_id": job["lease_token"],
        "work_id": bundle.work_id, "bundle_sha256": job["bundle_hash"], "config": config,
        "revision_parent": parent, "inventory": inventory.model_dump(),
        "scientific_acceptance": False, "production_writes": False,
        "output_token_limit_enforced_by_provider": False}
    review_options = {}
    if mode in {"relational_review", "source_fields", "source_fields_local", "scoped_review", "scoped_fields", "condition_review", "coverage_review", "focused_fields", "staged_fields"}:
        review_options = {"review_request": config.get("review_request")}
        receipt["review_request"] = config.get("review_request")
    try:
        expected = configuration(parent, mode=mode, **review_options, **{k: config[k] for k in
            ("provider", "model", "reasoning", "timeout_seconds", "max_input_tokens", "max_output_tokens")})
        if config != expected or job["bundle_hash"] != digest(bundle.model_dump()) or job["work_id"] != bundle.work_id:
            raise ProviderFailure("revision_worker_contract_drift")
        if check_admission(bundle): raise ProviderFailure("revision_source_not_admitted")
        sources = implementation_sources()
        if digest({name: sha(raw) for name, raw in sources.items()}) != config["implementation_sha256"]:
            raise ProviderFailure("worker_source_changed_during_capture")
        code_root = store.root / "implementations" / config["implementation_sha256"]
        for name, raw in sources.items():
            target = code_root / name
            if target.exists() and target.read_bytes() != raw: raise ProviderFailure("implementation_snapshot_corrupt")
            if not target.exists(): private_write(target, raw)
        private_write(code_root/"manifest.json", canonical({"files": {n: sha(r) for n,r in sources.items()}, "runtime": config["runtime"]}).encode())
        if mode in {"edits", "relational_edits", "relational_review", "source_fields", "source_fields_local", "scoped_review", "scoped_fields", "condition_review", "coverage_review", "focused_fields", "staged_fields"}:
            if not relational:
                from . import native_revision_edits as edit_contract
            schema = edit_contract.output_schema(bundle, inventory, parent, **review_options)
            prompt = edit_contract.render(bundle, inventory, parent, **review_options)
        else:
            schema = output_schema(bundle, inventory); prompt = render(bundle, inventory, parent)
        tokens = len(tiktoken.get_encoding("cl100k_base").encode(prompt + canonical(schema), disallowed_special=()))
        stage = {"name": "source_revision", "prompt_sha256": sha(prompt.encode()), "schema_sha256": digest(schema),
                 "input_count": {"tokens": tokens, "tokenizer": "cl100k_base", "provider_exact": False}}
        receipt["stages"] = [stage]
        for name, raw in (("input.txt",prompt.encode()), ("schema.json",canonical(schema).encode()),
                          ("parent-output.json",parent["raw_output"].encode()),
                          ("source-catalog.json",canonical(source_catalog(bundle)).encode())):
            private_write(directory/name, raw)
        if mode in {"relational_review", "source_fields", "source_fields_local", "scoped_review", "scoped_fields", "condition_review", "coverage_review", "focused_fields", "staged_fields"}:
            private_write(directory/"review-request.json", canonical(receipt["review_request"]).encode())
        if tokens > config["max_input_tokens"]: raise ProviderFailure("stage_input_budget_exceeded")
        remaining = config["timeout_seconds"] - (time.monotonic()-started)
        if remaining < 1: raise ProviderFailure("run_wall_budget_exhausted")
        stage["timeout_seconds"] = remaining
        stage["provider_invoked"] = True
        response = (provider_override or CodexProvider()).extract(prompt, schema, dict(config, timeout_seconds=remaining), directory/"source-revision")
        usage.update(response.usage); private_write(directory/"output.json", response.text.encode())
        stage.update(provider=response.provider, model=response.model, response_id=response.response_id,
                     usage=response.usage, elapsed_seconds=response.elapsed_seconds, raw_output_sha256=sha(response.text.encode()))
        receipt.update(raw_output_sha256=sha(response.text.encode()), selected_extraction_stage="source_revision")
        if relational:
            projection_options = ({"field_evidence_policy": config.get("field_evidence_policy", "legacy_all_replacements"),
                                   "evidence_binding_policy": config.get("evidence_binding_policy"),
                                   "literal_witness_policy": config.get("literal_witness_policy"),
                                   "binding_failure_policy": config.get("binding_failure_policy"),
                                   "quantity_name_policy": config.get("quantity_name_policy"),
                                   "quantity_raw_policy": config.get("quantity_raw_policy"),
                                   "field_source_policy": config.get("field_source_policy")}
                                  if mode == "staged_fields" else {})
            revision = edit_contract.apply_edits(parent, bundle, edit_contract.NativeEdits.model_validate_json(response.text),
                                                 **review_options, **projection_options)
            proof = edit_contract.audit_revision(parent, revision, bundle)
        else:
            revision = (edit_contract.apply_edits(parent["raw_output"], edit_contract.NativeEdits.model_validate_json(response.text))
                        if mode == "edits" else NativeRevision.model_validate_json(response.text))
            proof = audit_revision(parent["raw_output"], revision, bundle)
        extraction = revision.revised_graph.expand(bundle)
        coverage_options = ({"parent": parent, "read_context_block_ids": proof["read_context_block_ids"]}
                            if mode == "staged_fields" and config.get("coverage_policy") else {})
        coverage = (edit_contract.validate_coverage(revision.revised_graph, inventory, bundle, **coverage_options) if mode == "staged_fields"
                    else validate_coverage(revision.revised_graph, inventory, bundle))
        validation = validate_extraction(extraction, bundle)
        validation["issues"].extend(coverage["issues"] + proof["issues"])
        validation["valid"] = not validation["issues"]
        receipt.update(revision_audit=proof, extraction=extraction.model_dump(), validation=validation,
            inventory_coverage=coverage, training_assessment=training_exclusions(extraction, bundle, validation))
        state = "succeeded" if validation["valid"] else "quarantined"
        if not validation["valid"]: error_code = "source_or_scientific_contract_validation_failed"
    except ProviderFailure as error:
        error_code = error.code; usage.update(error.usage)
    except ValidationError as error:
        state, error_code = "quarantined", "revision_schema_invalid"
        receipt["schema_errors"] = [{"location": list(e["loc"]), "type": e["type"], "message": e["msg"][:500]}
            for e in error.errors(include_input=False, include_context=False)]
    except (ValueError, KeyError, OSError) as error:
        state, error_code = "quarantined", "revision_" + type(error).__name__
        if isinstance(error, ValueError) and str(error).startswith(("source_field_", "focused_field_", "condition_revision_", "coverage_revision_", "staged_field_")):
            receipt["revision_error_detail"] = str(error)
    receipt.update(state=state, error_code=error_code, retryable=False, usage=usage,
                   elapsed_seconds=time.monotonic()-started)
    raw = canonical(receipt).encode(); path = directory/"receipt.json"; private_write(path, raw)
    store.finish(job, state=state, receipt_path=str(path.relative_to(store.root)), receipt_hash=sha(raw),
                 usage=usage, duration_seconds=receipt["elapsed_seconds"], error_code=error_code, retryable=False)
    return {k: receipt[k] for k in ("job_id", "state", "error_code", "usage", "elapsed_seconds")}
