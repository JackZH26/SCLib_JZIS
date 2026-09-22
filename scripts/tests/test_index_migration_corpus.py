"""Offline synthetic coverage measurements, never provider/scientific gold."""
from __future__ import annotations

import hashlib
import json
import os
import socket
import stat
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import index_migration_corpus as corpus


@pytest.fixture(scope="module")
def measured():
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden in local corpus measurement")), \
         patch.object(socket.socket, "connect_ex", side_effect=AssertionError("Network forbidden in local corpus measurement")):
        return corpus.measure_chunking()


def test_fixed_corpus_detaches_and_has_all_explicit_boundaries():
    value = corpus.build_corpus()
    assert [row["case_id"] for row in value["cases"]] == list(corpus._CASE_IDS)
    value["cases"][0]["sections"][0]["text"] = "mutated"
    assert corpus.build_corpus()["cases"][0]["sections"][0]["text"] != "mutated"
    assert len(corpus.build_corpus()["cases"][-1]["records"]) == 42


def test_historical_bytes_are_exact_approved_repository_blob():
    path = ROOT / corpus.BASELINE_PATH
    assert hashlib.sha256(path.read_bytes()).hexdigest() == corpus.BASELINE_SHA256
    result = subprocess.run(["git", "show", f"{corpus.BASELINE_COMMIT}:ingestion/ingestion/chunk/chunker.py"],
                            cwd=ROOT, capture_output=True, check=True)
    assert result.stdout == path.read_bytes()


def test_complete_source_locators_and_full_text_counts_are_measured(measured):
    assert corpus.validate_corpus_report(measured) == measured
    originals = [row for row in measured["cases"] if row["mode"] != "facts"]
    assert len(originals) == 10
    for row in originals:
        current, old = row["after"], row["before"]
        assert current["locator_coverage"]["complete"] is True
        assert current["locator_coverage"]["covered_utf8_bytes"] == current["locator_coverage"]["total_utf8_bytes"]
        assert current["over_budget_chunks"] == current["stored_token_count_mismatches"] == 0
        assert current["max_full_tokens"] <= 512
        assert old["locator_coverage"] is None
    by_id = {row["case_id"]: row for row in originals}
    for identifier in ("long_sentence", "long_metadata", "ocr", "cjk", "formula", "table", "metadata_abstract", "override_abstract"):
        assert by_id[identifier]["before"]["over_budget_chunks"] > 0
    assert by_id["long_metadata"]["after"]["metadata_truncated_chunks"] > 0
    assert by_id["duplicate_headings"]["after"]["locator_coverage"]["sections"] == 2


def test_facts_have_exact_parents_and_explicit_cap_exclusion_not_claimed_complete(measured):
    facts = {row["case_id"]: row for row in measured["cases"] if row["mode"] == "facts"}
    for row in facts.values():
        assert row["before"] is None
        assert row["after"]["locator_coverage"] is None
        assert row["after"]["atomic_parent_preserved"] is True
    assert facts["facts_conditions"]["after"]["input_records"] == 2
    assert facts["facts_conditions"]["after"]["retained_records"] == 2
    assert facts["facts_cap"]["after"]["input_records"] == 42
    assert facts["facts_cap"]["after"]["retained_records"] == 40
    assert facts["facts_cap"]["after"]["excluded_records"] == 2
    assert facts["facts_cap"]["after"]["eligible_records"] == 42
    assert facts["facts_cap"]["after"]["cap_skipped_records"] == 2
    assert facts["facts_cap"]["after"]["unrenderable_records"] == 0


def test_canaries_distinguish_local_tokens_from_simulated_provider_statistics(measured):
    values = measured["canaries"]
    assert values["valid_simulated_responses"] == 1
    assert values["provider_calls"] == 0 and values["provider_statistics_measured"] is False
    assert len(values["rejections"]) == 13
    assert values["rejected_case_count"] == 13 and values["rejected_input_items"] == 22
    aggregate = values["rejections"][-1]
    assert aggregate["input_unit"] == "embedding_input"
    assert aggregate["input_item_count"] == aggregate["rejected_item_count"] == 10
    assert all(row["rejected"] is True for row in values["rejections"])
    assert {row["scope"] for row in values["rejections"]} == {"local_input_admission", "simulated_embedding_response"}
    assert measured["scientific_recall_measured"] is False


