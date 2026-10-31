"""One source-bound job per call; explicit failure, coverage, and scientific gates."""
from __future__ import annotations

import json
from collections import Counter
import importlib.metadata
from pathlib import Path
import platform
import time

from pydantic import ValidationError
import tiktoken

from . import PIPELINE_VERSION
from .contract import canonical, digest
from .evidence import source_catalog
from .prompt import PROMPT_HASH, PROMPT_VERSION, render
from .providers import CodexProvider, ProviderFailure, ResponsesProvider
from .sources import check_admission, load_bundle, private_write, sha
from .store import Store
from .validation import (REGISTRY_VERSION, VALIDATOR_VERSION, training_exclusions,
                         validate_extraction)
from .wire import CompactExtraction, WIRE_VERSION, output_schema
from .task_features import VERSION as TASK_FEATURE_VERSION, POLICY_SHA256 as TASK_FEATURE_POLICY_SHA256
from .quantities import NUMERIC_SYNTAX_VERSION


# Only developer-defined graph codes may supplement the public error shape.
# Do not copy arbitrary validator messages or input values into diagnostic codes.
GRAPH_ERROR_CODES = frozenset({
    "native_context_target_invalid", "native_state_sample_reference_invalid",
    "native_observation_reference_invalid", "native_observation_state_sample_mismatch",
    "duplicate_or_empty_native_sample_id", "duplicate_or_empty_native_state_id",
    "duplicate_or_empty_native_protocol_id", "duplicate_or_empty_native_result_id",
    "duplicate_relation_identifier", "duplicate_state_condition_identifier",
    "invalid_stable_condition_method_use", "invalid_component_relation",
    "cyclic_component_containment", "invalid_condition_support_reference",
    "cross_state_condition_support",
})


def schema_error_records(error):
    records = []
    for item in error.errors(include_input=False):
        record = {"location": list(item["loc"]), "type": item["type"]}
        code = str(item.get("ctx", {}).get("error", ""))
        if code in GRAPH_ERROR_CODES:
            record["code"] = code
        records.append(record)
    return records


def implementation_sources():
    package = Path(__file__).parent
    sources = {f"ingestion/materials_ner/{path.name}": path.read_bytes()
               for path in sorted(package.glob("*.py"))}
    sources["ingestion/extract/scientific_values.py"] = (
        package.parent / "extract" / "scientific_values.py").read_bytes()
    return sources


