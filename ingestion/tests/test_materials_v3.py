"""Scientific counterexamples and recovery tests; no provider/production access."""

import json
from copy import deepcopy

import pytest

from ingestion.materials_v3.assembly import assemble_reports
from ingestion.materials_v3.blocks import ArticleHTML, make_blocks, parse_source
from ingestion.materials_v3.contract import (
    CandidateError,
    occurrence_key,
    parse_json,
    validate_candidate,
)
from ingestion.materials_v3.evaluation import counts, evaluate, paired_bootstrap
from ingestion.materials_v3.ledger import Ledger, LeaseError
from ingestion.materials_v3.manifest import freeze_manifest, validate_manifest
from ingestion.materials_v3.pipeline import Pipeline
from ingestion.materials_v3.providers import (
    MODEL,
    REVISION,
    OutputLimit,
    ProviderConfig,
    ProviderError,
    Response,
)
from ingestion.materials_v3.registry import normalize_quantity


def quantity(raw="240 K", value=240, unit="K", relation="point", lower=None, upper=None):
    return dict(
        raw_text=raw,
        raw_unit=unit,
        relation=relation,
        value=value,
        lower=lower,
        upper=upper,
        approximate=False,
        uncertainty_raw=None,
    )


def fixture(
    text="LaH10 sample S1 pressure scan at 150 GPa loading: onset Tc 240 K; zero Tc 232 K.",
):
    block = dict(
        block_id="b-test",
        text=text,
        source_sha256="a" * 64,
        source_start=0,
        source_end=len(text),
        kind="text",
    )

    def evidence(role):
        return [dict(block_id=block["block_id"], quote=text, role=role)]

    result = dict(
        local_id="r1",
        subject=dict(
            name_raw="LaH10",
            formula_raw="LaH10",
            identity_kind="exact_composition",
            evidence=evidence("subject"),
        ),
        sample=dict(
            label_raw="S1", form_raw=None, preparation_raw=None, evidence=evidence("subject")
        ),
        conditions=[
            dict(
                key="measurement_pressure",
                status="reported",
                quantity=quantity("150 GPa", 150, "GPa"),
                qualitative=None,
                evidence=evidence("condition"),
            )
        ],
        series_point=dict(
            series_label_raw="pressure scan",
            scan_variables=["measurement_pressure"],
            point_label_raw="150 GPa",
            step_index_raw=0,
            path_direction="loading",
            replicate_label_raw=None,
            evidence=evidence("relation"),
        ),
        event=dict(
            event_kind="measurement",
            knowledge_origin="Observed",
            source_role="primary",
            method_raw=None,
            calculation_settings_raw=None,
            cited_source_raw=None,
            evidence=evidence("method"),
        ),
        sc_outcome="positive_reported",
        outcome_evidence=evidence("outcome"),
        properties=[],
    )
    for criterion, tc in (("onset", 240), ("zero_resistance", 232)):
        result["properties"].append(
            dict(
                property_key="tc",
                status="reported",
                quantity=quantity(f"{tc} K", tc),
                qualitative=None,
                qualifiers=dict(tc_definition=criterion),
                knowledge_origin="Observed",
                source_role="primary",
                evidence=evidence("value"),
            )
        )
    return dict(
        schema_version="materials-ner-candidate/3.0", results=[result], unresolved_links=[]
    ), block


def test_multiple_criteria_are_retained_and_normalized():
    value, block = fixture()
    out = validate_candidate(value, [block])
    assert len(out["normalized"][0]["properties"]) == 2
    assert out["normalized"][0]["properties"][0]["quantity"]["value"] == 240
    assert out["bound_evidence"][0]["source_end"] == len(block["text"])
    assert out["scientific_acceptance"] is False


def test_ambiguous_quotes_and_wrong_offsets_identify_each_failed_field():
    value, block = fixture(
        "LaH10 sample S1 pressure scan at 150 GPa loading: onset Tc 240 K; zero Tc 232 K. "
        "The unloading measurement was at 150 GPa with onset Tc 236 K."
    )
    subject = value["results"][0]["subject"]["evidence"][0]
    subject.update(quote="LaH10", char_start=1, char_end=6)
    condition = value["results"][0]["conditions"][0]["evidence"][0]
    condition.update(quote="150 GPa", char_start=None, char_end=None)
    with pytest.raises(CandidateError) as error:
        validate_candidate(value, [block])
    assert set(error.value.errors) == {
        "quote_offset_mismatch:results/0/subject/evidence/0",
        "quote_missing_or_ambiguous_offset:results/0/conditions/0/evidence/0",
    }