def test_measurement_restores_settings_and_leaves_no_baseline_namespace(measured):
    from ingestion.chunk import chunker
    from ingestion.config import get_settings
    from ingestion.extract import fact_sentences
    assert chunker.get_settings is get_settings and fact_sentences.get_settings is get_settings
    assert "_sclib_index_migration_pinned_legacy" not in sys.modules


def test_settings_shim_restores_on_error():
    from types import SimpleNamespace
    original = lambda: "original"
    module = SimpleNamespace(get_settings=original)
    with pytest.raises(RuntimeError):
        with corpus._settings([module], 64, 0):
            assert module.get_settings().chunk_size_tokens == 64
            raise RuntimeError("synthetic")
    assert module.get_settings is original


def test_two_paper_complete_generations_have_stable_metadata_and_real_chunk_counts(measured):
    from datetime import date

    from ingestion.chunk import chunker
    from ingestion.models import PaperMetadata, ParsedPaper, Section
    specs = corpus.migration_specs()
    assert len(specs["before"]) == len(specs["after"]) == 2
    counts = []
    with corpus._settings([chunker]):
        for phase in ("before", "after"):
            chunks = []
            for row in specs[phase]:
                meta = PaperMetadata(arxiv_id=row["arxiv_id"], title=row["title"], authors=row["authors"], abstract=row["abstract"],
                    date_submitted=date.fromisoformat(row["date_submitted"]), categories=[], primary_category=None)
                values = chunker.chunk_paper(ParsedPaper(meta=meta, sections=[Section(**section) for section in row["sections"]], parser_version=row["parser_version"]))
                assert all(value.paper_id == row["paper_id"] for value in values)
                chunks.extend(values)
            counts.append(len(chunks))
    assert counts == [7, 5]
    for before, after in zip(specs["before"], specs["after"], strict=True):
        assert {key: value for key, value in before.items() if key not in {"sections", "parser_version"}} == {
            key: value for key, value in after.items() if key not in {"sections", "parser_version"}}
    assert specs["before"][1]["sections"][0]["text"] != specs["after"][1]["sections"][0]["text"]
    assert specs["before"][1]["sections"][1] == specs["after"][1]["sections"][1]
    specs["before"][0]["raw_records"][0]["tc_kelvin"] = "changed"
    assert corpus.migration_specs()["before"][0]["raw_records"][0]["tc_kelvin"] == "39 K"


@pytest.mark.parametrize("path,value", [
    (("version",), "future"), (("synthetic",), 1), (("scientific_recall_measured",), True),
    (("provider_statistics_mode",), "real_provider"), (("corpus_sha256",), "0" * 64),
    (("baseline", "sha256"), "0" * 64), (("baseline", "facts_compared"), 0),
    (("baseline", "execution"), "historical_environment_reproduced"),
    (("chunk_size_tokens",), True), (("runtime", "tokenizer"), "another_tokenizer"),
    (("cases", 0, "input_sha256"), "0" * 64), (("cases", 0, "after", "elapsed_ns"), True),
    (("cases", 0, "after", "max_full_tokens"), 513), (("cases", 0, "after", "over_budget_chunks"), 1),
    (("cases", 0, "after", "locator_coverage", "complete"), 1),
    (("cases", 0, "after", "locator_coverage", "covered_characters"), 0),
    (("cases", 0, "before", "locator_coverage"), {}),
    (("cases", 11, "after", "excluded_records"), 0),
    (("cases", 11, "after", "eligible_records"), 40), (("cases", 11, "after", "cap_skipped_records"), 0),
    (("cases", 11, "after", "unrenderable_records"), 2),
    (("canaries", "provider_calls"), False), (("canaries", "provider_statistics_measured"), True),
    (("canaries", "rejected_input_items"), 13), (("canaries", "rejections", 12, "rejected_item_count"), 1),
    (("canaries", "rejections", 12, "input_item_count"), True),
    (("canaries", "rejections", 0, "rejected"), False),
])
def test_closed_report_rejects_repinning_false_coverage_and_authority(measured, path, value):
    changed = deepcopy(measured)
    target = changed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(corpus.CorpusError, match="invalid_corpus_report"):
        corpus.validate_corpus_report(changed)


