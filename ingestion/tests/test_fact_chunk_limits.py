"""Facts are atomic scientific retrieval aids, never truncated assertions."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from ingestion.chunk.chunker import count_tokens
from ingestion.config import IngestionSettings, get_settings
from ingestion.extract.fact_sentences import (
    FactChunkLimitError,
    build_authorized_chunks,
    build_fact_chunks,
    fact_sentence,
)
from ingestion.models import ApsArticleMeta


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setenv("CHUNK_SIZE_TOKENS", "512")
    monkeypatch.setenv("CHUNK_OVERLAP_TOKENS", "64")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def meta(title="Synthetic title"):
    return ApsArticleMeta(doi="10.0000/Synthetic.FactBounds", title=title, authors=[], abstract="Synthetic abstract.")


def test_long_title_does_not_split_or_truncate_negative_fact_conditions():
    paper = meta("A long synthetic title 测试 😀 " * 1000)
    record = {"formula": "Nb", "result_status": "not_detected", "tc_kelvin": "< 5 K",
              "minimum_temperature_k": "1.5 K", "pressure_gpa": "2 GPa", "magnetic_field_t": "3 T",
              "knowledge_origin": "Observed", "source_role": "cited", "sample_form": "thin_film"}
    before = deepcopy(record)
    chunk, = build_fact_chunks(paper, [record], start_index=1)
    sentence = fact_sentence(record)
    assert chunk.text.endswith(sentence)
    assert "[truncated]" in chunk.text.split("\n\n", 1)[0]
    assert "not detected" in chunk.text and "minimum test temperature = 1.5 K" in chunk.text
    assert "at 2 GPa" in chunk.text and "magnetic field = 3 T" in chunk.text
    assert "source role: cited" in chunk.text and "Tc =" not in chunk.text
    assert chunk.token_count == count_tokens(chunk.text) <= 512
    assert chunk.materials_mentioned == [before] and record == before
    assert paper.title.endswith("😀 ") and len(paper.title) > 1000


def test_oversized_atomic_fact_aborts_without_partial_output_or_source_text_in_error(monkeypatch):
    monkeypatch.setenv("CHUNK_SIZE_TOKENS", "64")
    monkeypatch.setenv("CHUNK_OVERLAP_TOKENS", "0")
    get_settings.cache_clear()
    record = {"formula": "Nb", "tc_kelvin": "9.2 K", "result_status": "not_detected", "minimum_temperature_k": "1 K",
              "knowledge_origin": "Observed", "source_role": "primary", "sample_form": "PRIVATE_RESULT_VALUE " * 6}
    before = deepcopy(record)
    with pytest.raises(FactChunkLimitError) as caught:
        build_authorized_chunks(meta(), [record])
    assert str(caught.value) == "atomic_fact_exceeds_complete_text_limit"
    assert "PRIVATE_RESULT_VALUE" not in str(caught.value) and record == before


@pytest.mark.parametrize("size,overlap", [(True, 0), (512.0, 64), (512, False), (63, 0), (64, 64), (512, -1), ("512.0", "64")])
def test_bad_configuration_fails_before_ingestion(size, overlap):
    with pytest.raises(ValidationError):
        IngestionSettings(_env_file=None, database_url="postgresql://unused@127.0.0.1:1/unused",
                          chunk_size_tokens=size, chunk_overlap_tokens=overlap)


def test_integer_environment_representation_is_supported():
    settings = IngestionSettings(_env_file=None, database_url="postgresql://unused@127.0.0.1:1/unused",
                                 chunk_size_tokens="512", chunk_overlap_tokens="64")
    assert settings.chunk_size_tokens == 512 and settings.chunk_overlap_tokens == 64


@pytest.mark.parametrize("start", [True, -1, 32768, 1.0, "1"])
def test_fact_start_index_is_explicit_and_bounded(start):
    with pytest.raises(ValueError, match="starting index"):
        build_fact_chunks(meta(), [], start_index=start)
