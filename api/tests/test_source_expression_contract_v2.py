"""Finite transcription checks; all inline source text is synthetic."""

import base64
from copy import deepcopy
from hashlib import sha256

import pytest

from services import source_expression_contract_v2 as contract


def span(source, token, start=0):
    index = source.index(token, start)
    return {"start": index, "end": index + len(token), "sha256": sha256(token.encode()).hexdigest()}


def synthetic_package(source="YScH10 94.5 K at 200 GPa. Computed model X."):
    expr = {
        "field_id": "tc_kelvin",
        "subject": {"formula_spans": [span(source, "YScH10")], "sample_label_spans": []},
        "window": {"id": "synthetic-window", "label_spans": []},
        "source_role": "source_reported",
        "knowledge_origin": "Computed",
        "origin_basis": {
            "statement": "Synthetic declared method context",
            "spans": [span(source, "Computed")],
        },
        "model_spans": [span(source, "model X")],
        "value_spans": [span(source, "94.5 K")],
        "unit_spans": [],
        "conditions": [
            {
                "field_id": "pressure_gpa",
                "role": "reported_result_condition",
                "value_spans": [span(source, "200 GPa")],
                "unit_spans": [],
            }
        ],
        "locator": {k: None for k in contract.LOCATOR_KEYS},
        "predecessor": None,
    }
    return {
        "version": contract.VERSION,
        "source": {
            "source_id": "synthetic:conference",
            "url": "https://example.com/source",
            "kind": "conference_presentation",
            "content_kind": "plain_text",
            "revision": None,
            "revision_status": "unresolved",
            "original_parent_sha256": "e" * 64,
            "parent_hash_status": "declared",
            "rights_status": "unresolved",
            "currentness": "unresolved",
            "captured_at": "2026-10-02T00:00:00+00:00",
        },
        "source_text_base64": base64.b64encode(source.encode()).decode(),
        "source_content_sha256": sha256(source.encode()).hexdigest(),
        "expressions": [expr],
    }


def escaping_package(count=9):
    """Valid synthetic maximum-length strings stress nested proof escaping."""
    token = '\\"' * 600
    raw = "YScH10 94.5 K at 200 GPa. Computed model X. " + token
    p = synthetic_package(raw)
    start = raw.index(token)

    def pick(n):
        return {
            "start": start,
            "end": start + n,
            "sha256": sha256(raw[start : start + n].encode()).hexdigest(),
        }

    e = p["expressions"][0]
    e.update(field_id="method_statement", value_spans=[pick(1200)], model_spans=[pick(500)])
    e["subject"] = {"formula_spans": [pick(200)], "sample_label_spans": [pick(200)]}
    e["window"]["label_spans"] = [pick(500)]
    e["origin_basis"] = {"statement": '\\"' * 250, "spans": [pick(1000)]}
    e["conditions"] = [
        {
            "field_id": "method_statement",
            "role": "reported_result_condition",
            "value_spans": [pick(1200)],
            "unit_spans": [],
        }
        for _ in range(8)
    ]
    e["locator"] = {
        k: '\\"' * 100 if k in {"table", "section", "member"} else None for k in e["locator"]
    }
    p["source"].update(
        url="https://example.com/" + '\\"' * 1000, revision='\\"' * 80, revision_status="declared"
    )
    p["expressions"] = [deepcopy(e) for _ in range(count)]
    for i, item in enumerate(p["expressions"]):
        item["window"]["id"] = "synthetic-escaping-window-" + str(i)
    return p


def test_new_fragment_has_faithful_quantities_and_unestablished_authority():
    prepared = contract.compile_package(synthetic_package())
    p = prepared.projections[0]
    assert p["value"]["value"] == 94.5 and p["value"]["raw_value"] == "94.5 K"
    assert p["conditions"][0]["value"]["value"] == 200
    assert p["knowledge_origin"] == "Computed"
    assert p["scientific_acceptance"] is False and p["canonical_promotions"] == 0
    assert p["selected_result_association"] == "unestablished"
    assert p["origin_basis"]["verification"] == "declared_inspection_basis"


