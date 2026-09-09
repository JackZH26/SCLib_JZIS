"""Fixed synthetic local chunking measurements, not scientific or provider recall.

The historical algorithm is exact pinned repository code, executed with the
current recorded dataclasses/tokenizer runtime. It has no source locators;
missing historical coverage is unknown, never reconstructed or reported zero.
Import and report validation are stdlib-only. The guarded caller must prohibit
network before measure_chunking: an unavailable tokenizer cache is a failure.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import stat
import sys
import threading
import time
from contextlib import contextmanager
from copy import deepcopy
from importlib.metadata import version as package_version
from pathlib import Path
from types import ModuleType, SimpleNamespace

CORPUS_VERSION = "index-migration-corpus/1.0.0"
REPORT_VERSION = "index-chunking-measurement/1.0.0"
SPECS_VERSION = "index-migration-specs/1.0.0"
BASELINE_COMMIT = "44fd6ce377c89d4b4e1b78dbe082f420c33b8814"
BASELINE_SHA256 = "43ee1e764a32fd39ac3c7f13c99bf94e525a54ab11a46ad4be0ea36336435139"
BASELINE_PATH = "scripts/fixtures/index_migration_legacy_chunker_44fd6ce.py.txt"
MAX_REPORT_BYTES = 1024 * 1024
_LOCK = threading.RLock()
_CASE_IDS = ("long_sentence", "long_metadata", "ocr", "cjk", "formula", "table", "unicode_whitespace",
             "duplicate_headings", "metadata_abstract", "override_abstract", "facts_conditions", "facts_cap")
_REJECTIONS = ("size_too_small", "overlap_at_size", "invalid_unicode", "oversized_atomic_fact",
               "simulated_truncated", "simulated_missing_statistics", "simulated_unknown_truncation",
               "simulated_provider_input_limit", "simulated_wrong_dimension", "simulated_missing_vector",
               "simulated_zero_vector", "simulated_nonfinite_vector", "simulated_provider_aggregate_limit")


class CorpusError(ValueError):
    """Static codes only; source bodies are never interpolated into failures."""


def _require(value, code="invalid_corpus_report"):
    if not value:
        raise CorpusError(code)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _section(name, text, *, equation=False, table=False):
    return {"name": name, "text": text, "has_equation": equation, "has_table": table}


def _record(formula="MgB2", tc="39 K"):
    return {"formula": formula, "tc_kelvin": tc, "knowledge_origin": "Observed", "source_role": "primary",
            "result_status": "observed", "validity_status": "pending", "extractor_version": "synthetic-corpus/1.0.0", "synthetic": True}


def build_corpus():
    """Return detached fixed inputs; the function itself imports no application."""
    sources = [
        ("long_sentence", "Synthetic long sentence", [_section("Results", "word " * 1800)]),
        ("long_metadata", "Synthetic long title 测试 😀 " * 400, [_section("结果材料族" * 400, "\nNo transition down to 2 K.\r\n" * 30)]),
        ("ocr", "Synthetic OCR", [_section("Results", "A" * 15000)]),
        ("cjk", "Synthetic CJK", [_section("结果", "超导凝聚态物理材料研究" * 200)]),
        ("formula", "Synthetic equations", [_section("Equations", r"\frac{\Delta^2}{E_F}+\lambda_{ep}=\omega_{log};" * 100, equation=True)]),
        ("table", "Synthetic table", [_section("Table", "Element\tTc(K)\tP(GPa)\n" + "LaH10\t250\t170\n" * 200, table=True)]),
        ("unicode_whitespace", "Synthetic Unicode", [_section("Results", "😀𓀀🧑🏽‍🔬e\u0301\r\n\r\n  alpha\t beta  \n" * 60)]),
        ("duplicate_headings", "Synthetic repeated headings", [_section("Results", " \r\n\t "), _section("Empty", ""), _section("Results", "alpha\n\nbeta\n\ngamma")]),
    ]
    cases = [{"case_id": identifier, "mode": "sections", "title": title, "sections": sections,
              "abstract": "", "abstract_override": None, "records": []} for identifier, title, sections in sources]
    abstract = "\n\t Synthetic abstract 超导😀 long unpunctuated words " * 200
    for identifier, override in (("metadata_abstract", False), ("override_abstract", True)):
        cases.append({"case_id": identifier, "mode": "override_abstract" if override else "metadata_abstract",
            "title": "Synthetic abstract fallback", "sections": [], "abstract": "" if override else abstract,
            "abstract_override": abstract if override else "Unselected override.", "records": []})
    negative = {**_record("Nb", "< 5 K"), "result_status": "not_detected", "source_role": "cited",
        "minimum_temperature_k": "1.5 K", "pressure_gpa": "2 GPa", "magnetic_field_t": "3 T", "sample_form": "thin_film"}
    for identifier, records in (("facts_conditions", [_record(), negative]),
                                ("facts_cap", [_record("Nb", f"{index + 1} K") for index in range(42)])):
        cases.append({"case_id": identifier, "mode": "facts", "title": "Synthetic Facts title 测试 " * 200,
            "sections": [], "abstract": "", "abstract_override": None, "records": records})
    return {"version": CORPUS_VERSION, "synthetic": True, "chunk_size_tokens": 512, "chunk_overlap_tokens": 64, "cases": cases}


def migration_specs():
    """Two complete paper inventories for G1/G2, same current algorithm.

    Metadata/raw results intentionally stay fixed so old generations remain
    eligible for technical rollback. Only parsed sections and parser labels
    change; this is not evidence of a new published source version.
    """
    before, after = [], []
    for index, (formula, tc) in enumerate((("MgB2", "39 K"), ("Nb", "9.2 K")), 11):
        arxiv_id = f"2609.{index:05d}"
        item = {"paper_id": "arxiv:" + arxiv_id, "arxiv_id": arxiv_id,
            "title": f"Synthetic migration fixture {formula}", "authors": ["Synthetic Fixture"],
            "abstract": "Synthetic local index migration fixture; pending extracted records, no scientific approval.",
            "date_submitted": "2026-09-01", "parser_version": "synthetic-index-migration/1.0.0",
            "sections": [_section(name, f"Synthetic {formula} {name.lower()} retained G1 passage. No independent confirmation is established.",
                table=name == "Table") for name in (("Methods", "Results", "Table", "Discussion", "Conclusion") if index == 11 else ("Methods", "Results"))],
            "raw_records": [_record(formula, tc)]}
        before.append(item)
        updated = deepcopy(item)
        updated["parser_version"] = "synthetic-index-migration/2.0.0"
        if index == 11:
            updated["sections"] = updated["sections"][:3]
        else:
            updated["sections"][0]["text"] = "Synthetic Nb methods G2 replacement passage. This is a local fixture edit, not a publication or scientific review."
        after.append(updated)
    return {"version": SPECS_VERSION, "synthetic": True, "scientific_acceptance": False, "ml_training_approved": False,
            "chunk_size_tokens": 512, "chunk_overlap_tokens": 64, "before": before, "after": after}


@contextmanager
def _settings(modules, size=512, overlap=64):
    originals = [(module, module.get_settings) for module in modules]
    try:
        for module, _ in originals:
            module.get_settings = lambda: SimpleNamespace(chunk_size_tokens=size, chunk_overlap_tokens=overlap)
        yield
    finally:
        for module, getter in originals:
            module.get_settings = getter


@contextmanager
def _runtime():
    root = Path(__file__).resolve().parents[1]
    payload = _baseline_bytes(root)
    ingestion_root = str(root / "ingestion")
    inserted = ingestion_root not in sys.path
    if inserted:
        sys.path.insert(0, ingestion_root)
    try:
        from ingestion.chunk import chunker
        from ingestion.extract import fact_sentences
        from ingestion.models import ApsArticleMeta, PaperMetadata, ParsedPaper, Section

        from ingestion import embedding_contract

        name = "_sclib_index_migration_pinned_legacy"
        _require(name not in sys.modules, "historical_chunker_namespace_busy")
        legacy = ModuleType(name)
        sys.modules[name] = legacy
        try:
            exec(compile(payload, BASELINE_PATH, "exec"), legacy.__dict__)
            yield chunker, fact_sentences, embedding_contract, legacy, (ApsArticleMeta, PaperMetadata, ParsedPaper, Section)
        finally:
            sys.modules.pop(name, None)
    finally:
        if inserted:
            sys.path.remove(ingestion_root)


def _baseline_bytes(root):
    """Fixed source path, bounded stable no-follow read before any execution."""
    path = root / BASELINE_PATH
    _require(path.is_absolute() and 1 <= len(path.parts) <= 48 and ".." not in path.parts, "invalid_historical_chunker")
    directories = []
    try:
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
        directories.append(os.open(path.anchor, directory_flags))
        for part in path.parts[1:-1]:
            directories.append(os.open(part, directory_flags, dir_fd=directories[-1]))
        with os.fdopen(os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directories[-1]), "rb") as handle:
            before = os.fstat(handle.fileno())
            _require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= 65536, "invalid_historical_chunker")
            payload = handle.read(65537)
            after = os.fstat(handle.fileno())
            named = os.stat(path.name, dir_fd=directories[-1], follow_symlinks=False)
        fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        _require(all(getattr(before, name) == getattr(after, name) == getattr(named, name) for name in fields)
            and len(payload) == before.st_size and _sha(payload) == BASELINE_SHA256, "historical_chunker_pin_mismatch")
        for index, part in enumerate(path.parts[1:-1]):
            named = os.stat(part, dir_fd=directories[index], follow_symlinks=False)
            held = os.fstat(directories[index + 1])
            _require(stat.S_ISDIR(named.st_mode) and (named.st_dev, named.st_ino) == (held.st_dev, held.st_ino), "historical_chunker_parent_changed")
        return payload
    finally:
        for descriptor in reversed(directories):
            os.close(descriptor)


def _source_parts(case):
    if case["mode"] == "sections":
        return {f"sections/{index}": value["text"] for index, value in enumerate(case["sections"]) if value["text"]}
    if case["mode"] == "metadata_abstract":
        return {"metadata/abstract": case["abstract"]}
    if case["mode"] == "override_abstract":
        return {"abstract_override": case["abstract_override"]}
    return {}


def _coverage(case, chunks, chunker):
    parts = _source_parts(case)
    groups = {key: [] for key in parts}
    for chunk in chunks:
        locator = chunk.evidence_candidate["source_locator"]
        path = locator["section_path"]
        _require(path in groups, "unexpected_source_locator")
        groups[path].append((chunk, locator))
    characters = byte_count = 0
    for path, source in parts.items():
        end, prior_start = 0, -1
        section = case["sections"][int(path.split("/")[1])]["name"] if path.startswith("sections/") else "Abstract"
        prefix = chunker.build_bounded_prefix(case["title"], section, max_tokens=512)
        for chunk, locator in groups[path]:
            start, stop = locator["char_start"], locator["char_end"]
            _require(type(start) is int and type(stop) is int and prior_start < start <= end < stop <= len(source), "source_locator_gap_or_reversal")
            _require(chunk.text == prefix + source[start:stop], "source_slice_changed")
            _require(chunker.count_tokens(source[start:end]) <= 64, "source_overlap_exceeded")
            characters += stop - end
            byte_count += len(source[end:stop].encode("utf-8"))
            end, prior_start = stop, start
        _require(end == len(source), "source_coverage_incomplete")
    return {"scope": "parsed_source_characters", "sections": len(parts), "locator_count": len(chunks),
        "covered_characters": characters, "total_characters": sum(map(len, parts.values())),
        "covered_utf8_bytes": byte_count, "total_utf8_bytes": sum(len(part.encode()) for part in parts.values()), "complete": True}


def _measurement(case, chunks, elapsed_ns, chunker, *, historical, eligible_records=None):
    counts = [chunker.count_tokens(chunk.text) for chunk in chunks]
    facts = case["mode"] == "facts"
    if facts:
        parents = [chunk.materials_mentioned for chunk in chunks]
        _require(all(len(value) == 1 and value[0] in case["records"] for value in parents), "atomic_parent_changed")
        _require(all(chunk.evidence_candidate["parent_record"] == chunk.materials_mentioned[0] for chunk in chunks), "atomic_parent_changed")
    return {"elapsed_ns": elapsed_ns, "chunk_count": len(chunks), "full_token_total": sum(counts),
        "max_full_tokens": max(counts, default=0), "over_budget_chunks": sum(value > 512 for value in counts),
        "stored_token_count_mismatches": sum(chunk.token_count != count for chunk, count in zip(chunks, counts, strict=True)),
        "metadata_truncated_chunks": sum("[truncated]" in chunk.text.split("\n\n", 1)[0] for chunk in chunks),
        "locator_coverage": None if historical or facts else _coverage(case, chunks, chunker),
        "input_records": len(case["records"]) if facts else None, "retained_records": len(chunks) if facts else None,
        "excluded_records": len(case["records"]) - len(chunks) if facts else None,
        "eligible_records": eligible_records, "unrenderable_records": len(case["records"]) - eligible_records if facts else None,
        "cap_skipped_records": eligible_records - len(chunks) if facts else None,
        "atomic_parent_preserved": True if facts else None,
        "output_sha256": _sha(_canonical([{"id": chunk.id, "text": chunk.text, "token_count": chunk.token_count} for chunk in chunks]))}


def _canaries(chunker, facts, contract, model_types):
    ApsArticleMeta, PaperMetadata, ParsedPaper, Section = model_types
    meta = PaperMetadata(arxiv_id="2609.99999", title="Synthetic rejection canary", authors=[], abstract="", date_submitted=None, categories=[], primary_category=None)
    rejected = []
    def reject(identifier, operation, error=ValueError, *, input_count=1):
        try:
            operation()
        except error:
            embedding = identifier.startswith("simulated_")
            rejected.append({"case_id": identifier, "rejected": True, "scope": "simulated_embedding_response" if embedding else "local_input_admission",
                "input_unit": "embedding_input" if embedding else "record" if identifier == "oversized_atomic_fact" else "paper",
                "input_item_count": input_count, "rejected_item_count": input_count})
        else:
            raise CorpusError("rejection_canary_was_admitted")
    for identifier, size, overlap in (("size_too_small", 63, 0), ("overlap_at_size", 512, 512)):
        with _settings([chunker], size, overlap):
            reject(identifier, lambda: chunker.chunk_paper(ParsedPaper(meta=meta, sections=[])))
    reject("invalid_unicode", lambda: chunker.chunk_paper(ParsedPaper(meta=meta, sections=[Section("Results", "invalid\ud800")])) )
    with _settings([chunker, facts], 64, 0):
        record = {**_record("Nb", "9.2 K"), "result_status": "not_detected", "minimum_temperature_k": "1 K", "sample_form": "SYNTHETIC_SCOPE " * 8}
        reject("oversized_atomic_fact", lambda: facts.build_authorized_chunks(
            ApsArticleMeta(doi="10.0000/Synthetic.Canary", title="Synthetic", authors=[], abstract="Synthetic abstract."), [record]), facts.FactChunkLimitError)
    text = "Synthetic embedding contract input."
    count = chunker.count_tokens(text)
    options = dict(model=contract.MODEL, dimension=contract.DIMENSION, task_type="RETRIEVAL_DOCUMENT",
        local_count_method=contract.LOCAL_DOCUMENT_COUNT_METHOD, local_input_limit=contract.LOCAL_DOCUMENT_INPUT_LIMIT,
        local_request_limit=contract.LOCAL_DOCUMENT_REQUEST_LIMIT)
    valid = {"embeddings": [{"statistics": {"truncated": False, "token_count": count}, "values": [0.25] * contract.DIMENSION}]}
    good = contract.validate_embedding_response([text], valid, local_counts=[count], **options)
    _require(len(good) == 1, "valid_simulated_response_rejected")
    variants = {}
    for identifier in _REJECTIONS[4:-1]:
        variants[identifier] = deepcopy(valid)
    variants["simulated_truncated"]["embeddings"][0]["statistics"]["truncated"] = True
    variants["simulated_missing_statistics"]["embeddings"][0].pop("statistics")
    variants["simulated_unknown_truncation"]["embeddings"][0]["statistics"]["truncated"] = None
    variants["simulated_provider_input_limit"]["embeddings"][0]["statistics"]["token_count"] = 2049
    variants["simulated_wrong_dimension"]["embeddings"][0]["values"] = [0.25] * 767
    variants["simulated_missing_vector"]["embeddings"] = []
    variants["simulated_zero_vector"]["embeddings"][0]["values"] = [0.0] * 768
    variants["simulated_nonfinite_vector"]["embeddings"][0]["values"][0] = math.inf
    for identifier, response in variants.items():
        reject(identifier, lambda response=response: contract.validate_embedding_response([text], response, local_counts=[count], **options), contract.EmbeddingCompletenessError)
    aggregate = {"embeddings": [{"statistics": {"truncated": False, "token_count": 2048}, "values": [0.25] * 768} for _ in range(10)]}
    reject("simulated_provider_aggregate_limit", lambda: contract.validate_embedding_response([text] * 10, aggregate,
        local_counts=[count] * 10, **options), contract.EmbeddingCompletenessError, input_count=10)
    return {"valid_simulated_responses": 1, "provider_calls": 0, "provider_statistics_measured": False,
        "rejected_case_count": len(rejected), "rejected_input_items": sum(row["rejected_item_count"] for row in rejected), "rejections": rejected}


def measure_chunking():
    """Execute fixed current and byte-pinned old chunkers, never a supplied program."""
    corpus = build_corpus()
    try:
        with _LOCK, _runtime() as (chunker, facts, contract, legacy, model_types), _settings([chunker, facts, legacy]):
            ApsArticleMeta, PaperMetadata, ParsedPaper, Section = model_types
            measured = []
            for ordinal, case in enumerate(corpus["cases"], 1):
                before_input = deepcopy(case)
                eligible_records = None
                if case["mode"] == "facts":
                    meta = ApsArticleMeta(doi=f"10.0000/Synthetic.Corpus{ordinal}", title=case["title"], authors=[], abstract="")
                    eligible_records = sum(facts.fact_sentence(record) is not None for record in case["records"])
                    start = time.perf_counter_ns()
                    after = facts.build_fact_chunks(meta, deepcopy(case["records"]), start_index=0)
                    elapsed = time.perf_counter_ns() - start
                    prior = None
                else:
                    meta = PaperMetadata(arxiv_id=f"2609.{20000 + ordinal:05d}", title=case["title"], authors=[], abstract=case["abstract"], date_submitted=None, categories=[], primary_category=None)
                    paper = ParsedPaper(meta=meta, sections=[Section(**value) for value in case["sections"]], abstract_override=case["abstract_override"], parser_version="synthetic-index-corpus/1.0.0")
                    original = deepcopy(paper)
                    start = time.perf_counter_ns()
                    old = legacy.chunk_paper(paper)
                    old_elapsed = time.perf_counter_ns() - start
                    _require(paper == original, "historical_input_mutated")
                    prior = _measurement(case, old, old_elapsed, chunker, historical=True)
                    start = time.perf_counter_ns()
                    after = chunker.chunk_paper(paper)
                    elapsed = time.perf_counter_ns() - start
                    _require(paper == original, "current_input_mutated")
                _require(case == before_input, "corpus_input_mutated")
                current = _measurement(case, after, elapsed, chunker, historical=False, eligible_records=eligible_records)
                _require(current["over_budget_chunks"] == 0 and current["stored_token_count_mismatches"] == 0, "current_complete_text_bound_failed")
                if case["case_id"] == "facts_conditions":
                    _require(any("not detected" in item.text and "minimum test temperature = 1.5 K" in item.text
                        and "Tc =" not in item.text and "source role: cited" in item.text for item in after), "negative_fact_context_changed")
                measured.append({"case_id": case["case_id"], "mode": case["mode"], "input_sha256": _sha(_canonical(case)), "before": prior, "after": current})
            report = {"version": REPORT_VERSION, "corpus_version": CORPUS_VERSION, "corpus_sha256": _sha(_canonical(corpus)),
                "synthetic": True, "scientific_recall_measured": False, "provider_statistics_mode": "simulated_contract_fixtures",
                "baseline": {"commit": BASELINE_COMMIT, "path": BASELINE_PATH, "sha256": BASELINE_SHA256,
                             "execution": "historical_algorithm_current_runtime", "facts_compared": False},
                "runtime": {"python": platform.python_version(), "tiktoken": package_version("tiktoken"), "tokenizer": "cl100k_base"},
                "chunk_size_tokens": 512, "chunk_overlap_tokens": 64, "cases": measured,
                "canaries": _canaries(chunker, facts, contract, model_types)}
            return validate_corpus_report(report)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError, OSError, ImportError):
        raise CorpusError("chunking_measurement_unavailable") from None


def _keys(value, keys):
    _require(type(value) is dict and set(value) == set(keys))


def _integer(value, maximum=10**15):
    _require(type(value) is int and 0 <= value <= maximum)


def _hash(value):
    _require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None)


def validate_corpus_report(report):
    """Closed stdlib validation; integrity/measurements never authenticate science."""
    try:
        _keys(report, ("version", "corpus_version", "corpus_sha256", "synthetic", "scientific_recall_measured", "provider_statistics_mode",
                       "baseline", "runtime", "chunk_size_tokens", "chunk_overlap_tokens", "cases", "canaries"))
        corpus = build_corpus()
        _require(report["version"] == REPORT_VERSION and report["corpus_version"] == CORPUS_VERSION
            and report["corpus_sha256"] == _sha(_canonical(corpus)) and report["synthetic"] is True
            and report["scientific_recall_measured"] is False and report["provider_statistics_mode"] == "simulated_contract_fixtures")
        _require(report["baseline"] == {"commit": BASELINE_COMMIT, "path": BASELINE_PATH, "sha256": BASELINE_SHA256,
            "execution": "historical_algorithm_current_runtime", "facts_compared": False})
        _require(type(report["baseline"]["facts_compared"]) is bool)
        _keys(report["runtime"], ("python", "tiktoken", "tokenizer"))
        for key in ("python", "tiktoken"):
            _require(type(report["runtime"][key]) is str and re.fullmatch(r"[A-Za-z0-9.+_-]{1,80}", report["runtime"][key]))
        _require(report["runtime"]["tokenizer"] == "cl100k_base")
        _require(type(report["chunk_size_tokens"]) is int and report["chunk_size_tokens"] == 512
            and type(report["chunk_overlap_tokens"]) is int and report["chunk_overlap_tokens"] == 64)
        _require(type(report["cases"]) is list and len(report["cases"]) == len(_CASE_IDS))
        for row, case in zip(report["cases"], corpus["cases"], strict=True):
            _keys(row, ("case_id", "mode", "input_sha256", "before", "after"))
            _require(row["case_id"] == case["case_id"] and row["mode"] == case["mode"] and row["input_sha256"] == _sha(_canonical(case)))
            facts = case["mode"] == "facts"
            _require((row["before"] is None) is facts)
            for phase in ("before", "after"):
                value = row[phase]
                if value is None:
                    continue
                _keys(value, ("elapsed_ns", "chunk_count", "full_token_total", "max_full_tokens", "over_budget_chunks", "stored_token_count_mismatches",
                    "metadata_truncated_chunks", "locator_coverage", "input_records", "retained_records", "excluded_records", "eligible_records",
                    "unrenderable_records", "cap_skipped_records", "atomic_parent_preserved", "output_sha256"))
                for key in ("elapsed_ns", "chunk_count", "full_token_total", "max_full_tokens", "over_budget_chunks", "stored_token_count_mismatches", "metadata_truncated_chunks"):
                    _integer(value[key])
                _require(1 <= value["chunk_count"] <= 1000 and 1 <= value["max_full_tokens"] <= value["full_token_total"]
                    <= value["chunk_count"] * value["max_full_tokens"])
                for key in ("over_budget_chunks", "stored_token_count_mismatches", "metadata_truncated_chunks"):
                    _require(value[key] <= value["chunk_count"])
                _hash(value["output_sha256"])
                if phase == "after":
                    _require(value["over_budget_chunks"] == value["stored_token_count_mismatches"] == 0 and value["max_full_tokens"] <= 512)
                if facts:
                    for key in ("input_records", "retained_records", "excluded_records", "eligible_records", "unrenderable_records", "cap_skipped_records"):
                        _integer(value[key], 1000)
                    _require(value["input_records"] == len(case["records"]) and value["retained_records"] == value["chunk_count"]
                        and value["eligible_records"] == value["input_records"] and value["unrenderable_records"] == 0
                        and value["retained_records"] == min(40, value["eligible_records"])
                        and value["cap_skipped_records"] == value["eligible_records"] - value["retained_records"]
                        and value["input_records"] == value["retained_records"] + value["excluded_records"] and value["atomic_parent_preserved"] is True)
                else:
                    _require(all(value[key] is None for key in ("input_records", "retained_records", "excluded_records", "eligible_records",
                                                              "unrenderable_records", "cap_skipped_records", "atomic_parent_preserved")))
                coverage = value["locator_coverage"]
                if facts or phase == "before":
                    _require(coverage is None)
                else:
                    _keys(coverage, ("scope", "sections", "locator_count", "covered_characters", "total_characters", "covered_utf8_bytes", "total_utf8_bytes", "complete"))
                    parts = _source_parts(case)
                    _require(coverage["scope"] == "parsed_source_characters" and coverage["complete"] is True)
                    for key in ("sections", "locator_count", "covered_characters", "total_characters", "covered_utf8_bytes", "total_utf8_bytes"):
                        _integer(coverage[key])
                    _require(coverage["sections"] == len(parts) and coverage["locator_count"] == value["chunk_count"]
                        and coverage["covered_characters"] == coverage["total_characters"] == sum(map(len, parts.values()))
                        and coverage["covered_utf8_bytes"] == coverage["total_utf8_bytes"] == sum(len(part.encode()) for part in parts.values()))
        canaries = report["canaries"]
        _keys(canaries, ("valid_simulated_responses", "provider_calls", "provider_statistics_measured", "rejected_case_count", "rejected_input_items", "rejections"))
        _require(type(canaries["valid_simulated_responses"]) is int and canaries["valid_simulated_responses"] == 1
            and type(canaries["provider_calls"]) is int and canaries["provider_calls"] == 0 and canaries["provider_statistics_measured"] is False)
        _require(type(canaries["rejections"]) is list and len(canaries["rejections"]) == len(_REJECTIONS))
        _integer(canaries["rejected_case_count"])
        _integer(canaries["rejected_input_items"])
        _require(canaries["rejected_case_count"] == len(_REJECTIONS) and canaries["rejected_input_items"] == len(_REJECTIONS) + 9)
        for row, identifier in zip(canaries["rejections"], _REJECTIONS, strict=True):
            _keys(row, ("case_id", "rejected", "scope", "input_unit", "input_item_count", "rejected_item_count"))
            _require(row["case_id"] == identifier and row["rejected"] is True and row["scope"] == (
                "simulated_embedding_response" if identifier.startswith("simulated_") else "local_input_admission"))
            _require(row["input_unit"] == ("embedding_input" if identifier.startswith("simulated_") else
                "record" if identifier == "oversized_atomic_fact" else "paper"))
            _integer(row["input_item_count"])
            _integer(row["rejected_item_count"])
            _require(row["input_item_count"] == row["rejected_item_count"] == (10 if identifier == "simulated_provider_aggregate_limit" else 1))
        # Validate the closed bounded shape before allocating its serialized copy.
        _require(len(_canonical(report)) <= MAX_REPORT_BYTES)
        return deepcopy(report)
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError, RecursionError, UnicodeError):
        raise CorpusError("invalid_corpus_report") from None
