"""Offline hard-bound and exact parsed-source coverage regressions."""
from __future__ import annotations

import random
from copy import deepcopy
from types import SimpleNamespace

import pytest
import tiktoken

from ingestion.chunk import chunker
from ingestion.models import PaperMetadata, ParsedPaper, Section
from ingestion.rag_evidence_contract import validate_candidate

ENCODER = tiktoken.get_encoding("cl100k_base")


def _paper(text: str, *, title="Synthetic", section="Results") -> ParsedPaper:
    meta = PaperMetadata(arxiv_id="2609.00001", title=title, authors=[], abstract="",
                         date_submitted=None, categories=[], primary_category=None)
    return ParsedPaper(meta=meta, sections=[Section(section, text, True, True)])


def _settings(monkeypatch, size=512, overlap=64):
    monkeypatch.setattr(chunker, "get_settings", lambda: SimpleNamespace(
        chunk_size_tokens=size, chunk_overlap_tokens=overlap,
    ))


def _assert_source(chunks, source, *, title="Synthetic", section="Results",
                   path="sections/0", size=512, overlap=64, kind="original_passage"):
    prefix = chunker.build_bounded_prefix(title, section, max_tokens=size)
    selected = [chunk for chunk in chunks
                if chunk.evidence_candidate["source_locator"]["section_path"] == path]
    assert selected
    covered_end, prior_start = 0, -1
    recovered = []
    for chunk in selected:
        candidate = validate_candidate(chunk.evidence_candidate)
        locator = candidate["source_locator"]
        start, end = locator["char_start"], locator["char_end"]
        assert 0 <= start < end <= len(source)
        assert prior_start < start <= covered_end < end
        assert len(ENCODER.encode(source[start:covered_end], disallowed_special=())) <= overlap
        assert chunk.text.startswith(prefix)
        body = chunk.text[len(prefix):]
        assert body == source[start:end]
        assert body.encode("utf-8") == source[start:end].encode("utf-8")
        actual = len(ENCODER.encode(chunk.text, disallowed_special=()))
        assert chunk.token_count == actual <= size
        assert candidate["chunk_kind"] == kind
        assert candidate["rendering_version"] == chunker.CHUNKER_VERSION
        assert candidate["source_capture_id"] is None
        assert candidate["permission_status"] == "unresolved"
        assert candidate["unresolved_reason"] == "original_binding_unreviewed"
        recovered.append(body[covered_end - start:])
        covered_end, prior_start = end, start
    assert covered_end == len(source)
    assert "".join(recovered).encode("utf-8") == source.encode("utf-8")
    return selected


@pytest.mark.parametrize("text", [
    "word " * 1800,
    "A" * 15000,
    "超导凝聚态物理材料研究" * 350,
    r"\\frac{\\Delta^2}{E_{F}}+\\lambda_{ep}=\\omega_{log};" * 300,
    "Element\tTc (K)\tP (GPa)\n" + "LaH10\t250\t170\n" * 500,
    "\t  alpha\r\n\r\n beta\n \n\t gamma  \n" * 150,
    "😀𓀀🧑🏽‍🔬e\u0301\r\n" * 500,
], ids=["single-sentence", "ocr", "cjk", "formula", "table", "whitespace", "unicode"])
def test_every_complete_chunk_is_bounded_and_every_source_character_is_retained(monkeypatch, text):
    _settings(monkeypatch)
    parsed = _paper(text)
    before = deepcopy(parsed)
    chunks = chunker.chunk_paper(parsed)
    assert len(chunks) > 1
    _assert_source(chunks, text)
    assert parsed == before
    assert all(chunk.has_equation and chunk.has_table for chunk in chunks)
    assert [chunk.id for chunk in chunks] == [
        f"{parsed.meta.paper_id}_chunk_{index:03d}" for index in range(len(chunks))
    ]
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert all("�" not in chunk.text for chunk in chunks)


@pytest.mark.parametrize("size,overlap", [(64, 0), (64, 1), (64, 63), (128, 64), (512, 511)])
def test_overlap_is_a_unicode_safe_maximum_with_new_source_progress(monkeypatch, size, overlap):
    _settings(monkeypatch, size, overlap)
    source = "  HgBa2Ca2Cu3O8.\n\n超导😀𓀀 material not detected below 2 K.\t" * 30
    chunks = chunker.chunk_paper(_paper(source))
    _assert_source(chunks, source, size=size, overlap=overlap)
    assert len(chunks) <= len(source)