def configuration(provider="codex", model="gpt-6-luna", reasoning="medium",
                  timeout_seconds=900, max_input_tokens=60000, max_output_tokens=16000,
                  workflow="single_pass_v1", image_inputs=None):
    if provider not in {"codex", "responses"}:
        raise ValueError("unknown provider")
    if model not in {"gpt-6.1-sol", "gpt-6-luna"}:
        raise ValueError("model must be an explicitly evaluated candidate")
    if reasoning not in {"low", "medium", "high", "xhigh", "max"}:
        raise ValueError("unsupported reasoning effort")
    if not 10 <= timeout_seconds <= 3600 or not 1000 <= max_input_tokens <= 180000:
        raise ValueError("invalid worker budget")
    if not 1000 <= max_output_tokens <= 128000:
        raise ValueError("invalid output budget")
    if workflow not in {"single_pass_v1","inventory_v2","inventory_v3","inventory_v4","inventory_v5","inventory_v6","inventory_v7","inventory_v8","inventory_v9","inventory_v10","inventory_v11","inventory_v12","inventory_v13","inventory_v14","inventory_v15","inventory_v16","inventory_v17"}:
        raise ValueError("unknown workflow")
    if workflow in {"inventory_v2","inventory_v3","inventory_v4","inventory_v5","inventory_v6","inventory_v7","inventory_v8","inventory_v9","inventory_v10","inventory_v11","inventory_v12","inventory_v13","inventory_v14","inventory_v15","inventory_v16","inventory_v17"}:
        from . import wire_v2, inventory
        if workflow=="inventory_v3":
            from . import wire_v3 as wire_v2
        elif workflow=="inventory_v4":
            from . import wire_v4 as wire_v2
        elif workflow=="inventory_v5":
            from . import wire_v5 as wire_v2
        elif workflow=="inventory_v6":
            from . import wire_v6 as wire_v2
        elif workflow=="inventory_v7":
            from . import wire_v7 as wire_v2
        elif workflow=="inventory_v8":
            from . import wire_v8 as wire_v2
        elif workflow=="inventory_v9":
            from . import wire_v9 as wire_v2
        elif workflow=="inventory_v10":
            from . import wire_v10 as wire_v2
        elif workflow=="inventory_v11":
            from . import wire_v11 as wire_v2
        elif workflow=="inventory_v12":
            from . import wire_v12 as wire_v2
        elif workflow=="inventory_v13":
            from . import wire_v13 as wire_v2
        elif workflow=="inventory_v14":
            from . import wire_v14 as wire_v2
        elif workflow=="inventory_v15":
            from . import wire_v15 as wire_v2
        elif workflow=="inventory_v16":
            from . import wire_v16 as wire_v2
        elif workflow=="inventory_v17":
            from . import wire_v17 as wire_v2
        version, schema_hash, prompt_hash, prompt_version = (
            wire_v2.WIRE_VERSION,digest(wire_v2.output_schema()),wire_v2.PROMPT_HASH,wire_v2.PROMPT_VERSION)
        if workflow in {"inventory_v13", "inventory_v14","inventory_v15","inventory_v16","inventory_v17"}:
            from . import typed_inventory_v2
            if workflow in {"inventory_v14", "inventory_v15","inventory_v16","inventory_v17"}:
                from . import typed_inventory_v3 as typed_inventory_v2
            inventory_hash = digest(typed_inventory_v2.output_schema())
        else:
            inventory_hash=digest(inventory.output_schema())
    else:
        version,schema_hash,prompt_hash,prompt_version=WIRE_VERSION,digest(output_schema()),PROMPT_HASH,PROMPT_VERSION
        inventory_hash=None
    config = {"provider": provider, "model": model, "reasoning": reasoning,"workflow":workflow,
            "inventory_link_projection_version": (
                "materials-inventory-link-projection/1" if workflow in {"inventory_v4","inventory_v5","inventory_v6","inventory_v7","inventory_v8","inventory_v9","inventory_v10","inventory_v11","inventory_v12","inventory_v13","inventory_v14","inventory_v15","inventory_v16","inventory_v17"} else None),
            "max_inventory_repairs":1 if workflow in {"inventory_v2","inventory_v3","inventory_v4","inventory_v5","inventory_v6","inventory_v7","inventory_v8","inventory_v9","inventory_v10","inventory_v11","inventory_v12","inventory_v13","inventory_v14","inventory_v15","inventory_v16","inventory_v17"} else 0,
            "max_extraction_repairs":1 if workflow=="inventory_v2" else 0,
            "max_evidence_patches":1 if workflow in {"inventory_v3","inventory_v4","inventory_v5","inventory_v6","inventory_v7"} else 0,
            "timeout_seconds": timeout_seconds, "max_input_tokens": max_input_tokens,
            "max_output_tokens": max_output_tokens,
            "output_format": version,"inventory_schema_sha256":inventory_hash,
            "schema_sha256": schema_hash, "prompt_sha256": prompt_hash,
            "prompt_version": prompt_version, "validator_version": VALIDATOR_VERSION,
            "registry_version": REGISTRY_VERSION, "pipeline_version": PIPELINE_VERSION,
            "numeric_syntax_version": NUMERIC_SYNTAX_VERSION,
            "task_feature_version": TASK_FEATURE_VERSION, "task_feature_policy_sha256": TASK_FEATURE_POLICY_SHA256,
            "runtime": {"python": platform.python_version(),
                        "pydantic": importlib.metadata.version("pydantic"),
                        "tiktoken": importlib.metadata.version("tiktoken")},
            "implementation_sha256": digest({name: sha(raw) for name, raw in implementation_sources().items()})}

    if workflow in {"inventory_v13", "inventory_v14","inventory_v15","inventory_v16","inventory_v17"}:
        from . import typed_inventory_v2, quantities_v2, task_features, page_images
        if workflow in {"inventory_v14", "inventory_v15","inventory_v16","inventory_v17"}:
            from . import typed_inventory_v3 as typed_inventory_v2
        from .validation import ADOPTED_VALIDATOR_VERSION
        config.update(inventory_link_projection_version=typed_inventory_v2.PROJECTION,
            max_inventory_repairs=0, max_extraction_repairs=0, max_evidence_patches=0,
            registry_version=quantities_v2.REGISTRY_VERSION, validator_version=ADOPTED_VALIDATOR_VERSION,
            native_output_schema='materials-ner/12',
            task_feature_version=task_features.ADOPTED_VERSION,
            task_feature_policy_sha256=task_features.ADOPTED_POLICY_SHA256,
            image_inputs=page_images.validate_inputs(image_inputs or []))
        if workflow in {"inventory_v16", "inventory_v17"}:
            from .validation import PRESSURE_VALIDATOR_VERSION
            config.update(native_output_schema="materials-ner/13", validator_version=PRESSURE_VALIDATOR_VERSION,
                task_feature_version=task_features.PRESSURE_VERSION, task_feature_policy_sha256=task_features.PRESSURE_POLICY_SHA256)
    elif image_inputs:
        raise ValueError('image_inputs_require_inventory_v13')
    return config