def test_repair_compacts_only_valid_json_and_preserves_invalid_source_output():
    from ingestion.materials_v3.prompt import messages

    candidate, block = fixture()
    original = json.dumps(candidate, ensure_ascii=False, indent=2)
    payload = json.loads(
        messages([block], repair_errors=["error"], previous=original)[1]["content"]
    )
    compact = payload["previous_candidate"]
    assert len(compact) < len(original)
    assert json.loads(compact) == candidate
    duplicate = '{"results":[],"results":[1]}'
    malformed = '{"results":'
    overflow = '{"quantity":1e999}'
    for invalid in (duplicate, malformed, overflow):
        payload = json.loads(
            messages([block], repair_errors=["error"], previous=invalid)[1]["content"]
        )
        assert payload["previous_candidate"] == invalid


@pytest.mark.parametrize(
    "mutation,error",
    [
        (lambda v: v.update(public_eligible=True), "schema:"),
        (lambda v: v["results"][0].update(sc_outcome="not_detected"), "schema:"),
        (
            lambda v: v["results"][0]["event"].update(event_kind="calculation"),
            "calculation_cannot_be_observed",
        ),
        (
            lambda v: v["results"][0]["properties"][0]["quantity"].update(value=250),
            "quantity_not_in_raw_text",
        ),
        (
            lambda v: v["results"][0]["subject"]["evidence"][0].update(block_id="b-missing"),
            "unknown_evidence_block",
        ),
        (
            lambda v: v["results"][0]["subject"]["evidence"][0].update(quote="Invented statement"),
            "quote_missing",
        ),
        (
            lambda v: v["results"][0]["subject"]["evidence"][0].update(char_start=1, char_end=10),
            "quote_offset_mismatch",
        ),
        (lambda v: v["results"].append(deepcopy(v["results"][0])), "duplicate_local_id"),
    ],
)
def test_semantic_and_authority_failures(mutation, error):
    value, block = fixture()
    mutation(value)
    with pytest.raises(CandidateError, match=error):
        validate_candidate(value, [block])


@pytest.mark.parametrize("text", ['{"results":[],"results":[1]}', '{"value":NaN}', "{} trailing"])
def test_strict_json(text):
    with pytest.raises(CandidateError):
        parse_json(text)


def test_unknown_pressure_is_never_ambient():
    value, block = fixture()
    value["results"][0]["conditions"] = []
    out = validate_candidate(value, [block])
    assert out["normalized"][0]["conditions"] == []
    q = normalize_quantity("tc", quantity(unit=None))
    assert q["status"] == "unresolved" and q["value"] is None


def test_ranges_bounds_and_units():
    q = normalize_quantity(
        "measurement_pressure",
        quantity("150–170 kbar", None, "kbar", "interval", 150, 170),
        condition=True,
    )
    assert (q["relation"], q["lower"], q["upper"], q["value"]) == ("interval", 15, 17, None)
    q = normalize_quantity("tc", quantity("<2000 mK", None, "mK", "lt", upper=2000))
    assert q["upper"] == 2 and q["value"] is None
    q = normalize_quantity("omega_log", quantity("30 THz", 30, "THz"))
    assert q["status"] == "unresolved"


def test_reversed_range_fails():
    value, block = fixture()
    value["results"][0]["properties"][0]["quantity"] = quantity(
        "240–232 K", None, "K", "interval", 240, 232
    )
    with pytest.raises(CandidateError, match="reversed_interval"):
        validate_candidate(value, [block])


def test_non_detection_with_sourced_upper_bound():
    text = "LaH10 at 150 GPa has no transition down to 2 K; Tc <2 K."
    value, block = fixture(text)
    row = value["results"][0]
    row["sc_outcome"] = "not_detected"
    row["sample"] = None
    row["series_point"] = None
    row["properties"] = [row["properties"][0]]
    row["properties"][0]["quantity"] = quantity("<2 K", None, "K", "lt", upper=2)
    validate_candidate(value, [block])


def test_all_sections_and_multibyte_characters_survive(tmp_path):
    text = "\n".join(f"Section {i}: LaH₁₀ μ* α β γ Tc 240 K " * 100 for i in range(12))
    path = tmp_path / "paper.txt"
    path.write_text(text)
    doc = parse_source(path, source_id="synthetic:test")
    blocks = make_blocks(doc, max_tokens=128)
    assert "".join(b["text"] for b in blocks) == text
    assert blocks[-1]["source_end"] == len(text)
    assert len(text) > 16000 and len(blocks) > 8
    assert len({b["block_id"] for b in blocks}) == len(blocks)