@pytest.mark.parametrize("change", ["extra", "missing", "duplicate_case", "nonfinite", "oversize", "deep"])
def test_complete_inventory_and_bounded_json_are_required(measured, change):
    value = deepcopy(measured)
    if change == "extra": value["cases"][0]["after"]["private_raw_text"] = "canary"
    if change == "missing": value["cases"].pop()
    if change == "duplicate_case": value["cases"][1] = value["cases"][0]
    if change == "nonfinite": value["cases"][0]["after"]["elapsed_ns"] = float("nan")
    if change == "oversize": value["extra"] = "x" * corpus.MAX_REPORT_BYTES
    if change == "deep":
        target = value
        for _ in range(1200): target["extra"] = {}; target = target["extra"]
    with pytest.raises(corpus.CorpusError):
        corpus.validate_corpus_report(value)


def test_import_and_report_validation_do_not_import_application_or_touch_network(measured):
    code = '''import sys,json,importlib.abc
class Guard(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'ingestion','tiktoken','sqlalchemy','google','redis','asyncpg'}: raise RuntimeError('application import forbidden')
sys.meta_path.insert(0,Guard())
sys.path.insert(0,'scripts')
import index_migration_corpus as c
result=c.validate_corpus_report(json.loads(sys.stdin.read()))
assert c.build_corpus()['synthetic'] is True
assert c.migration_specs()['synthetic'] is True
print(result['version'])
'''
    result = subprocess.run([sys.executable, "-I", "-c", code], cwd=ROOT, input=json.dumps(measured),
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == corpus.REPORT_VERSION


def test_validator_returns_detached_copy(measured):
    value = corpus.validate_corpus_report(measured)
    value["cases"][0]["after"]["chunk_count"] = 0
    assert measured["cases"][0]["after"]["chunk_count"] > 0


@pytest.mark.parametrize("kind", ["wrong_bytes", "oversize", "leaf_symlink", "parent_symlink", "fifo"])
def test_pinned_baseline_refuses_changed_or_nonregular_source_before_execution(tmp_path, kind):
    root = tmp_path.resolve()
    path = root / corpus.BASELINE_PATH
    path.parent.mkdir(parents=True)
    if kind == "wrong_bytes": path.write_bytes(b"raise RuntimeError('must never execute')\n")
    if kind == "oversize": path.write_bytes(b"x" * 65537)
    if kind == "leaf_symlink":
        (root / "actual").write_bytes((ROOT / corpus.BASELINE_PATH).read_bytes())
        path.symlink_to(root / "actual")
    if kind == "parent_symlink":
        path.parent.rmdir()
        (root / "actual").mkdir()
        (root / "actual" / path.name).write_bytes((ROOT / corpus.BASELINE_PATH).read_bytes())
        path.parent.symlink_to(root / "actual", target_is_directory=True)
    if kind == "fifo": os.mkfifo(path)
    with pytest.raises((corpus.CorpusError, OSError)):
        corpus._baseline_bytes(root)
    assert "_sclib_index_migration_pinned_legacy" not in sys.modules


@pytest.mark.parametrize("change", ["atime_only", "mtime_changed"])
def test_baseline_stat_stability_ignores_read_atime_but_refuses_modification(monkeypatch, change):
    from types import SimpleNamespace
    original = os.fstat
    observed = 0
    def fstat(fd):
        nonlocal observed
        info = original(fd)
        if not stat.S_ISREG(info.st_mode): return info
        observed += 1
        fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns", "st_atime_ns")
        value = {name: getattr(info, name) for name in fields}
        value["st_atime_ns"] += observed
        if change == "mtime_changed" and observed > 1: value["st_mtime_ns"] += 1
        return SimpleNamespace(**value)
    monkeypatch.setattr(os, "fstat", fstat)
    if change == "atime_only":
        assert hashlib.sha256(corpus._baseline_bytes(ROOT)).hexdigest() == corpus.BASELINE_SHA256
    else:
        with pytest.raises(corpus.CorpusError, match="historical_chunker_pin_mismatch"):
            corpus._baseline_bytes(ROOT)


def test_baseline_rejection_closes_all_owned_descriptors(monkeypatch):
    opened = []
    original = os.open
    def open_fd(*args, **kwargs):
        descriptor = original(*args, **kwargs)
        opened.append(descriptor)
        return descriptor
    monkeypatch.setattr(os, "open", open_fd)
    monkeypatch.setattr(corpus, "BASELINE_SHA256", "0" * 64)
    with pytest.raises(corpus.CorpusError): corpus._baseline_bytes(ROOT)
    assert opened
    for descriptor in opened:
        with pytest.raises(OSError): os.fstat(descriptor)