def run_one(store: Store, *, job_id=None, provider_override=None, max_seconds=None):
    # Lease exceeds maximum allowed provider time. A crashed worker can be reclaimed.
    job = store.claim(lease_seconds=3900, job_id=job_id)
    if job is None:
        return None
    if job['config'].get('workflow') == 'compiled_source_fields_v1':
        from .compiled_field_worker import run_claimed
        return run_claimed(store,job,provider_override=provider_override,max_seconds=max_seconds)
    if job['config'].get('workflow') in {'source_item_stages_v1', 'source_item_stages_v2', 'source_item_stages_v3', 'source_item_stages_v4', 'source_item_stages_v5'}:
        from .item_worker import run_claimed
        return run_claimed(store, job, provider_override=provider_override, max_seconds=max_seconds)
    directory = store.root / "attempts" / job["id"] / job["lease_token"]
    directory.mkdir(parents=True, mode=0o700)
    started = time.monotonic()
    receipt = {"schema": "materials-ner-attempt/1", "job_id": job["id"],
               "attempt_id": job["lease_token"], "work_id": job["work_id"],
               "config": job["config"], "bundle_sha256": job["bundle_hash"],
               "output_token_limit_enforced_by_provider": job["config"]["provider"] == "responses",
               "scientific_acceptance": False, "production_writes": False}
    state, error_code, retryable, usage = "failed", None, False, Counter()
    try:
        config = job["config"]
        expected = configuration(**{key: config[key] for key in
                                   ("provider", "model", "reasoning", "timeout_seconds",
                                    "max_input_tokens", "max_output_tokens","workflow")},
                                 **({"image_inputs":config["image_inputs"]} if config["workflow"] in {"inventory_v13", "inventory_v14","inventory_v15","inventory_v16","inventory_v17"} else {}))
        if config != expected:
            raise ProviderFailure("worker_contract_drift")
        sources = implementation_sources()
        if digest({name: sha(raw) for name, raw in sources.items()}) != config["implementation_sha256"]:
            raise ProviderFailure("worker_source_changed_during_capture")
        code_root = store.root / "implementations" / config["implementation_sha256"]
        for name, raw in sources.items():
            target = code_root / name
            if target.exists() and target.read_bytes() != raw:
                raise ProviderFailure("implementation_snapshot_corrupt")
            if not target.exists():
                private_write(target, raw)
        private_write(code_root / "manifest.json", canonical({
            "files": {name: sha(raw) for name, raw in sources.items()},
            "runtime": config["runtime"]}).encode())
        bundle = load_bundle(store.root / "bundles" / f'{job["bundle_hash"]}.json')
        if digest(bundle.model_dump()) != job["bundle_hash"]:
            raise ProviderFailure("bundle_hash_mismatch")
        reasons = check_admission(bundle)
        if reasons:
            state, error_code = "blocked", reasons[0]
            receipt["admission_reasons"] = reasons
        else:
            catalog = source_catalog(bundle)
            receipt["source_catalog_sha256"] = digest(catalog)
            private_write(directory / "source-catalog.json", canonical(catalog).encode())
            provider = provider_override or (
                CodexProvider() if config["provider"] == "codex" else ResponsesProvider())
            job_budget=min(config["timeout_seconds"],max_seconds) if max_seconds is not None else config["timeout_seconds"]

            def call_stage(prompt,schema,stage_directory,stage_name):
                tokens=len(tiktoken.get_encoding("cl100k_base").encode(prompt+canonical(schema),disallowed_special=()))
                info={"name":stage_name,"prompt_sha256":sha(prompt.encode()),"schema_sha256":digest(schema),
                      "input_count":{"tokenizer":"cl100k_base","tokens":tokens,"provider_exact":False}}
                receipt.setdefault("stages",[]).append(info)
                private_write(stage_directory/"input.txt",prompt.encode())
                private_write(stage_directory/"schema.json",canonical(schema).encode())
                if tokens>config["max_input_tokens"]:raise ProviderFailure("stage_input_budget_exceeded")
                remaining=job_budget-(time.monotonic()-started)
                if remaining<1:raise ProviderFailure("run_wall_budget_exhausted",retryable=True)
                effective=dict(config,timeout_seconds=remaining)
                info["timeout_seconds"]=remaining
                response=provider.extract(prompt,schema,effective,stage_directory)
                usage.update(response.usage)
                info.update(provider=response.provider,model=response.model,response_id=response.response_id,
                            usage=response.usage,elapsed_seconds=response.elapsed_seconds,
                            raw_output_sha256=sha(response.text.encode()))
                private_write(stage_directory/"output.json",response.text.encode())
                return response

            source_inventory=None
            if config["workflow"] in {"inventory_v2","inventory_v3","inventory_v4","inventory_v5","inventory_v6","inventory_v7","inventory_v8","inventory_v9","inventory_v10","inventory_v11","inventory_v12","inventory_v13","inventory_v14","inventory_v15","inventory_v16","inventory_v17"}:
                from . import inventory,wire_v2
                wire_model=wire_v2.CompactExtractionV2
                inventory_render,inventory_render_repair=inventory.render,inventory.render_repair
                if config["workflow"]=="inventory_v3":
                    from . import wire_v3 as wire_v2
                    wire_model=wire_v2.CompactExtractionV3
                    inventory_render,inventory_render_repair=wire_v2.inventory_render,wire_v2.inventory_render_repair
                elif config["workflow"]=="inventory_v4":
                    from . import wire_v4 as wire_v2
                    wire_model=wire_v2.CompactExtractionV4
                    inventory_render,inventory_render_repair=wire_v2.inventory_render,wire_v2.inventory_render_repair
                elif config["workflow"]=="inventory_v5":
                    from . import wire_v5 as wire_v2
                    wire_model=wire_v2.SharedExtraction
                    inventory_render,inventory_render_repair=wire_v2.inventory_render,wire_v2.inventory_render_repair
                elif config["workflow"]=="inventory_v6":
                    from . import wire_v6 as wire_v2
                    wire_model=wire_v2.DefinedExtraction
                    inventory_render,inventory_render_repair=wire_v2.inventory_render,wire_v2.inventory_render_repair
                elif config["workflow"]=="inventory_v7":
                    from . import wire_v7 as wire_v2
                    wire_model=wire_v2.NativeExtraction
                    inventory_render,inventory_render_repair=wire_v2.inventory_render,wire_v2.inventory_render_repair
                elif config["workflow"]=="inventory_v8":
                    from . import wire_v8 as wire_v2
                    wire_model=wire_v2.RelationalExtraction
                    inventory_render,inventory_render_repair=wire_v2.inventory_render,wire_v2.inventory_render_repair
                elif config["workflow"]=="inventory_v9":
                    from . import wire_v9 as wire_v2
                    wire_model=wire_v2.ScopedExtraction
                    inventory_render,inventory_render_repair=wire_v2.inventory_render,wire_v2.inventory_render_repair
                elif config["workflow"]=="inventory_v10":
                    from . import wire_v10 as wire_v2
                    wire_model=wire_v2.DetectionExtraction
                    inventory_render,inventory_render_repair=wire_v2.inventory_render,wire_v2.inventory_render_repair
                elif config["workflow"]=="inventory_v11":
                    from . import wire_v11 as wire_v2
                    wire_model=wire_v2.AccountedExtraction
                    inventory_render,inventory_render_repair=wire_v2.inventory_render,wire_v2.inventory_render_repair
                elif config["workflow"]=="inventory_v12":
                    from . import wire_v12 as wire_v2
                    wire_model=wire_v2.AccountedExtraction
                    inventory_render,inventory_render_repair=wire_v2.inventory_render,wire_v2.inventory_render_repair
                if config["workflow"] in {"inventory_v13", "inventory_v14","inventory_v15","inventory_v16","inventory_v17"}:
                    from . import wire_v13 as wire_v2, typed_inventory_v2
                    if config["workflow"] in {"inventory_v14", "inventory_v15","inventory_v16","inventory_v17"}:
                        from . import wire_v14 as wire_v2, typed_inventory_v3 as typed_inventory_v2
                    if config["workflow"] == "inventory_v15":
                        from . import wire_v15 as wire_v2
                    if config["workflow"] == "inventory_v16":
                        from . import wire_v16 as wire_v2
                    if config["workflow"] == "inventory_v17":
                        from . import wire_v17 as wire_v2
                    wire_model=wire_v2.AccountedExtraction
                    inventory_render=typed_inventory_v2.render

                def read_inventory(response, stage):
                    if config["workflow"] in {"inventory_v13", "inventory_v14","inventory_v15","inventory_v16","inventory_v17"}:
                        from .frozen_inventory import parse
                        typed = typed_inventory_v2.TypedInventory.model_validate(parse(response.text))
                        checked = typed_inventory_v2.inspect(typed, bundle)
                        receipt.update(typed_inventory=typed.model_dump(), inventory_validation=checked)
                        read = dict(stage=stage, raw_output=response.text, validation=checked)
                        receipt.setdefault("inventory_reads", []).append(read)
                        if not checked['valid']:
                            return None, checked
                        proposed, proof = typed_inventory_v2.project(typed, bundle)
                        read['link_projection'] = proof
                        receipt['inventory'] = proposed.model_dump()
                        return proposed, checked
                    proposed = inventory.Inventory.model_validate_json(response.text)
                    read = {"stage": stage}
                    if config.get("inventory_link_projection_version"):
                        from .inventory_links import project_links
                        proposed, proof = project_links(proposed, bundle)
                        read.update(raw_output=response.text, link_projection=proof)
                    checked = inventory.validate_inventory(proposed, bundle)
                    for issue in read.get("link_projection", {}).get("blockers", []):
                        if issue not in checked["issues"]:
                            checked["issues"].append(issue)
                    checked["valid"] = not checked["issues"]
                    read["validation"] = checked
                    receipt.setdefault("inventory_reads", []).append(read)
                    receipt.update(inventory=proposed.model_dump(), inventory_validation=checked)
                    return proposed, checked

                inventory_schema = typed_inventory_v2.output_schema(bundle) if config["workflow"] in {"inventory_v13", "inventory_v14","inventory_v15","inventory_v16","inventory_v17"} else inventory.output_schema(bundle)
                inv_response=call_stage(inventory_render(bundle),inventory_schema,directory/"inventory","inventory")
                source_inventory,inventory_validation=read_inventory(inv_response,"inventory")
                if not inventory_validation["valid"] and config["max_inventory_repairs"]:
                    repaired=call_stage(inventory_render_repair(bundle,source_inventory,inventory_validation),
                        inventory.output_schema(bundle),directory/"inventory-repair","inventory_repair")
                    source_inventory,inventory_validation=read_inventory(repaired,"inventory_repair")
                if not inventory_validation["valid"]:
                    state="quarantined"
                    raise ProviderFailure("source_inventory_contract_invalid")
                schema=(wire_v2.output_schema(bundle,source_inventory) if config["workflow"] in {"inventory_v6","inventory_v7","inventory_v8","inventory_v9","inventory_v10","inventory_v11","inventory_v12","inventory_v13","inventory_v14","inventory_v15","inventory_v16","inventory_v17"}
                        else wire_v2.output_schema(bundle))
                prompt=wire_v2.render(bundle,source_inventory)
            else:
                schema=output_schema(bundle)
                prompt=render(bundle)
            receipt["effective_schema_sha256"] = digest(schema)
            # A deterministic local guard, explicitly not a claim of exact provider token usage.
            input_tokens = len(tiktoken.get_encoding("cl100k_base").encode(
                prompt + canonical(schema), disallowed_special=()))
            receipt["input_count"] = {"tokenizer": "cl100k_base", "tokens": input_tokens,
                                      "provider_exact": False}
            receipt["prompt_input_sha256"] = sha(prompt.encode())
            if input_tokens > config["max_input_tokens"]:
                state, error_code = "blocked", "whole_document_input_budget_exceeded"
            else:
                for read in range(1+config["max_extraction_repairs"]):
                    stage_name="extraction" if read==0 else "extraction_repair"
                    stage_directory=(directory/("extraction-initial" if read==0 else "extraction-repair")
                                     if source_inventory is not None else directory)
                    response=call_stage(prompt,schema,stage_directory,stage_name)
                    if read==0:
                        # Invalid JSON/schema is still a hash-bound raw attempt.
                        private_write(directory/"output.json",response.text.encode())
                        receipt["raw_output_sha256"]=sha(response.text.encode())
                    if config["workflow"] in {"inventory_v11","inventory_v12","inventory_v13","inventory_v14","inventory_v15","inventory_v16","inventory_v17"}:
                        try:
                            transport = wire_model.parse_response(response.text)
                            compact, proof = transport.project(source_inventory, bundle)
                        except wire_v2.AccountingError as error:
                            receipt["inventory_accounting_error"] = {"code": str(error)}
                            state = "quarantined"
                            raise ProviderFailure("inventory_accounting_projection_invalid") from error
                        receipt["inventory_accounting_projection"] = proof
                    else:
                        compact = (wire_model.model_validate_json(response.text) if source_inventory is not None
                                   else CompactExtraction.model_validate_json(response.text))
                    if source_inventory is not None:
                        # Keep inventory diagnostics even when the relational
                        # expansion fails, e.g. a claimed result with no rows.
                        coverage=wire_v2.validate_coverage(compact,source_inventory,bundle)
                        receipt["inventory_coverage"]=coverage
                    try:
                        extraction = compact.expand(bundle)
                    except ValidationError as error:
                        state = "quarantined"
                        receipt["expansion_diagnostics"]=[{"path":list(e["loc"]),"message":e["msg"]}
                            for e in error.errors(include_input=False,include_context=False,include_url=False)]
                        raise ProviderFailure("output_contract_inconsistent") from error
                    except ValueError as error:
                        # Unknown span/alias remains invalid, never guessed.
                        state = "quarantined"
                        raise ProviderFailure("output_source_binding_invalid") from error
                    validation = validate_extraction(extraction, bundle)
                    if source_inventory is not None:
                        validation["issues"].extend(coverage["issues"])
                        validation["valid"]=not validation["issues"]
                    receipt.setdefault("extraction_reads",[]).append({"stage":stage_name,
                        "validation_sha256":digest(validation),"valid":validation["valid"],
                        "issues":validation["issues"],"extraction_sha256":digest(extraction.model_dump())})
                    if read:
                        from .repair_selection import assess_repair
                        selection=assess_repair(chosen_compact,chosen_validation,compact,validation)
                        receipt["extraction_repair_selection"]=selection
                        if not selection["admitted"]:
                            compact,extraction,validation=chosen_compact,chosen_extraction,chosen_validation
                            break
                    chosen_compact,chosen_extraction,chosen_validation=compact,extraction,validation
                    if source_inventory is not None:receipt["inventory_coverage"]=coverage
                    # Keep the last parsed draft even if a later repair fails.
                    # Each raw stage also survives at its own immutable path.
                    private_write(directory/"output.json",response.text.encode())
                    private_write(directory/"input.txt",prompt.encode())
                    private_write(directory/"schema.json",canonical(schema).encode())
                    receipt.update(raw_output_sha256=sha(response.text.encode()),
                        input_count=receipt["stages"][-1]["input_count"],
                        prompt_input_sha256=sha(prompt.encode()),output_format=config["output_format"],
                        selected_extraction_stage=stage_name,
                        effective_provider_timeout_seconds=receipt["stages"][-1]["timeout_seconds"],
                        provider={"name":response.provider,"model":response.model,"response_id":response.response_id,
                                  "elapsed_seconds":response.elapsed_seconds},
                        identity_policy=("explicit_source_scoped_shared_references" if config["workflow"] in {"inventory_v5","inventory_v6","inventory_v7","inventory_v8","inventory_v9","inventory_v10","inventory_v11","inventory_v12","inventory_v13","inventory_v14","inventory_v15","inventory_v16","inventory_v17"}
                                         else "observation_scoped_no_automatic_sample_merge"),
                        extraction=extraction.model_dump(),validation=validation,
                        training_assessment=training_exclusions(extraction,bundle,validation))
                    if hasattr(compact,"projection_manifest"):
                        receipt["definition_projection"]=compact.projection_manifest()
                    if read>=config["max_extraction_repairs"] or not any(
                        i["code"] in wire_v2.REPAIRABLE_CODES for i in validation["issues"]):break
                    repair_prompt=wire_v2.render_repair(bundle,source_inventory,compact,validation)
                    repair_tokens=len(tiktoken.get_encoding("cl100k_base").encode(
                        repair_prompt+canonical(schema),disallowed_special=()))
                    if repair_tokens>config["max_input_tokens"] or job_budget-(time.monotonic()-started)<1:
                        receipt["extraction_repair_skipped"]="input_or_wall_budget"
                        break
                    prompt=repair_prompt
                if config["max_evidence_patches"]:
                    from . import evidence_patch
                    if config["workflow"]=="inventory_v5":
                        from . import evidence_patch_shared as evidence_patch
                    elif config["workflow"]=="inventory_v6":
                        from . import evidence_patch_defined as evidence_patch
                    elif config["workflow"]=="inventory_v7":
                        from . import evidence_patch_native as evidence_patch
                    from .repair_selection import assess_repair
                    patch_targets=evidence_patch.build_targets(compact,validation)
                    if patch_targets:
                        patch_prompt=(evidence_patch.render(bundle,compact,patch_targets,source_inventory)
                                      if config["workflow"] in {"inventory_v5","inventory_v6","inventory_v7","inventory_v8","inventory_v9","inventory_v10","inventory_v11","inventory_v12","inventory_v13","inventory_v14","inventory_v15","inventory_v16","inventory_v17"} else
                                      evidence_patch.render(bundle,compact,patch_targets))
                        patch_schema=evidence_patch.output_schema(bundle,compact,patch_targets)
                        patch_tokens=len(tiktoken.get_encoding("cl100k_base").encode(
                            patch_prompt+canonical(patch_schema),disallowed_special=()))
                        if patch_tokens>config["max_input_tokens"] or job_budget-(time.monotonic()-started)<1:
                            receipt["evidence_patch_skipped"]="input_or_wall_budget"
                        else:
                            patch_response=call_stage(patch_prompt,patch_schema,directory/"evidence-patch","evidence_patch")
                            proof={"schema":"materials-evidence-patch-receipt/1","applied":False,
                                   "targets":patch_targets,"raw_output":patch_response.text,
                                   "raw_output_sha256":sha(patch_response.text.encode())}
                            receipt["evidence_patch"]=proof
                            patch=evidence_patch.EvidencePatch.model_validate_json(patch_response.text)
                            candidate,patch_check=evidence_patch.apply_patch(compact,patch,patch_targets,bundle)
                            candidate_extraction=candidate.expand(bundle)
                            candidate_validation=validate_extraction(candidate_extraction,bundle)
                            candidate_coverage=wire_v2.validate_coverage(candidate,source_inventory,bundle)
                            candidate_validation["issues"].extend(candidate_coverage["issues"])
                            candidate_validation["valid"]=not candidate_validation["issues"]
                            selection=assess_repair(compact,validation,candidate,candidate_validation)
                            proof.update(application_checks=patch_check,selection=selection,
                                         patched_compact_sha256=digest(candidate.model_dump()))
                            private_write(directory/"patched-output.json",canonical(candidate.model_dump()).encode())
                            receipt.setdefault("extraction_reads",[]).append({"stage":"evidence_patch",
                                "validation_sha256":digest(candidate_validation),"valid":candidate_validation["valid"],
                                "issues":candidate_validation["issues"],"extraction_sha256":digest(candidate_extraction.model_dump())})
                            if selection["admitted"]:
                                proof["applied"]=True
                                compact,extraction,validation=candidate,candidate_extraction,candidate_validation
                                receipt.update(selected_extraction_stage="extraction_with_evidence_patch",
                                    inventory_coverage=candidate_coverage,extraction=extraction.model_dump(),validation=validation,
                                    training_assessment=training_exclusions(extraction,bundle,validation))
                state = ("success_empty" if extraction.outcome == "empty" else "succeeded") if validation["valid"] else "quarantined"
                if not validation["valid"]:
                    error_code = "source_or_scientific_contract_validation_failed"
    except ProviderFailure as error:
        error_code, retryable = error.code, error.retryable
        usage.update(error.usage)
    except ValidationError as error:
        state, error_code = "quarantined", "output_schema_invalid"
        receipt["schema_errors"] = schema_error_records(error)
    except (ValueError, OSError, KeyError) as error:
        error_code = "worker_" + type(error).__name__
    receipt.update(state=state, error_code=error_code, retryable=retryable, usage=usage,
                   elapsed_seconds=time.monotonic() - started)
    path = directory / "receipt.json"
    raw = canonical(receipt).encode()
    private_write(path, raw)
    store.finish(job, state=state, receipt_path=str(path.relative_to(store.root)),
                 receipt_hash=sha(raw), usage=usage, duration_seconds=receipt["elapsed_seconds"],
                 error_code=error_code, retryable=retryable)
    return {key: receipt[key] for key in ("job_id", "state", "error_code", "usage", "elapsed_seconds")}