def test_html_tables_math_and_footnotes_remain_in_order():
    p = ArticleHTML()
    p.feed(
        '<p>A LaH10 study <math alttext="T_c=240">ignored</math>.</p><table id="t1"><tr><th>P GPa</th><th>Tc K</th></tr><tr><td>150</td><td>240</td></tr><tfoot>onset criterion</tfoot></table><p>Final section.</p>'
    )
    p.flush()
    assert "T_c=240" in p.records[0]["text"]
    assert p.records[1]["kind"] == "table"
    assert "onset criterion" in p.records[1]["text"] and "P GPa" in p.records[1]["text"]
    assert p.records[-1]["text"] == "Final section."


def test_occurrence_identity_excludes_model_and_interpreted_values():
    value, block = fixture()
    row = value["results"][0]
    changed = deepcopy(row)
    changed["local_id"] = "different-model-id"
    changed["properties"][0]["quantity"]["value"] = 999
    assert occurrence_key(row, [block]) == occurrence_key(changed, [block])


class FakeProvider:
    config = ProviderConfig("local_mlx", MODEL, REVISION)

    def __init__(self, mode="empty"):
        self.mode, self.calls = mode, 0

    def generate(self, messages):
        self.calls += 1
        if self.mode == "failure":
            raise ProviderError("synthetic_transport_error")
        if self.mode == "invalid" or self.mode == "repair" and self.calls == 1:
            return Response("not json")
        if self.mode == "split" and self.calls == 1:
            raise OutputLimit("synthetic_limit")
        return Response(
            json.dumps(
                {
                    "schema_version": "materials-ner-candidate/3.0",
                    "results": [],
                    "unresolved_links": [],
                }
            )
        )


def document(tmp_path, text="A text without superconducting claims."):
    path = tmp_path / "source.txt"
    path.write_text(text)
    return parse_source(path, source_id="synthetic:test")


@pytest.mark.parametrize(
    "mode,calls,complete",
    [
        ("empty", 1, True),
        ("repair", 2, True),
        ("invalid", 2, False),
        ("failure", 3, False),
        ("split", 3, True),
    ],
)
def test_failures_repairs_splits_and_resume(tmp_path, mode, calls, complete):
    provider = FakeProvider(mode)
    ledger = Ledger(tmp_path / "ledger.sqlite")
    pipeline = Pipeline(provider, ledger)
    doc = document(tmp_path, "No claims. " * 100 if mode == "split" else "No claims.")
    out = pipeline.run(doc, paper_id="synthetic:test", work_id="synthetic:work")
    assert provider.calls == calls
    assert out["coverage"]["machine_text_complete"] is complete
    assert pipeline.run(doc, paper_id="synthetic:test", work_id="synthetic:work") == out
    assert provider.calls == calls
    assert out["production_database_changed"] is False
    ledger.close()


def test_fenced_lease_rejects_stale_completion(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite")
    ledger.enqueue("j", "config", "input")
    one = ledger.claim("j", now=1, lease_seconds=1)
    two = ledger.claim("j", lease_seconds=60)
    assert two > one
    with pytest.raises(LeaseError, match="stale"):
        ledger.complete("j", one, {"coverage": {"machine_text_complete": True}})
    ledger.complete("j", two, {"coverage": {"machine_text_complete": True}})
    assert ledger.claim("j") is None
    ledger.close()


def test_model_outputs_cannot_be_gold():
    with pytest.raises(ValueError, match="independent_adjudicated_gold"):
        evaluate({}, {"status": "model_consensus", "annotators": []}, {})


def test_empty_denominators_are_not_perfect_scores():
    assert counts([], [])["f1"] is None
    assert (
        paired_bootstrap({}, {}, {}, [{"work_id": "w", "study_dependency_group": "g"}])["status"]
        == "insufficient_clusters"
    )


def test_cross_model_source_results_require_selection(tmp_path):
    provider = FakeProvider()
    ledger = Ledger(tmp_path / "ledger.sqlite")
    run = Pipeline(provider, ledger).run(document(tmp_path), paper_id="p", work_id="w")
    other = {**run, "job_key": "another-provider"}
    with pytest.raises(ValueError, match="explicit_selection"):
        assemble_reports([run, other], {})
    ledger.close()


def test_sampling_quotas_do_not_equal_a_frozen_corpus():
    manifest = {"papers": []}
    assert "requires_50_works" in validate_manifest(manifest)
    with pytest.raises(ValueError, match="freeze_refused"):
        freeze_manifest(manifest)
