"""Offline gates for mixed-version rejection, failed requests and review boundaries."""
import gzip
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


snapshot = module("verify_public_snapshot")
review = module("build_nextstage_review_package")


def network(monkeypatch, *, change_version=False, fail_materials=False, changed_observation=False):
    seed = json.loads((ROOT / snapshot.SEED).read_bytes())
    versions = 0

    def fetch(url, accept_encoding="identity"):
        nonlocal versions
        headers = {"x-materials-cache": "HIT"}
        if url == snapshot.API + "/version":
            versions += 1
            body = json.dumps({"site_version": "abcdef1" if versions == 1 or not change_version else "abcdef2",
                               "dataset_version": "v2026.09.03", "api_version": "1"}).encode()
        elif url == snapshot.API + "/stats":
            body = json.dumps({"total_papers": 10, "total_materials": 5, "total_chunks": 30,
                               "dataset_version": "v2026.09.03", "papers_by_year_arxiv": {"2026": 7},
                               "papers_by_year_aps": {"2026": 3}}).encode()
        elif url == snapshot.SITE + "/":
            body = b'<a href="https://github.com/JackZH26/SCLib_JZIS/commit/abcdef1">Version</a>'
        elif url.startswith(snapshot.SITE + "/research-hypotheses/"):
            body = (ROOT / "frontend/public" / url.removeprefix(snapshot.SITE + "/")).read_bytes()
        elif url.endswith("/enrichment"):
            from urllib.parse import unquote
            mid = unquote(url.split("/")[-2])
            row = next(r for r in seed["rows"] if r["material_id"] == mid)
            recovery = {**row, "seed_id": seed["seed_id"], "seed_sha256": seed["seed_sha256"]}
            if changed_observation:
                recovery = deepcopy(recovery)
                recovery["observations"][0]["value"] = "changed"
            body = json.dumps({"source_recovery_batch": recovery, "scientific_acceptance": False,
                               "ml_training_approved": False}).encode()
        elif url.startswith(snapshot.API + "/materials?"):
            if url.removeprefix(snapshot.API) in snapshot.REFUSALS.values():
                return {"url": url, "status": 422, "error": "HTTPError", "elapsed_seconds": .1}, None
            if fail_materials:
                return {"url": url, "status": 503, "error": "HTTPError", "elapsed_seconds": 45}, None
            body = json.dumps({"total": 1, "results": [{"formula": "MgB2"}]}).encode()
        else:
            raise AssertionError("unexpected GET " + url)
        return {"url": url, "status": 200, "error": None, "elapsed_seconds": .1,
                "bytes": len(body), "sha256": snapshot.sha(body), "headers": headers}, body

    monkeypatch.setattr(snapshot, "fetch", fetch)


def test_full_pinned_static_files_and_recovery_have_no_scientific_authority(monkeypatch):
    network(monkeypatch)
    result = snapshot.collect(samples=2, all_details=True)
    assert result["operational_acceptance"] is True
    assert result["detail_scope"] == {"checked": 206, "available": 206, "complete": True}
    assert len(result["recovery"]) == 16
    assert sum(r["observations"] for r in result["recovery"]) == 55
    assert result["scientific_acceptance"] is result["ml_training_approved"] is False
    assert result["catalogue_transaction_snapshot"] is False


def test_mid_capture_deploy_is_not_accepted(monkeypatch):
    network(monkeypatch, change_version=True)
    result = snapshot.collect(samples=1)
    assert result["operational_acceptance"] is False
    assert {c["name"] for c in result["checks"] if not c["passed"]} == {"version_stable_across_capture"}


def test_failed_attempts_remain_in_latency_denominator(monkeypatch):
    network(monkeypatch, fail_materials=True)
    result = snapshot.collect(samples=2)
    assert result["operational_acceptance"] is False
    for value in result["latency"].values():
        assert value["attempts"] == value["failures"] == 2
        assert value["successful"] == 0
        assert value["p95_seconds"] is value["median_seconds"] is None


