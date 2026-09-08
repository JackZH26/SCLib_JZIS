"""Actual disposable SQL publication fixtures; no production grants or data.

The default source is an Inferred curation, not an experimental finding.
Additional captured-literature and Computed-run records are synthetic as well;
no real paper or calculation is fetched or executed. The existing 0054 capsule
supplies technical integrity only. Every dependency needs its own test grant.
"""
from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa

from models.db import Base
from services import research_distribution_contract as contract
from services import research_freeze
from services.research_distribution_inputs import load_live_closure
from services.research_priority import canonical_json, digest
from tests.test_priority_public_bundle import (
    disclosure_for,
    public_release_payload,
    reseal_public_release,
)
from tests.test_research_freeze import add, approved, seed
from tests.test_research_publication import actors
from tests.test_research_release_schema import capture


async def source_context(db, *, event_type="curation", knowledge_origin="Inferred"):
    people = await actors(db)
    source = await seed(db, with_children=False)
    await db.execute(sa.text("UPDATE materials SET formula='TEST',formula_normalized='TEST',"
        "family='synthetic',total_papers=1,needs_review=false WHERE id=:id"), {"id": source["material"]})
    await db.execute(sa.text("UPDATE works SET publication_status='active' WHERE id=:id"), {"id": source["work"]})
    await db.execute(sa.text("UPDATE material_states SET pressure_status='explicit_ambient',pressure_gpa=0 WHERE id=:id"),
                     {"id": source["state"]})
    await db.execute(sa.text("UPDATE research_events SET event_type=:event_type,knowledge_origin=:origin WHERE id=:id"),
                     {"id": source["event"], "origin": "Inferred" if knowledge_origin == "Computed" else knowledge_origin,
                      "event_type": event_type})
    if knowledge_origin == "Computed":
        document = {"synthetic_fixture": True, "actual_calculation_executed": False, "kind": "dft_run_manifest"}
        body = canonical_json(document).encode("utf-8")
        sha = hashlib.sha256(body).hexdigest()
        artifact = await add(db, "evidence_artifacts", kind="run_manifest", schema_version="synthetic-dft/1",
            source="synthetic-distribution-test", record_sha256=sha, bytes_sha256=sha,
            hash_status="verified", access="restricted", metadata={"synthetic": True})
        source["args"]["artifact_bytes"][sha] = body
        run = await add(db, "research_runs", run_kind="dft", status="completed", code_version="synthetic-not-executed/1",
            settings_schema_version="synthetic-dft/1", settings={"synthetic": True},
            input_manifest_id=artifact["id"], output_manifest_id=artifact["id"], record_sha256=digest(document))
        source["run"] = run["id"]
        await db.execute(sa.text("UPDATE research_events SET producer_run_id=:run,knowledge_origin='Computed' WHERE id=:id"),
                         {"run": run["id"], "id": source["event"]})
    _, args = await approved(db, source)
    frozen = await research_freeze.freeze_research_release(db, **args, dry_run=False)
    return {"actors": people, "source": source, "capsule": frozen,
            "capsule_bytes": args["artifact_bytes"], "internal_artifacts": {},
            "evidence_source_kind": "calculation" if event_type == "calculation" and knowledge_origin == "Computed" else "curation"}


async def source_capture_context(db, *, provider_revision="1"):
    """Actual accepted Work mapping and immutable 0052 source/capture rows."""
    from services.source_registry import import_source_provenance_bundle
    from tests.test_source_registry import bundle

    shared = await source_context(db)
    source = shared["source"]
    await add(db, "paper_work_map", paper_id=source["paper"], work_id=source["work"],
              relation_type="preprint", match_method="manual", review_status="accepted")
    body = b"Synthetic captured literature fixture; no real publication or scientific finding."
    sha = hashlib.sha256(body).hexdigest()
    value = bundle(source["paper"], source["work"])
    value["source_revisions"][0].update(provider_revision=provider_revision, revision_key="synthetic-v" + provider_revision,
        metadata_sha256=digest({"synthetic_provider_revision": provider_revision}))
    value["source_captures"][0]["bytes_sha256"] = sha
    await import_source_provenance_bundle(db, value, dry_run=False)
    revision = await capture(db, "source_revisions", value["source_revisions"][0]["id"])
    captured = await capture(db, "source_captures", value["source_captures"][0]["id"])
    shared.update(evidence_source_kind="literature", source_bytes={sha: body},
        evidence_root={"kind": "source_capture", "source_revision_id": revision["id"],
            "source_revision_record_sha256": revision["record_sha256"], "capture_id": captured["id"],
            "capture_record_sha256": captured["record_sha256"], "bytes_sha256": sha})
    return shared