def export_review_packet(store: Store, destination: Path, plan_path: Path | None = None) -> dict:
    """All planned jobs remain in the manifest; no silent successful-only export."""
    if destination.exists():
        raise ValueError("review packet destination already exists")
    destination.mkdir(parents=True, mode=0o700)
    rows, templates = [], []
    for job in store.results():
        item = {"job_id": job["id"], "work_id": job["work_id"], "state": job["state"],
                "bundle_sha256": job["bundle_hash"], "receipt_sha256": job["result_hash"]}
        if job["result_path"]:
            source_receipt = store.root / job["result_path"]
            raw = source_receipt.read_bytes()
            if sha(raw) != job["result_hash"]:
                raise ValueError("attempt receipt hash mismatch")
            receipt = json.loads(raw)
            # Private review packet, not a public Materials API payload.
            private_write(destination / f'{job["id"]}.json', raw)
            item["result_count"] = (len(receipt["extraction"]["results"])
                                    if "extraction" in receipt else None)
            output_path = source_receipt.with_name("output.json")
            if output_path.exists():
                output = output_path.read_bytes()
                expected_hash = receipt.get("raw_output_sha256")
                if expected_hash is not None and sha(output) != expected_hash:
                    raise ValueError("raw output integrity failure")
                private_write(destination / "raw-outputs" / f'{job["id"]}.json', output)
                item["raw_output_sha256"] = sha(output)
                item["raw_output_capture_hash_verified"] = expected_hash is not None
            templates.append({
                "job_id": job["id"], "receipt_sha256": job["result_hash"], "reviewer": None,
                "status": "pending", "gold_manifest_sha256": None,
                "checks": {key: "pending" for key in (
                    "publication_version", "supplement_and_figure_coverage", "composition_and_isotopes",
                    "sample_state_protocol_binding", "numeric_value_unit_bounds_uncertainty",
                    "primary_cited_and_computed_origin", "negative_observations", "result_completeness",
                    "correction_retraction_status", "leakage_and_split_group")},
            })
        bundle = load_bundle(store.root / "bundles" / f'{job["bundle_hash"]}.json')
        if digest(bundle.model_dump()) != job["bundle_hash"]:
            raise ValueError("review source bundle integrity failure")
        private_write(destination / "bundles" / f'{job["bundle_hash"]}.json',
                      canonical(bundle.model_dump()).encode())
        rows.append(item)
    manifest = {"schema": "materials-ner-review-packet/1", "jobs": rows,
                "summary": store.summary(), "scientific_acceptance": False,
                "ml_training_eligible": False, "canonical_import_status": "pending_adjudication",
                "job_denominator_scope": "enqueued_jobs_only",
                "missing_release_gates": ["source_currentness_and_rights", "independent_human_gold",
                                         "sample_identity_and_composition", "ML_identity_dependency_split",
                                         "reviewed_canonical_import_and_projection_diff"]}
    if plan_path is not None:
        from .planning import load_plan
        plan, plan_hash = load_plan(plan_path)
        manifest["source_plan"] = {"sha256": plan_hash, "summary": plan["summary"],
                                   "scope": "all_inventoried_papers_including_unacquired_and_blocked"}
        private_write(destination / "source-plan.json", canonical(plan).encode())
    private_write(destination / "review-template.json", canonical({
        "schema": "materials-ner-human-review-template/1", "template_only": True,
        "scientific_acceptance": False, "jobs": templates,
    }).encode())
    private_write(destination / "manifest.json", canonical(manifest).encode())
    return {"manifest_sha256": digest(manifest), "jobs": len(rows), "path": str(destination)}
