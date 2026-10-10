"""Cross-point, evidence, queue and batch failures discovered during pilot development."""

import json
from copy import deepcopy

import pytest

from test_materials_v3 import FakeProvider, document, fixture, quantity
from ingestion.materials_v3.assembly import assemble_reports
from ingestion.materials_v3.batch import run_batch
from ingestion.materials_v3.blocks import block_inputs, make_blocks, parse_source
from ingestion.materials_v3.comparison import atomic_claims
from ingestion.materials_v3.contract import (
    CandidateError,
    digest,
    occurrence_key,
    schema,
    source_numbers,
    validate_candidate,
)
from ingestion.materials_v3.ledger import Ledger, LeaseError
from ingestion.materials_v3.pipeline import Budget, Pipeline
from ingestion.materials_v3.providers import ResourceLimit
from ingestion.materials_v3.registry import normalize_quantity
from ingestion.materials_v3.runtime import admission


def result_run(value, block):
    validated = validate_candidate(value, [block])
    validated.update(
        block_id=block["block_id"],
        input_blocks=[block],
        occurrences=[occurrence_key(r, [block]) for r in value["results"]],
    )
    return {
        "work_id": "synthetic:work",
        "paper_id": "synthetic:paper",
        "source_sha256": block["source_sha256"],
        "job_key": "synthetic:job",
        "blocks": [block],
        "results": [validated],
        "coverage": {"machine_text_complete": True},
    }


def test_summary_keeps_onset_240_distinct_from_zero_232():
    value, block = fixture()
    run = result_run(value, block)
    out = assemble_reports([run], {f"{block['source_sha256']}:LaH10": "mat:synthetic"})
    selected = out["materials"]["mat:synthetic"]["selected_result"]
    assert selected["quantity"]["value"] == 240 and selected["criterion"] == "onset"
    claims = atomic_claims(run)
    assert [c["quantity"]["value"] for c in claims] == [240, 232]


def test_two_points_in_one_sentence_have_distinct_source_occurrences():
    value, block = fixture(
        "LaH10 sample S1 pressure scan at 150 GPa loading: Tc 240 K and at 170 GPa Tc 250 K."
    )
    one, two = value["results"][0], deepcopy(value["results"][0])
    one["properties"] = [one["properties"][0]]
    two["local_id"] = "r2"
    two["properties"] = [two["properties"][0]]
    two["properties"][0]["quantity"] = quantity("250 K", 250)
    two["conditions"][0]["quantity"] = quantity("170 GPa", 170, "GPa")
    two["series_point"]["point_label_raw"] = "170 GPa"
    assert occurrence_key(one, [block]) != occurrence_key(two, [block])
    value["results"].append(two)
    run = result_run(value, block)
    out = assemble_reports([run], {f"{block['source_sha256']}:LaH10": "mat:synthetic"})
    assert out["materials"]["mat:synthetic"]["support_counts"]["result_points"] == 2


@pytest.mark.parametrize(
    "mutate",
    [
        lambda row: row["event"].update(method_raw="Invented instrument"),
        lambda row: row["sample"].update(form_raw="Invented epitaxial film"),
        lambda row: row["series_point"].update(series_label_raw="Invented series"),
        lambda row: row["subject"].update(name_raw="Invented material"),
    ],
)
def test_raw_identity_and_method_need_their_own_source_quotes(mutate):
    value, block = fixture()
    mutate(value["results"][0])
    with pytest.raises(CandidateError, match="not_in_evidence"):
        validate_candidate(value, [block])


def test_unit_cannot_be_invented_even_when_the_number_is_present():
    value, block = fixture()
    value["results"][0]["properties"][0]["quantity"]["raw_unit"] = "mK"
    with pytest.raises(CandidateError, match="raw_unit_not_in_evidence"):
        validate_candidate(value, [block])


@pytest.mark.parametrize(
    "raw,expected",
    [("5 × 10^5 A/cm²", 500000), ("1.2 × 10⁻³", 0.0012), ("150-170 GPa", 170), ("2.5e-2", 0.025)],
)
def test_source_scientific_notation_is_read_without_evaluation(raw, expected):
    assert expected in source_numbers(raw)