async def distribution_inputs(db, release, *, shared=None):
    """Bind complete actual artifact bytes and source/capsule row identities."""
    from services.priority_public_bundle import build_public_bundle

    shared = shared or await source_context(db)
    release = deepcopy(release)
    bundle = build_public_bundle(release, disclosure=disclosure_for(release))
    source, capsule = shared["source"], shared["capsule"]
    rows = {(row["table"], row["row_id"]): row for row in capsule["manifest"]["rows"]}
    claim = rows[("material_claims", str(source["claim"]))]
    bindings = []
    known_bytes = dict(shared["capsule_bytes"])
    known_bytes.update(shared.get("source_bytes", {}))
    await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
    for artifact in sorted(release["artifacts"], key=lambda item: item["id"]):
        identity = None
        if artifact["kind"] in {"material", "state"}:
            table = "materials" if artifact["kind"] == "material" else "material_states"
            identifier = source["material"] if table == "materials" else str(source["state"])
            actual = await capture(db, table, identifier)
            identity = {"table": table, "row_id": str(identifier), "row_sha256": digest(actual)}
        if artifact["kind"] == "evidence":
            assert artifact["content"]["source_kind"] == shared["evidence_source_kind"]
            root = deepcopy(shared.get("evidence_root", {"kind": "frozen_result",
                "manifest_sha256": capsule["manifest_sha256"], "table": "material_claims",
                "row_id": claim["row_id"], "row_sha256": claim["row_sha256"]}))
        else:
            body = canonical_json(artifact).encode("utf-8")
            sha = hashlib.sha256(body).hexdigest()
            known_bytes[sha] = body
            if sha not in shared["internal_artifacts"]:
                row = await add(db, "evidence_artifacts", kind=contract.INTERNAL_KINDS[artifact["kind"]],
                    schema_version=contract.INTERNAL_SCHEMA, source="synthetic-rps-distribution",
                    record_sha256=sha, bytes_sha256=sha, hash_status="verified", access="restricted",
                    metadata={"synthetic": True})
                shared["internal_artifacts"][sha] = row
            row = shared["internal_artifacts"][sha]
            root = {"kind": "internal_artifact", "evidence_artifact_id": str(row["id"]),
                    "artifact_kind": row["kind"], "record_sha256": sha, "bytes_sha256": sha}
        bindings.append({"artifact_id": artifact["id"], "artifact_sha256": artifact["sha256"],
                         "artifact_kind": artifact["kind"], "root": root, "identity": identity})
    binding = {"version": contract.BINDINGS_VERSION, "release_id": release["id"],
               "release_manifest_sha256": release["manifest_sha256"],
               "public_bundle_sha256": bundle["bundle_sha256"], "bindings": bindings}
    args = {"release": release, "bindings": binding, "expected_release_sha256": release["manifest_sha256"],
            "expected_bindings_sha256": digest(binding), "public_bundle": bundle,
            "expected_public_bundle_sha256": bundle["bundle_sha256"]}
    plan = contract.distribution_loading_plan(**args)
    live = await load_live_closure(db, plan["live_row_roots"])
    byte_keys = {row["data"]["bytes_sha256"] for row in live
                 if row["table"] in {"evidence_artifacts", "source_captures"}}
    args.update(artifact_bytes={sha: known_bytes[sha] for sha in byte_keys},
                capsule_artifact_bytes={sha: shared["capsule_bytes"] for sha in plan["capsule_manifest_sha256s"]})
    return {"shared": shared, "arguments": args, "release": release, "bundle": bundle}