def test_changed_recovery_value_is_not_admitted(monkeypatch):
    network(monkeypatch, changed_observation=True)
    result = snapshot.collect(samples=1)
    assert result["operational_acceptance"] is False
    assert not any(r["matched"] for r in result["recovery"])


def test_pin_checks_exact_bytes_and_size_and_quantiles_do_not_impute_failures():
    body = b'{"data": 1}\n'
    pin = {"bytes": len(body), "sha256": snapshot.sha(body)}
    assert snapshot.check_pin(body, pin)
    assert not snapshot.check_pin(body.rstrip(), pin)
    assert not snapshot.check_pin(None, pin)
    result = snapshot.latency_summary([{"status": 200, "error": None, "elapsed_seconds": 1},
                                       {"status": 200, "error": None, "elapsed_seconds": 9},
                                       {"status": 503, "error": "HTTPError", "elapsed_seconds": 45}])
    assert result["failures"] == 1 and result["p95_seconds"] == 9
    assert result["slo_acceptance"] is None


def test_gzip_pin_checks_decoded_bytes_with_a_decompression_size_bound(monkeypatch):
    source = b'{"data": 1}\n'
    assert snapshot.decoded_body(gzip.compress(source), "gzip") == source
    monkeypatch.setattr(snapshot, "MAX_BYTES", 20)
    with pytest.raises(ValueError, match="decoded_response_size_limit"):
        snapshot.decoded_body(gzip.compress(b"x" * 1000), "gzip")
    with pytest.raises(ValueError, match="unsupported_content_encoding"):
        snapshot.decoded_body(b"x", "br")


def inputs():
    return [review.load(path)[0] for path in (review.SEED, review.BENCH, review.CAT)]


def test_review_inventory_binds_conditions_without_labels_or_false_holdout():
    package = review.build(*inputs(), pins=[])
    questions = package["retrieval_acquisition"]["questions"]
    assert len(questions) == len({q["id"] for q in questions}) == 60
    assert package["retrieval_acquisition"]["language_counts"] == {"en": 40, "zh": 20}
    assert all(q["split"] == "unassigned" and q["scientific_support_label"] is None
               and q["execution_status"] == "not_run" and not q["held_out_eligible"] for q in questions)
    assert not package["retrieval_acquisition"]["gold_set"]
    assert package["ml_readiness"]["eligible_labels_established"] == 0
    assert len(package["material_review"]["rows"]) == 16
    assert all(r["unknowns"] and not r["reviewers"] and r["decision"] is None for r in package["material_review"]["rows"])
    for row in package["material_review"]["rows"]:
        related = [q for q in questions if row["material_id"] in q["material_ids"]]
        assert len(related) == 3
        assert related[0]["source_group_ids"] == related[1]["source_group_ids"] == related[2]["source_group_ids"]
        ids = {o["observation_id"] for o in row["observations"]}
        assert all(set(q["source_observation_ids"]) == ids for q in related)
    markdown = review.render_markdown(package)
    assert markdown.count("Reviewers: unassigned. Decision: pending.") == 16
    assert "60. " in markdown and "not human adjudication" in markdown


@pytest.mark.parametrize("field", ["human_reviewed", "scientific_acceptance", "ml_training_approved", "database_changed"])
def test_changed_seed_authority_requires_new_review_protocol(field):
    seed, benchmark, catalogue = inputs()
    seed[field] = True
    with pytest.raises(ValueError, match="seed_authority_changed"):
        review.build(seed, benchmark, catalogue, [])


def test_changed_prompt_or_hypothesis_review_inventory_is_rejected():
    seed, benchmark, catalogue = inputs()
    seed["rows"][0]["formula"] = "different"
    with pytest.raises(ValueError, match="prompt_inventory"):
        review.build(seed, benchmark, catalogue, [])
    seed, benchmark, catalogue = inputs()
    catalogue["candidates"][0]["human_scientific_review"] = {"decision": "approved"}
    with pytest.raises(ValueError, match="hypothesis_review_state_changed"):
        review.build(seed, benchmark, catalogue, [])
