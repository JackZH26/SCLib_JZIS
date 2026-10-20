"""Private model-to-alias mapping, source-only packets for blinded prediction audits."""

from copy import deepcopy
import secrets

from .contract import digest
from .evaluation import CRITICAL_FIELDS
from .providers import ProviderConfig, common_configuration_hash


def blinded_review(models):
    if set(models) != {"local_mlx", "gemini", "openai"}:
        raise ValueError("review_requires_three_model_packages")
    manifests, common = set(), set()
    packets, mapping = {}, {}
    allowed = set(CRITICAL_FIELDS) | {"anchor_id", "evidence", "sc_outcome"}
    for name, output in models.items():
        config = output.get("configuration")
        if (
            not isinstance(config, dict)
            or digest(config) != output.get("config_sha256")
            or output.get("provider") != name
            or config.get("provider", {}).get("provider") != name
        ):
            raise ValueError("review_model_configuration_unbound")
        ProviderConfig(**config["provider"])
        manifests.add(output["manifest_sha256"])
        common.add(common_configuration_hash(config))
        label = "review-" + secrets.token_hex(8)
        claims = deepcopy(output["claims_by_work"])
        if any(
            set(c) - allowed or not set(CRITICAL_FIELDS) <= set(c)
            for rows in claims.values()
            for c in rows
        ):
            raise ValueError("review_claim_contains_unknown_metadata_or_missing_fields")
        packets[label] = {
            "claims_by_work": claims,
            "prediction_audit": {
                "status": "unannotated",
                "annotators": None,
                "adjudicator": None,
                "items": {
                    digest(c): {
                        "evidence_support": None,
                        "locator_resolves": None,
                        "severe_errors": None,
                    }
                    for rows in claims.values()
                    for c in rows
                },
            },
        }
        mapping[label] = {
            "provider": name,
            "config_sha256": output["config_sha256"],
            "comparison_package_sha256": digest(output),
        }
    if len(manifests) != 1 or len(common) != 1:
        raise ValueError("review_inputs_or_common_configuration_differ")
    if len({digest(sorted(p["claims_by_work"])) for p in packets.values()}) != 1:
        raise ValueError("review_work_scopes_differ")
    body = {
        "version": "materials-ner-blinded-review/1",
        "manifest_sha256": manifests.pop(),
        "status": "unannotated",
        "models": packets,
        "scientific_acceptance": False,
    }
    review = {**body, "receipt_sha256": digest(body)}
    return review, {
        "version": "materials-ner-private-review-mapping/1",
        "review_receipt_sha256": review["receipt_sha256"],
        "manifest_sha256": review["manifest_sha256"],
        "aliases": mapping,
    }