async def publish_distribution(db, release, *, shared=None, publish=True, permissions=True, omit_permission_table=None):
    from services import research_distribution as service

    context = await distribution_inputs(db, release, shared=shared)
    people = context["shared"]["actors"]
    request_prefix = "synthetic:" + uuid4().hex
    result = await service.register_distribution(db, actor_user_id=people["curator"],
        request_key=request_prefix + ":register", **context["arguments"], dry_run=False)
    package_table = Base.metadata.tables["research_distribution_packages"]
    package = (await db.execute(sa.select(package_table).where(sa.cast(package_table.c.id, sa.Text)
               == str(result["package_id"])))).mappings().one()
    context.update(registration=result, package=package, permissions=[], request_prefix=request_prefix)
    if permissions:
        for index, dependency in enumerate(result["inventory"]["dependencies"]):
            if dependency["table"] == omit_permission_table:
                continue
            document = service.rights_review_payload(package, dependency, "permission-on-file", "synthetic_full_bundle")
            body = canonical_json(document).encode("utf-8")
            sha = hashlib.sha256(body).hexdigest()
            rights = await add(db, "evidence_artifacts", kind="review",
                schema_version="rps-distribution-rights/1.0.0", source="synthetic-rights-review",
                record_sha256=sha, bytes_sha256=sha, hash_status="verified", access="restricted",
                metadata={"distribution_rights": document})
            actual = await capture(db, "evidence_artifacts", rights["id"])
            arguments = dict(actor_user_id=people["reviewer"], package_id=result["package_id"],
                dependency_id=dependency["dependency_id"], decision="allow", license_code="permission-on-file",
                basis_code="synthetic_full_bundle", reason_code="synthetic_distribution_permission",
                rights_artifact_id=rights["id"], expected_rights_row_sha256=digest(actual), rights_bytes=body)
            receipt = await service.decide_distribution_permission(db,
                request_key=request_prefix + ":permission:" + str(index), **arguments, dry_run=False)
            context["permissions"].append({"receipt": receipt, "arguments": arguments, "dependency": dependency})
    if publish:
        context["review"] = await service.review_distribution(db, actor_user_id=people["reviewer"],
            request_key=request_prefix + ":review", package_id=result["package_id"],
            expected_inventory_sha256=result["inventory_sha256"], disclosure_approved=True,
            reason_code="synthetic_independent_disclosure", dry_run=False)
        context["action"] = await service.distribution_action(db, actor_user_id=people["publisher"],
            request_key=request_prefix + ":publish", package_id=result["package_id"], review_id=context["review"]["id"],
            expected_inventory_sha256=result["inventory_sha256"], kind="publish",
            reason_code="synthetic_publication", dry_run=False)
    return context


async def revoke_distribution_permission(db, context, *, table_name=None):
    from services import research_distribution as service

    permission = next(item for item in context["permissions"]
                      if table_name is None or item["dependency"]["table"] == table_name)
    return await service.decide_distribution_permission(db,
        **{**permission["arguments"], "decision": "revoke", "reason_code": "synthetic_rights_withdrawal"},
        request_key="synthetic:revoke:" + uuid4().hex, supersedes_id=permission["receipt"]["id"], dry_run=False)


def release_document(identifier=None, *, source_kind=None):
    value = public_release_payload()
    value["id"] = identifier or "synthetic-rps-" + uuid4().hex
    changed = {}
    if source_kind:
        for artifact in value["artifacts"]:
            if artifact["kind"] == "evidence":
                artifact["content"]["source_kind"] = source_kind
                artifact["sha256"] = digest({key: item for key, item in artifact.items() if key != "sha256"})
                changed[artifact["id"]] = artifact["sha256"]
        def references(item):
            if type(item) is dict:
                if set(item) == {"id", "sha256"} and item["id"] in changed:
                    item["sha256"] = changed[item["id"]]
                else:
                    for child in item.values():
                        references(child)
            elif type(item) is list:
                for child in item:
                    references(child)
        references(value)
    return reseal_public_release(value)


@dataclass
class LocalDistributions:
    directory: Path
    db: object
    shared: dict
    payloads: dict = field(default_factory=dict)
    bundles: dict = field(default_factory=dict)
    contexts: dict = field(default_factory=dict)

    def __iter__(self):
        return iter((self.directory, self.payloads))

    async def publish(self, release):
        context = await publish_distribution(self.db, release, shared=self.shared)
        identifier = release["id"]
        self.payloads[identifier] = context["release"]
        self.bundles[identifier] = context["bundle"]
        self.contexts[identifier] = context
        for suffix, value in ((".json", context["release"]), (".public.json", context["bundle"])):
            (self.directory / (identifier + suffix)).write_text(canonical_json(value), encoding="utf-8")
        await self.db.commit()
        return context