@pytest.mark.parametrize(
    "field,raw,unit,value,status",
    [
        ("tc_kelvin", "66", None, None, "unit_not_supplied"),
        ("tc_kelvin", "66", "K", 66, "parsed"),
        ("tc_kelvin", "~66 ± 2 K", None, 66, "parsed"),
        ("tc_kelvin", "66 K", "mK", None, "unit_requires_review"),
        ("pressure_gpa", "ambient pressure", None, None, "value_requires_review"),
        ("pressure_gpa", "200 MPa", None, 0.2, "parsed"),
        ("lambda_eph", "2", None, None, "unit_not_supplied"),
        ("tc_kelvin", "1e999 K", None, None, "value_requires_review"),
        ("tc_kelvin", "1e-999 K", None, None, "value_requires_review"),
        ("tc_kelvin", "66 ± -2 K", None, None, "value_requires_review"),
    ],
)
def test_finite_scalar_units_never_use_defaults(field, raw, unit, value, status):
    q = contract.quantity(raw, unit, field)
    assert q["value"] == value and q["status"] == status
    assert q["raw_value"] == raw


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p.update(actor_user_id="forged"),
        lambda p: p.update(source_content_sha256="a" * 64),
        lambda p: p["source"].update(verified=True),
        lambda p: p["source"].update(revision_status="verified"),
        lambda p: p["source"].update(parent_hash_status="verified"),
        lambda p: p["expressions"][0].update(scientific_acceptance=True),
        lambda p: p["expressions"][0].update(knowledge_origin="AI-Accepted"),
        lambda p: p["expressions"][0].update(
            value_spans=[{"start": 7, "end": 8, "sha256": "a" * 64}]
        ),
        lambda p: p["expressions"][0].update(
            value_spans=[{"start": True, "end": 8, "sha256": "a" * 64}]
        ),
        lambda p: p["expressions"][0].update(field_id="canonical_tc_max"),
        lambda p: p["source"].update(url="file:///private/source"),
        lambda p: p["source"].update(url="https://user:secret@example.com/source"),
    ],
)
def test_closed_authority_source_and_span_tamper_rejected(change):
    package = synthetic_package()
    change(package)
    with pytest.raises((contract.SourceExpressionContractError, ValueError)):
        contract.compile_package(package)


def test_windows_models_are_distinct_not_automatic_conflicts():
    package = synthetic_package()
    second = deepcopy(package["expressions"][0])
    second["window"]["id"] = "another-window"
    package["expressions"].append(second)
    prepared = contract.compile_package(package)
    assert len({p["expression_key"] for p in prepared.projections}) == 2
    package["expressions"][1]["window"]["id"] = "synthetic-window"
    with pytest.raises(contract.SourceExpressionContractError, match="distinct_expression"):
        contract.compile_package(package)


def test_split_xml_runs_keep_exact_fragment_and_printed_unit():
    raw = "<p><t>YScH</t><t>10</t></p><p><t>94.5</t><t> K</t></p><p><t>200 GPa</t></p><p><t>Computed model X</t></p>"
    p = synthetic_package()
    p["source"]["content_kind"] = "xml_text"
    p["source_text_base64"] = base64.b64encode(raw.encode()).decode()
    p["source_content_sha256"] = sha256(raw.encode()).hexdigest()
    e = p["expressions"][0]
    e["subject"]["formula_spans"] = [span(raw, "YScH"), span(raw, "10")]
    e["value_spans"] = [span(raw, "94.5")]
    e["unit_spans"] = [span(raw, "K")]
    e["conditions"][0]["value_spans"] = [span(raw, "200 GPa")]
    e["origin_basis"]["spans"] = [span(raw, "Computed")]
    e["model_spans"] = [span(raw, "model X")]
    result = contract.compile_package(p).projections[0]
    assert result["subject"]["formula"] == "YScH10" and result["value"]["value"] == 94.5
    assert result["subject"]["formula_scope"] == "declared_formula_span_assembly"


@pytest.mark.parametrize("tokens", [["9", "9"], ["4.5", "9"], ["94", "4.5"], ["9", "4.5"]])
def test_scalar_spans_never_assemble_a_different_printed_number(tokens):
    p = synthetic_package()
    raw = contract.compile_package(p).source_text
    p["expressions"][0]["value_spans"] = [span(raw, token) for token in tokens]
    with pytest.raises(contract.SourceExpressionContractError, match="contiguous"):
        contract.compile_package(p)


def test_source_statements_and_method_conditions_are_separate():
    p = synthetic_package()
    e = p["expressions"][0]
    e["field_id"] = "method_statement"
    e["value_spans"] = e["origin_basis"]["spans"]
    e["conditions"].append(
        {
            "field_id": "method_statement",
            "role": "reported_result_condition",
            "value_spans": e["origin_basis"]["spans"],
            "unit_spans": [],
        }
    )
    result = contract.compile_package(p).projections[0]
    assert result["value"]["status"] == "source_statement"
    assert result["conditions"][1]["value"]["status"] == "source_statement"