def test_unit_conversion_overflow_is_unresolved():
    q = normalize_quantity("critical_current_density", quantity("1e308 MA/cm2", 1e308, "MA/cm2"))
    assert q["status"] == "unresolved" and q["value"] is None


def test_dimensionless_definition_does_not_supply_missing_temperature_units():
    q = normalize_quantity("coulomb_mu_star", quantity("0.1", 0.1, None))
    assert q["status"] == "normalized" and q["unit"] == "1"
    assert normalize_quantity("tc", quantity("240", 240, None))["status"] == "unresolved"


def test_long_table_fragments_receive_exact_beginning_and_ending_context(tmp_path):
    table = (
        "<table><tr><th>Pressure GPa</th><th>Tc K</th></tr>"
        + "".join(f"<tr><td>{i}</td><td>{i + 100}</td></tr>" for i in range(300))
        + "<tfoot>All Tc values are resistive onset.</tfoot></table>"
    )
    path = tmp_path / "table.html"
    path.write_text(table)
    doc = parse_source(path, source_id="synthetic:table")
    blocks = make_blocks(doc, max_tokens=128)
    inputs = block_inputs(blocks[len(blocks) // 2], doc)
    assert any("Pressure GPa" in b["text"] for b in inputs[1:])
    assert any("resistive onset" in b["text"] for b in inputs[1:])
    source = "\n".join(r["text"] for r in doc["records"])
    assert all(source[b["source_start"] : b["source_end"]] == b["text"] for b in inputs)


def test_context_only_result_is_rejected():
    value, block = fixture()
    context = {**block, "block_role": "context"}
    target = {
        **block,
        "block_id": "b-other",
        "text": "No result in this target.",
        "block_role": "target",
    }
    with pytest.raises(CandidateError, match="context_only"):
        validate_candidate(value, [target, context])


def test_independent_connection_reclaim_fences_all_old_writes(tmp_path):
    path = tmp_path / "ledger.sqlite"
    first, second = Ledger(path), Ledger(path)
    first.enqueue("j", "c", "i")
    old = first.claim("j", now=1, lease_seconds=1)
    current = second.claim("j", lease_seconds=60)
    for call in (
        lambda: first.heartbeat("j", old),
        lambda: first.record_attempt("j", old, "b", "validated", {}),
        lambda: first.put_block("j", old, {"block_id": "b"}, "empty", {}),
    ):
        with pytest.raises(LeaseError, match="stale"):
            call()
    second.complete("j", current, {"coverage": {"machine_text_complete": True}})
    first.close()
    second.close()


def test_resource_failure_is_not_retried_as_transport_failure(tmp_path):
    class Exhausted(FakeProvider):
        def generate(self, messages):
            self.calls += 1
            raise ResourceLimit("synthetic_memory_limit")

    provider, ledger = Exhausted(), Ledger(tmp_path / "ledger.sqlite")
    out = Pipeline(provider, ledger, budget=Budget(max_tokens_per_block=128)).run(
        document(tmp_path, "No target claim. " * 1000), paper_id="p", work_id="w"
    )
    assert provider.calls == 1 and not out["coverage"]["machine_text_complete"]
    assert out["attempts"][0]["status"] == "resource_exhausted"
    assert len(out["blocks"]) > 1 and set(out["terminal"].values()) == {"resource_exhausted"}
    ledger.close()


def test_unfrozen_blind_batch_fails_before_loading_or_generating(tmp_path):
    provider, ledger = FakeProvider(), Ledger(tmp_path / "ledger.sqlite")
    with pytest.raises(ValueError, match="frozen_manifest"):
        run_batch(
            {"papers": []},
            provider,
            ledger,
            split="blind_test",
            load_document=lambda p: None,
            publish=lambda p, r: None,
        )
    assert provider.calls == 0
    ledger.close()


def test_batch_reuses_provider_and_checkpoints_two_distinct_sources(tmp_path):
    provider, ledger = FakeProvider(), Ledger(tmp_path / "ledger.sqlite")
    docs = [document(tmp_path, text="No target claim. " + str(i)) for i in range(2)]
    papers = [
        {
            "paper_id": str(i),
            "work_id": "w" + str(i),
            "split": "development",
            "main_text_sha256": d["source_sha256"],
            "content_manifest_sha256": d["manifest_sha256"],
        }
        for i, d in enumerate(docs)
    ]
    manifest = {"papers": papers, "manifest_sha256": "synthetic-unfrozen-development"}
    args = dict(
        split="development",
        load_document=lambda p: docs[int(p["paper_id"])],
        publish=lambda p, r: r["job_key"],
    )
    one = run_batch(manifest, provider, ledger, **args)
    two = run_batch(manifest, provider, ledger, **args)
    assert one == two and len(one["outputs"]) == provider.calls == 2
    ledger.close()


def test_mini_admission_uses_new_9b_profile_without_relaxing_old_35b_profile():
    base = {
        "supported": True,
        "total_memory_bytes": 48 * 1024**3,
        "reclaimable_memory_estimate_bytes": 26 * 1024**3,
    }
    admission(base)
    with pytest.raises(ValueError, match="headroom"):
        admission({**base, "reclaimable_memory_estimate_bytes": 19 * 1024**3})
    with pytest.raises(ValueError, match="headroom"):
        admission(base, budget_gib=32, headroom_gib=12, expected_peak_gib=24)
    admission(
        {**base, "reclaimable_memory_estimate_bytes": 38 * 1024**3},
        budget_gib=32,
        headroom_gib=12,
        expected_peak_gib=24,
    )


def test_documented_and_packaged_schemas_are_identical():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    documented = json.loads(
        (root / "docs/schemas/materials-ner-candidate-v3.0.schema.json").read_bytes()
    )
    assert digest(documented) == digest(schema())


def test_equation_layout_tables_pack_as_text_and_nested_data_tables_stay_atomic(tmp_path):
    path = tmp_path / "paper.html"
    path.write_text(
        '<p>Introduction.</p><table class="ltx_equation"><tr><td><math alttext="T_c=240 K">ignore</math></td></tr></table>'
        '<p>Methods.</p><table class="ltx_tabular"><tr><th>P GPa</th><td><table><tr><td>150</td></tr></table></td></tr><tfoot>onset</tfoot></table><p>Conclusion.</p>'
    )
    doc = parse_source(path, source_id="synthetic:equation")
    tables = [r for r in doc["records"] if r["kind"] == "table"]
    assert len(tables) == 1 and all(t in tables[0]["text"] for t in ("P GPa", "150", "onset"))
    blocks = make_blocks(doc)
    assert len(blocks) == 3 and "T_c=240 K" in blocks[0]["text"] and "Methods." in blocks[0]["text"]


def test_scientific_coefficient_and_exponent_are_not_quantity_witnesses():
    assert source_numbers("1.2 × 10^-3") == [0.0012]
    assert source_numbers("5 \\times 10^{5} A/cm²") == [500000]
    assert source_numbers("1.2 × 1000") == [1.2, 1000]


def test_condition_order_and_unit_spellings_do_not_change_semantic_scoring():
    value, block = fixture(
        "LaH10 sample S1 pressure scan at 150 GPa (1500 kbar) loading under 10 T: onset Tc 240 K; zero Tc 232 K."
    )
    field = deepcopy(value["results"][0]["conditions"][0])
    field.update(key="magnetic_field", quantity=quantity("10 T", 10, "T"))
    value["results"][0]["conditions"].append(field)
    changed = deepcopy(value)
    changed["results"][0]["conditions"][0]["quantity"] = quantity("1500 kbar", 1500, "kbar")
    changed["results"][0]["conditions"].reverse()
    assert atomic_claims(result_run(value, block)) == atomic_claims(result_run(changed, block))


def test_openai_length_failure_retains_raw_text_and_all_usage(monkeypatch):
    import httpx
    from ingestion.materials_v3.providers import HTTPProvider, OutputLimit, ProviderConfig

    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-key")
    body = {
        "id": "synthetic-response",
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": '{"results":['}]}
        ],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 4096,
            "output_tokens_details": {"reasoning_tokens": 12},
            "input_tokens_details": {"cached_tokens": 20},
        },
    }
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    ) as client:
        provider = HTTPProvider(ProviderConfig("openai", "gpt-6.1-sol"), client=client)
        with pytest.raises(OutputLimit) as error:
            provider.generate([])
    receipt = error.value.receipt
    assert (
        receipt.text,
        receipt.input_tokens,
        receipt.output_tokens,
        receipt.reasoning_tokens,
        receipt.cached_tokens,
    ) == ('{"results":[', 100, 4096, 12, 20)
    assert receipt.finish_reason == "length"