@pytest.mark.parametrize("size", [64, 128, 512])
def test_extreme_title_and_heading_prefixes_are_disclosed_not_source_mutations(monkeypatch, size):
    _settings(monkeypatch, size, 0)
    title = "Unicode 😀 title and superconductivity " * 1000
    heading = "结果𓀀材料族" * 1000
    source = "\nMeasured no transition down to 2 K.\r\n" * 20
    parsed = _paper(source, title=title, section=heading)
    before = deepcopy(parsed)
    chunks = chunker.chunk_paper(parsed)
    _assert_source(chunks, source, title=title, section=heading, size=size, overlap=0)
    prefix = chunker.build_bounded_prefix(title, heading, max_tokens=size)
    assert prefix.count("[truncated]") == 2
    assert chunker.count_tokens(prefix) <= min(128, size // 2)
    assert all("section" not in c.evidence_candidate["source_locator"] for c in chunks)
    assert all(c.section == heading for c in chunks)
    assert parsed == before


@pytest.mark.parametrize("use_override", [False, True])
def test_abstract_fallback_uses_identical_bounds_and_real_origin_coordinates(monkeypatch, use_override):
    _settings(monkeypatch)
    text = "\n\t Abstract 超导😀 long unpunctuated words " * 500
    parsed = _paper("")
    parsed.meta.abstract = "" if use_override else text
    parsed.abstract_override = text if use_override else "Unselected override."
    before = deepcopy(parsed)
    chunks = chunker.chunk_paper(parsed)
    assert len(chunks) > 1
    _assert_source(chunks, text, section="Abstract", kind="abstract",
                   path="abstract_override" if use_override else "metadata/abstract")
    assert parsed == before


def test_sections_with_duplicate_names_have_distinct_paths_and_whitespace_is_not_lost(monkeypatch):
    _settings(monkeypatch)
    parsed = _paper(" \r\n\t ", section="Results")
    parsed.sections += [Section("Empty", ""), Section("Results", "alpha\n\nbeta\n\ngamma")]
    chunks = chunker.chunk_paper(parsed)
    assert len(chunks) == 2
    _assert_source(chunks, parsed.sections[0].text, path="sections/0")
    _assert_source(chunks, parsed.sections[2].text, path="sections/2")
    assert "alpha\n\nbeta\n\ngamma" in chunks[1].text


def test_control_heading_uses_path_without_invalid_locator_label(monkeypatch):
    _settings(monkeypatch)
    parsed = _paper("Original prose", section="Methods\nFurther details")
    chunks = chunker.chunk_paper(parsed)
    _assert_source(chunks, parsed.sections[0].text, section=parsed.sections[0].name)
    assert "section" not in chunks[0].evidence_candidate["source_locator"]


@pytest.mark.parametrize("size,overlap", [
    (0, 0), (-1, 0), (63, 0), (True, 0), (512.0, 0), ("512", 0),
    (512, -1), (512, 512), (512, 513), (512, True), (512, 1.0), (512, "1"),
])
def test_invalid_settings_fail_even_for_empty_paper(monkeypatch, size, overlap):
    _settings(monkeypatch, size, overlap)
    with pytest.raises(ValueError):
        chunker.chunk_paper(_paper(""))


@pytest.mark.parametrize("text", ["😀" * 3, "𓀀" * 3, "汉字", "e\u0301", "🧑🏽‍🔬"])
@pytest.mark.parametrize("budget", [0, 1, 2, 3, 8])
def test_tail_never_inserts_replacement_characters_or_exceeds_budget(text, budget):
    tail = chunker._tail_by_tokens(text, budget)
    assert text.endswith(tail)
    assert chunker.count_tokens(tail) <= budget
    assert "�" not in tail
    tail.encode("utf-8", errors="strict")


def test_normal_prefix_is_unchanged_and_only_shortened_metadata_is_marked():
    assert chunker.build_bounded_prefix("Synthetic", "Results", max_tokens=512) == (
        "Title: Synthetic\nSection: Results\n\n"
    )
    title_only = chunker.build_bounded_prefix("Long " * 2000, "Results", max_tokens=512)
    assert title_only.count("[truncated]") == 1
    assert "Section: Results\n\n" in title_only
    section_only = chunker.build_bounded_prefix("Synthetic", "Long " * 2000, max_tokens=512)
    assert section_only.count("[truncated]") == 1
    assert section_only.startswith("Title: Synthetic\n")


def test_full_text_helper_is_strict_and_does_not_truncate_an_atomic_claim():
    prefix = chunker.build_bounded_prefix("Synthetic", "Facts", max_tokens=64)
    body = "No superconductivity detected down to 2 K at 20 GPa."
    assert chunker.fits_token_budget(prefix + body, max_tokens=64)
    assert chunker.require_token_budget(prefix + body, max_tokens=64) == chunker.count_tokens(prefix + body)
    too_long = prefix + body * 100
    assert chunker.fits_token_budget(too_long, max_tokens=64) is False
    with pytest.raises(ValueError, match="Complete chunk text"):
        chunker.require_token_budget(too_long, max_tokens=64)


@pytest.mark.parametrize("invalid", [None, 1, True, b"body", "bad\ud800text"])
def test_full_text_helpers_reject_non_text_or_unencodable_unicode(invalid):
    with pytest.raises(ValueError):
        chunker.require_token_budget(invalid, max_tokens=512)
    with pytest.raises(ValueError):
        chunker.build_bounded_prefix(invalid, "Results", max_tokens=512)


def test_unencodable_source_is_rejected_instead_of_repaired(monkeypatch):
    _settings(monkeypatch)
    with pytest.raises(ValueError, match="Unicode"):
        chunker.chunk_paper(_paper("Source with invalid \ud800 code point"))


def test_seeded_mixed_unicode_and_whitespace_never_loses_a_source_position(monkeypatch):
    rng = random.Random(693)
    alphabet = ["LaH10", " e\u0301 ", "超导", "😀", "𓀀", "\r\n\r\n", "\t", ". ", "=", "-0.2"]
    for size, overlap in [(64, 1), (64, 60), (128, 32), (512, 64)]:
        _settings(monkeypatch, size, overlap)
        for _ in range(8):
            source = "".join(rng.choice(alphabet) for _ in range(180))
            chunks = chunker.chunk_paper(_paper(source))
            _assert_source(chunks, source, size=size, overlap=overlap)


def test_chunker_version_changes_when_source_window_contract_changes():
    assert chunker.CHUNKER_VERSION == "sclib-section-chunker/2.0.0"