@pytest.mark.parametrize("name", ["MAX_PACKAGE_BYTES", "MAX_PROJECTION_BYTES"])
def test_canonical_utf8_byte_boundaries_are_checked_before_sql(monkeypatch, name):
    package = synthetic_package()
    prepared = contract.compile_package(package)
    payload = prepared.package if name == "MAX_PACKAGE_BYTES" else prepared.projections[0]
    from services.research_release_manifest import canonical

    bound = len(canonical(payload))
    monkeypatch.setattr(contract, name, bound)
    contract.compile_package(package)
    monkeypatch.setattr(contract, name, bound - 1)
    with pytest.raises(contract.SourceExpressionContractError, match="bounded_.*bytes"):
        contract.compile_package(package)


def test_multibyte_repeated_statement_projection_cannot_exceed_real_cap():
    source = "YScH10 94.5 K at 200 GPa. Computed model X. " + "界" * 1200
    package = synthetic_package(source)
    e = package["expressions"][0]
    e["field_id"] = "method_statement"
    e["value_spans"] = [span(source, "界" * 1200)]
    e["conditions"] = [
        {
            "field_id": "method_statement",
            "role": "reported_result_condition",
            "value_spans": [span(source, "界" * 1200)],
            "unit_spans": [],
        }
        for _ in range(8)
    ]
    with pytest.raises(contract.SourceExpressionContractError, match="bounded_projection_bytes"):
        contract.compile_package(package)


@pytest.mark.parametrize(
    "printed,selected,unit,status",
    [
        ("94.5 K", "94", "K", "value_requires_review"),
        ("-2.8 K", "2.8", "K", "value_requires_review"),
        ("1e3 K", "3", "K", "value_requires_review"),
        ("≤66 K", "66", "K", "value_requires_review"),
        ("66 ± 2 K", "66", "K", "value_requires_review"),
        ("66(5) K", "66", "K", "value_requires_review"),
        ("66 mK", "66", "K", "unit_requires_review"),
        ("66 GPa", "66", "Pa", "unit_requires_review"),
        ("66 K/GPa", "66 K", "K", "value_requires_review"),
        ("66 K^2", "66 K", "K", "value_requires_review"),
        ("6.6 ×10^3 K", "6.6", "K", "value_requires_review"),
        ("1,234 K", "1", "K", "value_requires_review"),
    ],
)
def test_partial_numeric_and_unit_tokens_preserve_raw_without_normalization(
    printed, selected, unit, status
):
    raw = "YScH10 94.5 K at 200 GPa. Computed model X. " + printed
    p = synthetic_package(raw)
    start = len(raw) - len(printed)
    e = p["expressions"][0]
    e["value_spans"] = [span(raw, selected, start)]
    e["unit_spans"] = [span(raw, unit, start)]
    if unit == "Pa":
        e["field_id"] = "pressure_gpa"
    result = contract.compile_package(p).projections[0]["value"]
    assert result["status"] == status and result["value"] is None and result["unit"] is None
    assert result["raw_value"] == selected and result["raw_unit"] == unit


def test_complete_signed_uncertain_and_inline_unit_tokens_are_retained():
    raw = "YScH10 94.5 K at 200 GPa. Computed model X. -2.8 ± 0.2 K."
    p = synthetic_package(raw)
    p["expressions"][0]["value_spans"] = [span(raw, "-2.8 ± 0.2 K")]
    result = contract.compile_package(p).projections[0]["value"]
    assert result["value"] == -2.8 and result["uncertainty"] == 0.2
    assert result["uncertainty_interpretation"] == "unspecified"


@pytest.mark.parametrize(
    "printed,selected,unit,status",
    [
        ("<t>-</t><t>2.8</t><t> K</t>", "2.8", "K", "value_requires_review"),
        ("<t>66 </t><t>m</t><t>K</t>", "66", "K", "unit_requires_review"),
        ("<t>-2.8</t><t> K</t>", "-2.8", "K", "parsed"),
    ],
)
def test_bounded_adjacent_xml_text_runs_preserve_sign_and_unit_prefix(
    printed, selected, unit, status
):
    raw = "<p>YScH10 94.5 K at 200 GPa. Computed model X.</p><p>" + printed + "</p>"
    p = synthetic_package(raw)
    p["source"]["content_kind"] = "xml_text"
    e = p["expressions"][0]
    e["value_spans"] = [span(raw, selected, raw.index(printed))]
    e["unit_spans"] = [span(raw, unit, raw.index(printed))]
    q = contract.compile_package(p).projections[0]["value"]
    assert q["status"] == status
    assert q["value"] == (-2.8 if status == "parsed" else None)