@pytest.mark.parametrize("finish", ["stop", "length"])
def test_mlx_uses_terminal_metadata_and_preserves_truncated_receipt(monkeypatch, finish):
    import sys
    from types import SimpleNamespace
    from ingestion.materials_v3.providers import MLXProvider, OutputLimit, Response

    core = SimpleNamespace(get_peak_memory=lambda: 1234)

    def stream(*args, **kwargs):
        assert kwargs["prefill_step_size"] == 512
        kwargs["prompt_progress_callback"](0, 3)
        yield SimpleNamespace(text="{", generation_tokens=1, finish_reason=None)
        yield SimpleNamespace(text="}", generation_tokens=2, finish_reason=finish)

    for name, module in {
        "mlx": SimpleNamespace(core=core),
        "mlx.core": core,
        "mlx_lm": SimpleNamespace(stream_generate=stream),
        "mlx_lm.sample_utils": SimpleNamespace(make_sampler=lambda **_: None),
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    provider = MLXProvider.__new__(MLXProvider)
    provider.config = FakeProvider.config.__class__(
        **{**FakeProvider.config.__dict__, "max_output_tokens": 2}
    )
    provider.model, provider.guard = None, lambda: None
    provider.tokenizer = SimpleNamespace(
        apply_chat_template=lambda *args, **kwargs: "prompt", encode=lambda _: [1, 2, 3]
    )
    if finish == "length":
        with pytest.raises(OutputLimit) as error:
            provider.generate([])
        receipt = error.value.receipt
    else:
        receipt = provider.generate([])
    assert isinstance(receipt, Response) and receipt.text == "{}" and receipt.output_tokens == 2
    assert receipt.finish_reason == finish


@pytest.mark.parametrize("model,modern", [("gemini-3.5-flash", True), ("gemini-2.5-flash", False)])
def test_gemini_reads_existing_project_setting_and_uses_model_specific_thinking(
    monkeypatch, model, modern
):
    from types import SimpleNamespace
    from google import genai
    from ingestion.materials_v3.providers import HTTPProvider, ProviderConfig

    for key in ("GCP_PROJECT_ID", "GOOGLE_CLOUD_PROJECT"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GCP_PROJECT", "synthetic-existing-project")
    captured = {}

    class Client:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.models = self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def generate_content(self, **kwargs):
            captured["generation"] = kwargs
            return SimpleNamespace(
                text="{}",
                candidates=[],
                model_version="synthetic-returned-model",
                usage_metadata=SimpleNamespace(
                    prompt_token_count=12,
                    candidates_token_count=2,
                    thoughts_token_count=3,
                    cached_content_token_count=0,
                ),
            )

    monkeypatch.setattr(genai, "Client", Client)
    provider = HTTPProvider(ProviderConfig("gemini", model))
    try:
        result = provider.generate(
            [{"content": "synthetic system"}, {"content": "synthetic input"}]
        )
    finally:
        provider.client.close()
    assert captured["project"] == "synthetic-existing-project"
    config = captured["generation"]["config"]
    if modern:
        assert str(config.thinking_config.thinking_level).endswith("LOW")
        assert config.thinking_config.thinking_budget is None and config.temperature is None
    else:
        assert config.thinking_config.thinking_budget == 0 and config.temperature == 0
    assert result.reasoning_tokens == 3
    assert result.metadata["actual_model"] == "synthetic-returned-model"


def test_model_snapshot_rejects_missing_files_before_loading(tmp_path):
    from ingestion.materials_v3.providers import MODEL, REVISION
    from ingestion.materials_v3.runtime import model_pin, verify_model

    pin = model_pin()
    assert pin["weights_bytes"] == 5950221072
    manifest = tmp_path / "model-manifest.json"
    manifest.write_text(
        json.dumps({"model_id": MODEL, "revision": REVISION, "files": pin["files"][:-1]})
    )
    with pytest.raises(ValueError, match="incomplete"):
        verify_model(tmp_path, manifest, REVISION)


def test_correct_value_anchors_ignore_raw_quantity_quote_width():
    value, block = fixture()
    changed = deepcopy(value)
    changed["results"][0]["properties"][0]["quantity"]["raw_text"] = "240"
    assert (
        atomic_claims(result_run(value, block))[0]["point"]
        == atomic_claims(result_run(changed, block))[0]["point"]
    )


@pytest.mark.parametrize("mode,expected", [("empty", 1), ("invalid", 2), ("failure", 3)])
def test_crash_after_attempt_receipt_preserves_success_and_retry_budget(
    tmp_path, monkeypatch, mode, expected
):
    provider, ledger = FakeProvider(mode), Ledger(tmp_path / "ledger.sqlite")
    pipeline, doc = Pipeline(provider, ledger), document(tmp_path)
    original = ledger.put_block

    def crash(*args, **kwargs):
        raise RuntimeError("synthetic crash between attempt fsync and block fsync")

    monkeypatch.setattr(ledger, "put_block", crash)
    with pytest.raises(RuntimeError, match="synthetic crash"):
        pipeline.run(doc, paper_id="p", work_id="w")
    assert provider.calls == expected
    monkeypatch.setattr(ledger, "put_block", original)
    ledger.db.execute("UPDATE jobs SET expires=0 WHERE status='running'")
    ledger.db.commit()
    run = pipeline.run(doc, paper_id="p", work_id="w")
    assert provider.calls == expected and len(run["attempts"]) == expected
    assert run["coverage"]["machine_text_complete"] is (mode == "empty")
    ledger.close()


@pytest.mark.parametrize("mode", ["length", "resource"])
def test_crash_after_limit_receipt_does_not_repeat_the_failed_parent(tmp_path, monkeypatch, mode):
    from ingestion.materials_v3.providers import OutputLimit

    class Limited(FakeProvider):
        def generate(self, messages):
            if self.calls == 0:
                self.calls += 1
                raise (
                    OutputLimit("synthetic_length")
                    if mode == "length"
                    else ResourceLimit("synthetic_memory")
                )
            return super().generate(messages)

    provider, ledger = Limited(), Ledger(tmp_path / "ledger.sqlite")
    pipeline, doc = Pipeline(provider, ledger), document(tmp_path, "No target claim. " * 100)
    original = ledger.put_block

    def crash(*args, **kwargs):
        raise RuntimeError("synthetic crash after limit receipt")

    monkeypatch.setattr(ledger, "put_block", crash)
    with pytest.raises(RuntimeError, match="synthetic crash"):
        pipeline.run(doc, paper_id="p", work_id="w")
    assert provider.calls == 1
    monkeypatch.setattr(ledger, "put_block", original)
    ledger.db.execute("UPDATE jobs SET expires=0 WHERE status='running'")
    ledger.db.commit()
    run = pipeline.run(doc, paper_id="p", work_id="w")
    assert provider.calls == (3 if mode == "length" else 1)
    assert len(run["attempts"]) == provider.calls
    assert run["coverage"]["machine_text_complete"] is (mode == "length")
    ledger.close()
